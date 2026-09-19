"""CT-REPOSITORY: in-memory persistence adapter contract tests.

RED → GREEN coverage:
- concurrent quota reservation consumes at most one remaining slot
- expected-revision CAS rejects stale app/calibration writes
- attempt fence rejects stale worker commits
- event ordering by stable (source_time, event_id)
- pagination cursors and limits
- immutable version storage
- idempotent run creation
- deletion generation tracking
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from vision_app.contracts.models import (
    AppSpec,
    AppVersion,
    BoxN,
    Calibration,
    Event,
    EvidenceManifest,
    EvidencePolicy,
    ExecutionLimits,
    FrameRef,
    MoneyMicrousd,
    PointN,
    ResourceId,
    RunProgress,
    SourceAsset,
    SourceTimeMs,
    TimeRange,
    TrackedRule,
    TrackedRulesSpec,
    UtcTimestamp,
    VisionApp,
)
from vision_app.persistence import InMemoryRepository
from vision_app.security.identity.models import Principal


@pytest.fixture
def principal() -> Principal:
    return Principal(
        user_id="user-1",
        email="user-1@example.com",
        workspace_ids=frozenset({"workspace-a"}),
    )


@pytest.fixture
def other_principal() -> Principal:
    return Principal(
        user_id="user-2",
        email="user-2@example.com",
        workspace_ids=frozenset({"workspace-b"}),
    )


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


def _frame(source_id: str = "source-1") -> FrameRef:
    return FrameRef(
        source_id=ResourceId(source_id),
        source_hash="a" * 64,
        pts=0,
        time_base_num=1,
        time_base_den=1000,
        source_time_ms=SourceTimeMs(0),
        sequence=0,
        width=1920,
        height=1080,
        transform_id=ResourceId("transform-1"),
    )


def _app(title: str = "Test App") -> VisionApp:
    return VisionApp(
        id=ResourceId("app-1"),
        workspace_id=ResourceId("workspace-a"),
        title=title,
        revision=0,
    )


def _spec() -> AppSpec:
    return TrackedRulesSpec(
        title="Demo",
        objective="Count people crossing a line",
        evidence_policy=EvidencePolicy(),
        approved_action_refs=[],
        limits=ExecutionLimits(),
        kind="tracked_rules",
        rules=[
            TrackedRule(
                rule_id=ResourceId("rule-1"),
                capability_id="tracked.line_crossing",
                object_classes=["person"],
            )
        ],
    )


def _version(app_id: str = "app-1", version_id: str = "version-1") -> AppVersion:
    return AppVersion(
        id=ResourceId(version_id),
        app_id=ResourceId(app_id),
        workspace_id=ResourceId("workspace-a"),
        parent_id=None,
        spec=_spec(),
        capability_manifest={},
        model_manifest={},
        validation_report=[],
        created_by=ResourceId("user-1"),
        created_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )


def _calibration(
    calibration_id: str = "calibration-1",
    source_id: str = "source-1",
) -> Calibration:
    return Calibration(
        id=ResourceId(calibration_id),
        source_id=ResourceId(source_id),
        workspace_id=ResourceId("workspace-a"),
        camera_binding="camera-a",
        revision=1,
        reference_frame=_frame(source_id),
        lanes={},
        lines={"line-1": [PointN(x=0.0, y=0.5), PointN(x=1.0, y=0.5)]},
        rois={"roi-1": BoxN(x1=0.1, y1=0.1, x2=0.9, y2=0.9)},
        governing_signals={},
        confirmed_by=ResourceId("user-1"),
        confirmed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        scene_fingerprint="fp-1",
    )


@dataclass(frozen=True, slots=True)
class _RunRecord:
    id: str
    workspace_id: str
    version_id: str
    asset_id: str
    calibration_id: str | None
    selected_attempt_id: str | None = None


def _run(run_id: str = "run-1", workspace_id: str = "workspace-a") -> _RunRecord:
    return _RunRecord(
        id=run_id,
        workspace_id=workspace_id,
        version_id="version-1",
        asset_id="asset-1",
        calibration_id="calibration-1",
    )


def _event(
    event_id: str = "event-1",
    run_id: str = "run-1",
    attempt_id: str = "attempt-1",
    start_ms: int = 1000,
    machine_decision: str = "supported",
    human_review: str = "unreviewed",
) -> Event:
    return Event(
        id=ResourceId(event_id),
        run_id=ResourceId(run_id),
        attempt_id=ResourceId(attempt_id),
        spec_version_id=ResourceId("version-1"),
        calibration_id=ResourceId("calibration-1"),
        source_range=TimeRange(
            start_ms=SourceTimeMs(start_ms),
            end_ms=SourceTimeMs(start_ms + 1000),
        ),
        rule_id=ResourceId("rule-1"),
        track_refs=[],
        facts={},
        evidence=EvidenceManifest(
            requested_range=TimeRange(
                start_ms=SourceTimeMs(start_ms),
                end_ms=SourceTimeMs(start_ms + 1000),
            ),
            actual_range=None,
            state="pending",
        ),
        machine_decision=machine_decision,
        human_review=human_review,
        revision=0,
    )


def _progress(
    run_id: str = "run-1",
    attempt_id: str = "attempt-1",
    sequence: int = 1,
    phase: str = "running",
) -> RunProgress:
    return RunProgress(
        run_id=ResourceId(run_id),
        attempt_id=ResourceId(attempt_id),
        phase=phase,  # type: ignore[arg-type]
        processed_ranges=[],
        requested_samples=0,
        processed_samples=0,
        review_backlog=0,
        cancel_requested=False,
        usage=MoneyMicrousd(0),
        sequence=sequence,
    )


class TestGenericOwnershipAndCAS:
    @pytest.mark.asyncio
    async def test_add_immutable_stores_version_once(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        version = _version()
        assert await repo.add_immutable("app_version", version.id.root, version) is True
        assert await repo.add_immutable("app_version", version.id.root, version) is False
        stored = await repo.get_owned("app_version", version.id.root, principal)
        assert stored == version

    @pytest.mark.asyncio
    async def test_compare_and_swap_requires_expected_revision(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        app = _app()
        await repo.add_immutable("vision_app", app.id.root, app)

        stale = app.model_copy(update={"title": "Stale"})
        assert await repo.compare_and_swap("vision_app", app.id.root, 1, stale) is False

        updated = app.model_copy(update={"title": "Updated", "revision": 1})
        assert await repo.compare_and_swap("vision_app", app.id.root, 0, updated) is True

        reverted = updated.model_copy(update={"title": "Reverted"})
        assert await repo.compare_and_swap("vision_app", app.id.root, 0, reverted) is False

    @pytest.mark.asyncio
    async def test_list_owned_filters_by_workspace(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        app_a = VisionApp(
            id=ResourceId("app-a"),
            workspace_id=ResourceId("workspace-a"),
            title="A",
            revision=0,
        )
        app_b = VisionApp(
            id=ResourceId("app-b"),
            workspace_id=ResourceId("workspace-b"),
            title="B",
            revision=0,
        )
        await repo.add_immutable("vision_app", "app-a", app_a)
        await repo.add_immutable("vision_app", "app-b", app_b)

        items = await repo.list_owned("vision_app", principal)
        assert [item.id.root for item in items] == ["app-a"]

    @pytest.mark.asyncio
    async def test_get_owned_rejects_cross_tenant(
        self,
        repo: InMemoryRepository,
        principal: Principal,
        other_principal: Principal,
    ) -> None:
        app = VisionApp(
            id=ResourceId("app-a"),
            workspace_id=ResourceId("workspace-a"),
            title="A",
            revision=0,
        )
        await repo.add_immutable("vision_app", "app-a", app)
        assert await repo.get_owned("vision_app", "app-a", principal) is not None
        assert await repo.get_owned("vision_app", "app-a", other_principal) is None


class TestQuotaReservation:
    @pytest.mark.asyncio
    async def test_concurrent_reservations_consume_only_one_remaining_slot(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        # Workspace budget has exactly one slot of 100 micro-USD remaining.
        repo._seed_budget("workspace-a", 100)  # type: ignore[attr-defined]

        async def reserve(reservation_id: str) -> dict[str, Any] | None:
            return await repo.reserve_quota(
                "workspace-a", "owner-1", 100, reservation_id, principal
            )

        results = await asyncio.gather(
            reserve("reservation-1"),
            reserve("reservation-2"),
            reserve("reservation-3"),
        )
        successes = [r for r in results if r is not None]
        assert len(successes) == 1, (
            "only one concurrent reservation may consume the final budget slot"
        )

    @pytest.mark.asyncio
    async def test_released_reservation_allows_new_reservation(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        repo._seed_budget("workspace-a", 100)
        await repo.reserve_quota("workspace-a", "owner-1", 100, "reservation-1", principal)
        assert await repo.release_reservation("reservation-1") is True
        second = await repo.reserve_quota(
            "workspace-a", "owner-1", 100, "reservation-2", principal
        )
        assert second is not None


class TestAttemptFencing:
    @pytest.mark.asyncio
    async def test_stale_worker_fence_is_rejected(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        assert await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1) is True

        # A stale worker with a lower fence cannot overwrite.
        event = _event(event_id="event-1")
        assert await repo.commit_event("run-1", "attempt-1", fence=0, event=event) is False
        assert await repo.commit_event("run-1", "attempt-1", fence=1, event=event) is True

        progress = _progress(sequence=1)
        assert (
            await repo.commit_progress("run-1", "attempt-1", fence=0, progress=progress)
            is False
        )
        assert (
            await repo.commit_progress("run-1", "attempt-1", fence=2, progress=progress) is True
        )

    @pytest.mark.asyncio
    async def test_higher_fence_overwrites_lower_fence_event(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1)
        first = _event(event_id="event-1", machine_decision="candidate")
        second = first.model_copy(update={"machine_decision": "supported"})
        await repo.commit_event("run-1", "attempt-1", fence=1, event=first)
        await repo.commit_event("run-1", "attempt-1", fence=2, event=second)
        stored = await repo.list_events("run-1")
        assert stored[0][0].machine_decision == "supported"


class TestEventOrderingAndPagination:
    @pytest.mark.asyncio
    async def test_events_sorted_by_source_time_then_event_id(
        self,
        repo: InMemoryRepository,
    ) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1)

        ids = [(500, "event-b"), (100, "event-z"), (100, "event-a"), (300, "event-m")]
        for start_ms, event_id in ids:
            await repo.commit_event(
                "run-1", "attempt-1", fence=1, event=_event(event_id=event_id, start_ms=start_ms)
            )

        events, _ = await repo.list_events("run-1")
        keys = [(e.source_range.start_ms.root, e.id.root) for e in events]
        assert keys == [(100, "event-a"), (100, "event-z"), (300, "event-m"), (500, "event-b")]

    @pytest.mark.asyncio
    async def test_event_pagination_cursor(self, repo: InMemoryRepository) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1)

        for i in range(5):
            await repo.commit_event(
                "run-1",
                "attempt-1",
                fence=1,
                event=_event(event_id=f"event-{i}", start_ms=i * 1000),
            )

        page1, cursor1 = await repo.list_events("run-1", limit=2)
        assert [e.id.root for e in page1] == ["event-0", "event-1"]
        assert cursor1 is not None

        page2, cursor2 = await repo.list_events("run-1", after=cursor1, limit=2)
        assert [e.id.root for e in page2] == ["event-2", "event-3"]
        assert cursor2 is not None

        page3, cursor3 = await repo.list_events("run-1", after=cursor2, limit=2)
        assert [e.id.root for e in page3] == ["event-4"]
        assert cursor3 is None

    @pytest.mark.asyncio
    async def test_progress_paginated_by_sequence(self, repo: InMemoryRepository) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1)

        for seq in range(1, 6):
            await repo.commit_progress(
                "run-1", "attempt-1", fence=1, progress=_progress(sequence=seq)
            )

        page1 = await repo.list_progress("run-1", "attempt-1", after_sequence=0, limit=2)
        assert [p.sequence for p in page1] == [1, 2]

        page2 = await repo.list_progress("run-1", "attempt-1", after_sequence=2, limit=2)
        assert [p.sequence for p in page2] == [3, 4]


class TestRunLifecycle:
    @pytest.mark.asyncio
    async def test_create_run_is_idempotent(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        run = _run()
        result1 = await repo.create_run(run, principal, "idem-1", "reservation-1")
        result2 = await repo.create_run(run, principal, "idem-1", "reservation-1")
        assert result1 is not None
        assert result2 is not None
        assert result1.id == result2.id

    @pytest.mark.asyncio
    async def test_finalize_run_selects_attempt(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        run = _run()
        await repo.add_immutable("run", run.id, run)
        await repo.claim_attempt("run-1", "attempt-1", "worker-1", fence=1)
        assert await repo.finalize_run("run-1", "attempt-1", "completed") is True
        stored = await repo.get_owned("run", "run-1", principal)
        assert stored.selected_attempt_id == "attempt-1"


class TestDeletionGeneration:
    @pytest.mark.asyncio
    async def test_mark_deletion_increments_generation(
        self,
        repo: InMemoryRepository,
        principal: Principal,
    ) -> None:
        asset = SourceAsset(
            id=ResourceId("asset-1"),
            workspace_id=ResourceId("workspace-a"),
            byte_size=100,
            codec="mp4",
            width=1920,
            height=1080,
            duration_ms=SourceTimeMs(30000),
            storage_ref=ResourceId("ref-1"),
            sha256="0" * 64,
            state="ready",
            generation=1,
        )
        await repo.add_immutable("asset", "asset-1", asset)
        assert (
            await repo.mark_deletion("asset", "asset-1", generation=1, principal=principal) is True
        )
        assert (
            await repo.mark_deletion(
                "asset", "asset-1", generation=1, principal=principal
            )
            is False
        )
        stored = await repo.get_owned("asset", "asset-1", principal)
        assert stored.state == "deleting"
