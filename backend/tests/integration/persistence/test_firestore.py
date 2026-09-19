"""IT01: Firestore-backed Repository integration tests.

NOTE: This suite is intentionally skipped when the Firestore emulator is not
available. The scaffolding below documents the expected interface and
validates import paths; it does not fall back to the in-memory implementation.

These tests target an isolated Firestore emulator. When the emulator is not
available or google-cloud-firestore is not installed, the suite skips with an
explicit reason rather than silently passing or failing on import.
"""
from datetime import datetime, timezone
import os
import uuid

import pytest

from vision_app.contracts.models import (
    AppVersion,
    Event,
    EvidenceManifest,
    MoneyMicrousd,
    ResourceId,
    RunProgress,
    SourceTimeMs,
    TimeRange,
    UtcTimestamp,
    VisionApp,
)
from vision_app.security.identity.models import Principal

try:
    from vision_app.persistence.firestore import FirestoreRepository
except ImportError:
    FirestoreRepository = None  # type: ignore[misc, assignment]


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def skip_if_unavailable(firestore_available):
    available, reason = firestore_available
    if not available:
        pytest.skip(reason)


@pytest.fixture
def project_id() -> str:
    return os.environ.get("FIRESTORE_PROJECT_ID") or f"vision-app-it-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def principal() -> Principal:
    return Principal(
        user_id="user-1",
        email="user-1@example.com",
        workspace_ids=frozenset({"workspace-it"}),
    )


@pytest.fixture
def vision_app(principal: Principal) -> VisionApp:
    return VisionApp(
        id=ResourceId("app-it-1"),
        workspace_id=ResourceId("workspace-it"),
        title="Integration app",
        revision=1,
    )


@pytest.fixture
def app_version(principal: Principal, vision_app: VisionApp) -> AppVersion:
    return AppVersion(
        id=ResourceId("version-it-1"),
        app_id=vision_app.id,
        workspace_id=vision_app.workspace_id,
        spec={"kind": "semantic_windows"},  # minimal dict for storage roundtrip
        capability_manifest={},
        model_manifest={},
        validation_report=["ok"],
        created_by=ResourceId(principal.user_id),
        created_at=UtcTimestamp(datetime.now(timezone.utc)),
    )


@pytest.fixture
def repo(project_id: str):
    from google.cloud import firestore

    client = firestore.Client(project=project_id)
    return FirestoreRepository(client=client)


@pytest.mark.asyncio
async def test_create_version_with_firestore(
    skip_if_unavailable, repo: FirestoreRepository, principal, vision_app, app_version
):
    await repo.add_immutable("apps", vision_app.id.root, vision_app)

    ok, app = await repo.create_version(
        vision_app.id.root, 1, app_version, principal
    )
    assert ok
    assert app is not None
    assert app.draft_version_id.root == app_version.id.root


@pytest.mark.asyncio
async def test_atomic_reservation_with_firestore(
    skip_if_unavailable, repo: FirestoreRepository, principal
):
    repo._seed_budget("workspace-it", 1000)  # type: ignore[attr-defined]

    run = RunProgress(
        run_id=ResourceId("run-it-1"),
        attempt_id=ResourceId("attempt-it-1"),
        phase="queued",
        processed_ranges=[],
        requested_samples=10,
        processed_samples=0,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=0,
    )
    ok, stored = await repo.reserve_quota_and_create_run(
        workspace_id="workspace-it",
        owner_id="run-it-1",
        microusd=1000,
        reservation_id="res-it-1",
        run=run,
        principal=principal,
        idempotency_key="idem-it-1",
    )
    assert ok
    assert stored is not None

    # A second concurrent reservation for the final slot is rejected.
    run2 = run.model_copy(update={"run_id": ResourceId("run-it-2")})
    ok2, _ = await repo.reserve_quota_and_create_run(
        workspace_id="workspace-it",
        owner_id="run-it-2",
        microusd=1,
        reservation_id="res-it-2",
        run=run2,
        principal=principal,
        idempotency_key="idem-it-2",
    )
    assert not ok2


@pytest.mark.asyncio
async def test_attempt_fence_with_firestore(
    skip_if_unavailable, repo: FirestoreRepository, principal
):
    repo._seed_budget("workspace-it", 1000)  # type: ignore[attr-defined]

    run = RunProgress(
        run_id=ResourceId("run-it-fence"),
        attempt_id=ResourceId("attempt-it-fence"),
        phase="queued",
        processed_ranges=[],
        requested_samples=10,
        processed_samples=0,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=0,
    )
    await repo.reserve_quota_and_create_run(
        workspace_id="workspace-it",
        owner_id="run-it-fence",
        microusd=100,
        reservation_id="res-it-fence",
        run=run,
        principal=principal,
        idempotency_key="idem-it-fence",
    )

    assert await repo.claim_attempt(
        "run-it-fence", "attempt-a", "worker-1", fence=1
    )

    event = Event(
        id=ResourceId("event-it-fence"),
        run_id=ResourceId("run-it-fence"),
        attempt_id=ResourceId("attempt-a"),
        spec_version_id=ResourceId("version-it-1"),
        calibration_id=None,
        source_range=TimeRange(
            start_ms=SourceTimeMs(0), end_ms=SourceTimeMs(100)
        ),
        rule_id=ResourceId("rule-it-1"),
        track_refs=[],
        facts={},
        evidence=EvidenceManifest(
            requested_range=TimeRange(
                start_ms=SourceTimeMs(0), end_ms=SourceTimeMs(100)
            ),
            actual_range=None,
            state="pending",
        ),
        machine_decision="supported",
        human_review="unreviewed",
        revision=1,
    )
    assert await repo.commit_event(
        "run-it-fence", "attempt-a", fence=1, event=event
    )

    # Old fence is rejected.
    stale = event.model_copy(update={"id": ResourceId("event-it-stale")})
    assert not await repo.commit_event(
        "run-it-fence", "attempt-a", fence=0, event=stale
    )
