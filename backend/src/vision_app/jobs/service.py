"""Repository-backed job dispatch and fenced attempt coordination."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from vision_app.contracts.models import RunProgress
from vision_app.contracts.ports import Clock, EventSink, IdFactory, JobExecutor, Repository

_KIND = "job_run"
_MAX_CAS = 100


class JobError(RuntimeError):
    pass


class JobNotFound(JobError):
    pass


class JobConflict(JobError):
    pass


class StaleAttempt(JobError):
    pass


class LeaseExpired(StaleAttempt):
    pass


class JobState(StrEnum):
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = {JobState.COMPLETED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELLED}


@dataclass(frozen=True)
class AttemptLease:
    run_id: str
    attempt_id: str
    fence: int
    expires_at: datetime


@dataclass(frozen=True)
class JobSnapshot:
    run_id: str
    state: JobState
    invocation_id: str | None
    cancel_requested: bool
    attempt_id: str | None
    fence: int
    lease_expires_at: datetime | None
    progress_sequence: int


class JobDispatchService:
    """Coordinates durable intent; execution remains at-least-once and fenced."""

    def __init__(
        self,
        repository: Repository,
        executor: JobExecutor,
        event_sink: EventSink,
        clock: Clock,
        ids: IdFactory,
        *,
        lease_seconds: int = 30,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._repository = repository
        self._executor = executor
        self._sink = event_sink
        self._clock = clock
        self._ids = ids
        self._lease = timedelta(seconds=lease_seconds)

    async def create(self, run_id: str) -> JobSnapshot:
        if not run_id:
            raise ValueError("run_id is required")
        initial = self._initial(run_id)
        await self._repository.compare_and_swap(_KIND, run_id, 0, initial)
        return await self.get(run_id)

    async def get(self, run_id: str) -> JobSnapshot:
        return self._snapshot(await self._read(run_id))

    async def dispatch(self, run_id: str) -> str:
        state = await self._read(run_id)
        current = JobState(state["state"])
        if current in _TERMINAL:
            raise JobConflict(f"cannot dispatch terminal run: {current}")
        if state["invocation_id"] is not None:
            return str(state["invocation_id"])
        if current is JobState.QUEUED:
            await self._mutate(run_id, lambda value: value.update(state=JobState.DISPATCHING.value))
        # submit(run_id) may have succeeded even if its response was lost. Executors must
        # use run_id as their idempotency key; state fencing rejects duplicate workers too.
        invocation_id = await self._executor.submit(run_id)

        def record(value: dict[str, Any]) -> None:
            if value["invocation_id"] is None:
                value["invocation_id"] = invocation_id
            # An in-process executor may have already completed the run inline.
            if JobState(value["state"]) not in _TERMINAL:
                value["state"] = JobState.DISPATCHED.value

        await self._mutate(run_id, record)
        return str((await self._read(run_id))["invocation_id"])

    async def claim(self, run_id: str) -> AttemptLease:
        now = self._clock.now()
        result: AttemptLease | None = None

        def claim_state(value: dict[str, Any]) -> None:
            nonlocal result
            state = JobState(value["state"])
            expiry = value["lease_expires_at"]
            if state in _TERMINAL or value["cancel_requested"]:
                raise JobConflict("run is terminal or cancelled")
            if value["attempt_id"] is not None and expiry is not None and now < expiry:
                result = self._lease_from(value)
                return
            value["fence"] += 1
            value["attempt_id"] = self._ids.new("attempt")
            value["lease_expires_at"] = now + self._lease
            value["heartbeat_at"] = now
            value["progress_sequence"] = -1
            value["state"] = JobState.RUNNING.value
            result = self._lease_from(value)

        await self._mutate(run_id, claim_state)
        assert result is not None
        return result

    async def heartbeat(self, run_id: str, attempt_id: str, fence: int) -> AttemptLease:
        now = self._clock.now()
        result: AttemptLease | None = None

        def renew(value: dict[str, Any]) -> None:
            nonlocal result
            self._validate_attempt(value, attempt_id, fence)
            if value["lease_expires_at"] <= now:
                raise LeaseExpired(attempt_id)
            value["heartbeat_at"] = now
            value["lease_expires_at"] = now + self._lease
            result = self._lease_from(value)

        await self._mutate(run_id, renew)
        assert result is not None
        return result

    async def reconcile(self, run_id: str) -> AttemptLease | None:
        state = await self._read(run_id)
        if JobState(state["state"]) in _TERMINAL or state["cancel_requested"]:
            return None
        if state["invocation_id"] is None:
            await self.dispatch(run_id)
        expiry = state["lease_expires_at"]
        if state["attempt_id"] is None or (expiry is not None and expiry <= self._clock.now()):
            return await self.claim(run_id)
        return self._lease_from(state)

    async def cancel(self, run_id: str) -> None:
        def cancelled(value: dict[str, Any]) -> None:
            value["cancel_requested"] = True
            value["state"] = JobState.CANCELLED.value
            value["lease_expires_at"] = self._clock.now()

        await self._mutate(run_id, cancelled)
        invocation = (await self._read(run_id))["invocation_id"]
        if invocation is not None:
            await self._executor.cancel(str(invocation))

    async def commit_progress(self, progress: RunProgress, fence: int) -> None:
        run_id = progress.run_id.root
        should_emit = False

        def commit(value: dict[str, Any]) -> None:
            nonlocal should_emit
            self._validate_attempt(value, progress.attempt_id.root, fence)
            if value["cancel_requested"]:
                raise StaleAttempt("run was cancelled")
            previous = int(value["progress_sequence"])
            if progress.sequence == previous:
                return
            if progress.sequence < previous:
                raise ValueError("progress sequence must be monotonically increasing")
            value["progress_sequence"] = progress.sequence
            should_emit = True

        await self._mutate(run_id, commit)
        if should_emit:
            await self._sink.progress(progress, fence)

    async def finish(self, run_id: str, attempt_id: str, fence: int, state: JobState) -> None:
        if state not in _TERMINAL or state is JobState.CANCELLED:
            raise ValueError("finish requires completed, partial, or failed")

        def finish_state(value: dict[str, Any]) -> None:
            self._validate_attempt(value, attempt_id, fence)
            value["state"] = state.value
            value["lease_expires_at"] = None

        await self._mutate(run_id, finish_state)

    async def _read(self, run_id: str) -> dict[str, Any]:
        value = await self._repository.get_owned(_KIND, run_id, run_id)
        if value is None:
            raise JobNotFound(run_id)
        return value  # type: ignore[no-any-return]

    async def _mutate(self, run_id: str, mutation: Any) -> None:
        for _ in range(_MAX_CAS):
            value = deepcopy(await self._read(run_id))
            revision = int(value["revision"])
            mutation(value)
            value["revision"] = revision + 1
            if await self._repository.compare_and_swap(_KIND, run_id, revision, value):
                return
        raise JobConflict("job remained contended")

    @staticmethod
    def _initial(run_id: str) -> dict[str, Any]:
        return {"revision": 0, "run_id": run_id, "state": JobState.QUEUED.value,
                "invocation_id": None, "cancel_requested": False, "attempt_id": None,
                "fence": 0, "lease_expires_at": None, "heartbeat_at": None,
                "progress_sequence": -1}

    @staticmethod
    def _validate_attempt(value: dict[str, Any], attempt_id: str, fence: int) -> None:
        if value["attempt_id"] != attempt_id or int(value["fence"]) != fence:
            raise StaleAttempt(attempt_id)

    @staticmethod
    def _lease_from(value: dict[str, Any]) -> AttemptLease:
        return AttemptLease(str(value["run_id"]), str(value["attempt_id"]),
                            int(value["fence"]), value["lease_expires_at"])

    @staticmethod
    def _snapshot(value: dict[str, Any]) -> JobSnapshot:
        return JobSnapshot(str(value["run_id"]), JobState(value["state"]),
                           value["invocation_id"], bool(value["cancel_requested"]),
                           value["attempt_id"], int(value["fence"]),
                           value["lease_expires_at"], int(value["progress_sequence"]))
