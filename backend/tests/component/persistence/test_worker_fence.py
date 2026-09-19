"""CT-REPOSITORY: attempt claim/fence and stale worker rejection.

Core cases covered by test_repository.py::TestAttemptFencing.
This file adds a sanity check using the public claim flow with a Pydantic run model.
"""
import pytest

from vision_app.contracts.models import Event, EvidenceManifest, MoneyMicrousd, ResourceId, RunProgress, TimeRange, SourceTimeMs
from vision_app.persistence.memory import InMemoryRepository


@pytest.mark.asyncio
async def test_claim_attempt_with_run_progress_model(
    repository: InMemoryRepository, workspace_id, principal
):
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

    event = Event(
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
        human_review="unreviewed",
        revision=1,
    )
    assert await repository.commit_event("run-001", "attempt-001", fence=1, event=event)

    # A stale worker with an old fence cannot commit.
    stale = event.model_copy(update={"id": ResourceId("event-stale")})
    assert not await repository.commit_event("run-001", "attempt-001", fence=0, event=stale)
