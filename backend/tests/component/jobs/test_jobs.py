"""CT-JOBS: deterministic dispatch, attempts, leases, cancellation and progress."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from vision_app.contracts.models import (
    MoneyMicrousd,
    ResourceId,
    RunProgress,
    SourceTimeMs,
    TimeRange,
)
from vision_app.jobs import (
    InMemoryEventSink,
    InMemoryJobExecutor,
    JobDispatchService,
    JobState,
    LeaseExpired,
    StaleAttempt,
)


class Repository:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}
        self.lock = asyncio.Lock()

    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        del principal
        async with self.lock:
            return deepcopy(self.values.get((kind, resource_id)))

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        async with self.lock:
            current = self.values.get((kind, resource_id))
            if (0 if current is None else current["revision"]) != revision:
                return False
            self.values[(kind, resource_id)] = deepcopy(value)
            return True


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class Ids:
    def __init__(self) -> None:
        self.next = 0

    def new(self, prefix: str) -> str:
        self.next += 1
        return f"{prefix}-{self.next}"


@pytest.fixture
def harness() -> tuple[JobDispatchService, InMemoryJobExecutor, InMemoryEventSink, Clock]:
    clock = Clock()
    executor = InMemoryJobExecutor()
    sink = InMemoryEventSink()
    service = JobDispatchService(Repository(), executor, sink, clock, Ids(), lease_seconds=10)
    return service, executor, sink, clock


@pytest.mark.asyncio
async def test_lost_dispatch_response_retry_is_idempotent_by_run_state(harness: Any) -> None:
    service, executor, _, _ = harness
    await service.create("run-1")
    executor.raise_after_submit_once = True

    with pytest.raises(ConnectionError):
        await service.dispatch("run-1")
    invocation = await service.dispatch("run-1")
    duplicate = await service.dispatch("run-1")

    assert invocation == duplicate
    assert executor.submission_count == 1
    assert (await service.get("run-1")).state is JobState.DISPATCHED


@pytest.mark.asyncio
async def test_lease_expiry_revokes_old_attempt_and_increments_fence(harness: Any) -> None:
    service, _, _, clock = harness
    await service.create("run-1")
    await service.dispatch("run-1")
    first = await service.claim("run-1")
    clock.advance(11)

    with pytest.raises(LeaseExpired):
        await service.heartbeat("run-1", first.attempt_id, first.fence)
    second = await service.reconcile("run-1")

    assert second is not None
    assert second.attempt_id != first.attempt_id
    assert second.fence == first.fence + 1


@pytest.mark.asyncio
async def test_cancellation_propagates_and_stops_worker(harness: Any) -> None:
    service, executor, _, _ = harness
    started = asyncio.Event()
    continued = False

    async def worker(cancelled: asyncio.Event) -> None:
        nonlocal continued
        started.set()
        await cancelled.wait()
        await asyncio.sleep(0)
        continued = True

    executor.worker = worker
    await service.create("run-1")
    await service.dispatch("run-1")
    await started.wait()
    await service.cancel("run-1")
    await executor.wait_all()

    snapshot = await service.get("run-1")
    assert executor.cancelled_invocations == [snapshot.invocation_id]
    assert continued  # worker observed cooperative cancellation and exited
    assert snapshot.state is JobState.CANCELLED
    assert snapshot.cancel_requested


@pytest.mark.asyncio
async def test_stale_attempt_cannot_publish_after_replacement(harness: Any) -> None:
    service, _, sink, clock = harness
    await service.create("run-1")
    await service.dispatch("run-1")
    old = await service.claim("run-1")
    clock.advance(11)
    current = await service.reconcile("run-1")
    assert current is not None

    with pytest.raises(StaleAttempt):
        await service.commit_progress(progress(old.attempt_id, 1), old.fence)
    await service.commit_progress(progress(current.attempt_id, 1), current.fence)

    assert [item.attempt_id.root for item in sink.progress_updates] == [current.attempt_id]


@pytest.mark.asyncio
async def test_progress_is_ordered_idempotent_and_commits_coverage(harness: Any) -> None:
    service, _, sink, _ = harness
    await service.create("run-1")
    await service.dispatch("run-1")
    attempt = await service.claim("run-1")

    await service.commit_progress(progress(attempt.attempt_id, 1, 0, 100), attempt.fence)
    await service.commit_progress(progress(attempt.attempt_id, 1, 0, 100), attempt.fence)
    with pytest.raises(ValueError, match="sequence"):
        await service.commit_progress(progress(attempt.attempt_id, 0), attempt.fence)
    await service.commit_progress(progress(attempt.attempt_id, 2, 100, 200), attempt.fence)

    assert [item.sequence for item in sink.progress_updates] == [1, 2]
    assert [(r.start_ms.root, r.end_ms.root) for r in sink.coverage] == [(0, 100), (100, 200)]


def progress(attempt_id: str, sequence: int, start: int = 0, end: int = 1) -> RunProgress:
    return RunProgress(
        run_id=ResourceId("run-1"),
        attempt_id=ResourceId(attempt_id),
        phase="running",
        processed_ranges=[TimeRange(start_ms=SourceTimeMs(start), end_ms=SourceTimeMs(end))],
        requested_samples=2,
        processed_samples=sequence,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=sequence,
    )
