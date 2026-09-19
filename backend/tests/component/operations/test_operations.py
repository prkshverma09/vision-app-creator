import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from vision_app.operations.ledger import (
    BudgetExceeded,
    BudgetLedgerService,
    ReservationNotFound,
)
from vision_app.operations.limits import (
    DeadlineExceeded,
    ExecutionLimits,
    LimitExceeded,
    LimitGuard,
    run_with_deadline,
)
from vision_app.operations.tracing import InMemoryTraceSink, SafeTraceSink
from vision_app.operations.usage import UsageAggregator


class AtomicRepository:
    """CAS repository double; all accounting state still lives in the repository."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}
        self._lock = asyncio.Lock()

    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        del principal
        async with self._lock:
            value = self.values.get((kind, resource_id))
            return deepcopy(value)

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        async with self._lock:
            current = self.values.get((kind, resource_id))
            current_revision = 0 if current is None else current["revision"]
            if current_revision != revision:
                return False
            self.values[(kind, resource_id)] = deepcopy(value)
            return True


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


@pytest.mark.asyncio
async def test_concurrent_calls_cannot_both_reserve_last_budget() -> None:
    repo = AtomicRepository()
    ledger = BudgetLedgerService(repo, Ids(), budget_microusd=100)

    results = await asyncio.gather(
        ledger.reserve("workspace-1", 100),
        ledger.reserve("workspace-1", 100),
        return_exceptions=True,
    )

    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, BudgetExceeded) for result in results) == 1
    snapshot = await ledger.snapshot("workspace-1")
    assert snapshot.estimated_reserved_microusd == 100
    assert snapshot.measured_microusd == 0


@pytest.mark.asyncio
async def test_settle_retries_aggregates_estimated_and_measured_usage() -> None:
    repo = AtomicRepository()
    ledger = BudgetLedgerService(repo, Ids(), budget_microusd=1_000)
    usage = UsageAggregator()

    first = await ledger.reserve("owner", 300)
    await ledger.settle(first, 120)
    usage.record_call(estimated_microusd=300, measured_microusd=120, failed=True)
    second = await ledger.reserve("owner", 250)
    await ledger.settle(second, 200)
    usage.record_call(estimated_microusd=250, measured_microusd=200, retry=True)

    snapshot = await ledger.snapshot("owner")
    assert snapshot.estimated_total_microusd == 550
    assert snapshot.measured_microusd == 320
    assert snapshot.estimated_reserved_microusd == 0
    assert usage.snapshot().model_calls == 2
    assert usage.snapshot().failed_calls == 1
    assert usage.snapshot().retried_calls == 1


@pytest.mark.asyncio
async def test_cancellation_settles_in_flight_and_releases_only_unused_work() -> None:
    repo = AtomicRepository()
    ledger = BudgetLedgerService(repo, Ids(), budget_microusd=1_000)
    started = await ledger.reserve("owner", 400)
    not_started = await ledger.reserve("owner", 300)

    await ledger.cancel([(started, 175)], [not_started])

    snapshot = await ledger.snapshot("owner")
    assert snapshot.measured_microusd == 175
    assert snapshot.estimated_reserved_microusd == 0
    assert snapshot.released_microusd == 525
    with pytest.raises(ReservationNotFound):
        await ledger.release(started)


def test_trace_sink_redacts_auth_signed_urls_prompts_and_media_bytes() -> None:
    sink = InMemoryTraceSink()
    safe = SafeTraceSink(sink)
    secret = b"raw prompt and image bytes"
    signed_url = "https://storage.test/video?X-Goog-Signature=secret&token=abc"

    safe.record(
        "model.call",
        {
            "Authorization": "Bearer raw-auth-token",
            "source_url": signed_url,
            "prompt": secret,  # type: ignore[dict-item]
            "safe_count": 3,
        },
    )

    rendered = repr(sink.records)
    assert "raw-auth-token" not in rendered
    assert "X-Goog-Signature" not in rendered
    assert "raw prompt" not in rendered
    assert "secret" not in rendered
    assert sink.records[0].attributes["safe_count"] == 3


def test_telemetry_failure_never_interrupts_analysis() -> None:
    class BrokenSink:
        def record(self, name: str, attributes: dict[str, str | int | bool]) -> None:
            raise RuntimeError("telemetry unavailable")

    SafeTraceSink(BrokenSink()).record("analysis", {"safe": True})


def test_job_build_frame_call_output_and_concurrency_limits() -> None:
    guard = LimitGuard(
        ExecutionLimits(jobs=1, builds=1, frames=2, calls=1, output_bytes=4, concurrency=1)
    )
    guard.consume_job()
    guard.consume_build()
    guard.consume_frames(2)
    guard.consume_call()
    guard.consume_output(4)
    with pytest.raises(LimitExceeded):
        guard.consume_job()
    with pytest.raises(LimitExceeded):
        guard.consume_build()
    with pytest.raises(LimitExceeded):
        guard.consume_frames()
    with pytest.raises(LimitExceeded):
        guard.consume_call()
    with pytest.raises(LimitExceeded):
        guard.consume_output(1)
    permit = guard.acquire()
    with pytest.raises(LimitExceeded):
        guard.acquire()
    permit.release()


@pytest.mark.asyncio
async def test_finite_model_deadline() -> None:
    async def blocked() -> None:
        await asyncio.Event().wait()

    with pytest.raises(DeadlineExceeded):
        await run_with_deadline(blocked(), timeout_seconds=0.01)

    deadline = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DeadlineExceeded):
        LimitGuard(ExecutionLimits(deadline=deadline)).check_deadline()
