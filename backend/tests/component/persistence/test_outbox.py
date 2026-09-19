"""CT-REPOSITORY: outbox atomic commands."""
import pytest

from vision_app.contracts.models import DeliveryAttempt, Event, EvidenceManifest, MoneyMicrousd, ResourceId, RunProgress, TimeRange, SourceTimeMs
from vision_app.persistence.memory import InMemoryRepository


@pytest.fixture
def seeded_run(repository: InMemoryRepository, workspace_id, principal):
    repository._seed_budget(workspace_id, 1000)
    run = RunProgress(
        run_id=ResourceId("run-001"),
        attempt_id=ResourceId("attempt-001"),
        phase="queued",
        processed_ranges=[],
        requested_samples=10,
        processed_samples=0,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=0,
    )
    async def _seed():
        await repository.reserve_quota_and_create_run(
            workspace_id=workspace_id,
            owner_id="run-001",
            microusd=1000,
            reservation_id="res-001",
            run=run,
            principal=principal,
            idempotency_key="idem-001",
        )
        assert await repository.claim_attempt("run-001", "attempt-001", "worker-1", fence=1)
        return run, 1
    return _seed


@pytest.fixture
def event() -> Event:
    return Event(
        id=ResourceId("event-001"),
        run_id=ResourceId("run-001"),
        attempt_id=ResourceId("attempt-001"),
        spec_version_id=ResourceId("version-001"),
        calibration_id=None,
        source_range=TimeRange(start_ms=SourceTimeMs(0), end_ms=SourceTimeMs(100)),
        rule_id=ResourceId("rule-001"),
        track_refs=[],
        facts={},
        evidence=EvidenceManifest(
            requested_range=TimeRange(start_ms=SourceTimeMs(0), end_ms=SourceTimeMs(100)),
            actual_range=None,
            state="pending",
        ),
        machine_decision="supported",
        human_review="confirmed_by_user",
        revision=1,
    )


@pytest.fixture
def delivery_attempt() -> DeliveryAttempt:
    return DeliveryAttempt(
        id=ResourceId("delivery-001"),
        event_id=ResourceId("event-001"),
        event_revision=1,
        destination_ref="webhook://example.com/sink",
        permission_version=1,
        payload={"event_id": "event-001"},
    )


@pytest.mark.asyncio
async def test_create_delivery_once_per_event_revision_and_destination(
    repository: InMemoryRepository,
    principal,
    seeded_run,
    event,
    delivery_attempt,
):
    _, fence = await seeded_run()
    await repository.commit_event("run-001", "attempt-001", fence, event)

    ok1, id1 = await repository.create_delivery("event-001", delivery_attempt, principal)
    assert ok1
    assert id1 == delivery_attempt.id.root

    # A duplicate creation with the same id is atomically rejected.
    ok2, id2 = await repository.create_delivery("event-001", delivery_attempt, principal)
    assert not ok2
    assert id2 is None

    # A delivery for a different destination succeeds.
    delivery3 = delivery_attempt.model_copy(update={
        "id": ResourceId("delivery-003"),
        "destination_ref": "webhook://other.example.com/sink",
    })
    ok3, _ = await repository.create_delivery("event-001", delivery3, principal)
    assert ok3


@pytest.mark.asyncio
async def test_delivery_claim_and_dispatch(
    repository: InMemoryRepository,
    principal,
    seeded_run,
    event,
    delivery_attempt,
):
    _, fence = await seeded_run()
    await repository.commit_event("run-001", "attempt-001", fence, event)

    ok, delivery_id = await repository.create_delivery("event-001", delivery_attempt, principal)
    assert ok

    claimed = await repository.claim_delivery(delivery_id, principal)
    assert claimed is not None
    assert claimed.state == "dispatched"

    # A claimed delivery cannot be claimed again.
    claimed2 = await repository.claim_delivery(delivery_id, principal)
    assert claimed2 is None

    # mark_delivery_dispatched on a non-pending delivery fails.
    assert not await repository.mark_delivery_dispatched(delivery_id, principal)
