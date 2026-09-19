"""I04 deterministic race, budget, cancellation, and replay verification."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest

from vision_app.actions import (
    ActionContext,
    ActionService,
    InMemoryDeliveryStore,
    InMemoryWebhookSink,
    Permission,
)
from vision_app.contracts.models import (
    Event,
    EvidenceManifest,
    ResourceId,
    SourceTimeMs,
    TimeRange,
    VisionApp,
)
from vision_app.operations.ledger import BudgetExceeded, BudgetLedgerService
from vision_app.persistence import InMemoryRepository
from vision_app.security.identity.models import Principal

pytestmark = pytest.mark.integration


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def new(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


class _AtomicRepository:
    """Repository-port in-memory adapter used to force real CAS contention."""

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
            current_revision = 0 if current is None else int(current["revision"])
            if current_revision != revision:
                return False
            self.values[(kind, resource_id)] = deepcopy(value)
            return True


@dataclass(frozen=True)
class _Run:
    id: str
    workspace_id: str
    version_id: str = "version-1"
    asset_id: str = "asset-1"
    calibration_id: str | None = None
    selected_attempt_id: str | None = None


def _principal() -> Principal:
    return Principal("user-a", None, frozenset({"workspace-a"}))


def _event() -> Event:
    interval = TimeRange(start_ms=SourceTimeMs(100), end_ms=SourceTimeMs(200))
    return Event(
        id=ResourceId("event-1"),
        run_id=ResourceId("run-1"),
        attempt_id=ResourceId("attempt-1"),
        spec_version_id=ResourceId("version-1"),
        calibration_id=None,
        source_range=interval,
        rule_id=ResourceId("rule-1"),
        track_refs=[],
        facts={},
        evidence=EvidenceManifest(requested_range=interval, actual_range=None, state="pending"),
        machine_decision="supported",
        human_review="unreviewed",
        revision=0,
    )


@pytest.mark.asyncio
async def test_concurrent_app_revisions_commit_one_version_without_ghosts() -> None:
    repo = InMemoryRepository()
    principal = _principal()
    app = VisionApp(
        id=ResourceId("app-1"),
        workspace_id=ResourceId("workspace-a"),
        title="race",
        revision=0,
    )
    await repo.add_immutable("apps", "app-1", app)

    results = await asyncio.gather(
        *(
            repo.create_version("app-1", 0, {"id": f"version-{index}"}, principal)
            for index in range(12)
        )
    )

    assert sum(committed for committed, _ in results) == 1
    assert len(repo._store["workspace-a"]["versions"]) == 1
    stored = await repo.get_owned("apps", "app-1", principal)
    assert stored.revision == 1


@pytest.mark.asyncio
async def test_concurrent_run_submissions_create_one_run_without_ghosts() -> None:
    repo = InMemoryRepository()
    principal = _principal()
    run = _Run("run-1", "workspace-a")

    results = await asyncio.gather(
        *(repo.create_run(run, principal, "same-request", "reservation-1") for _ in range(12))
    )

    assert {result.id for result in results} == {"run-1"}
    stored = await repo.get_owned("run", "run-1", principal)
    assert stored is not None
    assert len(repo._store["workspace-a"]["run"]) == 1  # one durable side effect


@pytest.mark.asyncio
async def test_concurrent_reviews_select_exactly_one_revision() -> None:
    repo = InMemoryRepository()
    principal = _principal()
    await repo.add_immutable("run", "run-1", _Run("run-1", "workspace-a"))
    await repo.claim_attempt("run-1", "attempt-1", "worker", fence=1)
    assert await repo.commit_event("run-1", "attempt-1", 1, _event())

    results = await asyncio.gather(
        repo.review_event("run-1", "event-1", 0, "confirmed_by_user", principal),
        repo.review_event("run-1", "event-1", 0, "rejected_by_user", principal),
    )
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].revision == 1
    events, _ = await repo.list_events("run-1")
    assert len(events) == 1
    assert events[0].revision == 1


@pytest.mark.asyncio
async def test_concurrent_delivery_attempts_have_one_outbox_record_and_send() -> None:
    store = InMemoryDeliveryStore()
    sink = InMemoryWebhookSink()
    service = ActionService(store, sink, signing_secret=b"integration-secret")
    context = ActionContext(
        workspace_id="workspace-a",
        event_id="event-1",
        event_revision=1,
        machine_decision="supported",
        human_review="confirmed_by_user",
        selected_finalized=True,
        run_mode="normal",
        action_ref="permission-1",
        explicitly_enabled=True,
        deleted=False,
        cancelled=False,
        budget_available=True,
    )
    permission = Permission(
        "permission-1", 1, "workspace-a", "destination-1", True
    )

    queued = await asyncio.gather(*(service.enqueue(context, permission) for _ in range(16)))
    assert len({record.id for record in queued}) == 1
    delivered = await asyncio.gather(
        *(service.deliver(queued[0].id, context, permission) for _ in range(8))
    )
    assert {record.state.value for record in delivered} == {"delivered"}
    assert len(store.records) == 1
    assert len(sink.requests) == 1


@pytest.mark.asyncio
async def test_budget_exhaustion_is_atomic_and_has_no_losing_side_effect() -> None:
    repository = _AtomicRepository()
    ledger = BudgetLedgerService(repository, _Ids(), budget_microusd=100)

    results = await asyncio.gather(
        *(ledger.reserve("workspace-a", 100) for _ in range(10)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, str) for result in results) == 1
    assert sum(isinstance(result, BudgetExceeded) for result in results) == 9
    snapshot = await ledger.snapshot("workspace-a")
    assert snapshot.active_reservations == 1
    assert snapshot.estimated_reserved_microusd == 100
    assert snapshot.measured_microusd == 0


@pytest.mark.asyncio
async def test_mid_run_cancellation_keeps_partial_progress_and_releases_budget() -> None:
    repository = _AtomicRepository()
    ledger = BudgetLedgerService(repository, _Ids(), budget_microusd=1_000)
    in_flight = await ledger.reserve("workspace-a", 400)
    not_started = await ledger.reserve("workspace-a", 300)
    partial_progress = {"processed_samples": 7, "requested_samples": 20, "state": "partial"}

    await ledger.cancel([(in_flight, 175)], [not_started])

    snapshot = await ledger.snapshot("workspace-a")
    assert partial_progress == {
        "processed_samples": 7,
        "requested_samples": 20,
        "state": "partial",
    }
    assert snapshot.active_reservations == 0
    assert snapshot.measured_microusd == 175
    assert snapshot.released_microusd == 525


@pytest.mark.asyncio
async def test_duplicate_progress_finalize_run_and_review_are_harmless() -> None:
    repo = InMemoryRepository()
    principal = _principal()
    await repo.add_immutable("run", "run-1", _Run("run-1", "workspace-a"))
    await repo.claim_attempt("run-1", "attempt-1", "worker", fence=1)
    assert await repo.commit_event("run-1", "attempt-1", 1, _event())

    first = await repo.review_event(
        "run-1", "event-1", 0, "confirmed_by_user", principal
    )
    replay = await repo.review_event(
        "run-1", "event-1", 0, "confirmed_by_user", principal
    )
    assert first is not None and replay is None
    assert await repo.finalize_run("run-1", "attempt-1", "completed")
    assert await repo.finalize_run("run-1", "attempt-1", "completed")
    events, _ = await repo.list_events("run-1")
    assert len(events) == 1
    assert events[0].revision == 1
