"""Backend composition root for the Vision App Creator.

This module wires all production and local-profile adapters behind a single
``create_app(profile, settings)`` factory. It intentionally contains no product
business logic; that lives in the domain services it composes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from vision_app.actions.eligibility import eligibility
from vision_app.actions.models import ActionContext, Permission
from vision_app.actions.outbox import ActionService, InMemoryDeliveryStore
from vision_app.actions.transport import InMemoryWebhookSink
from vision_app.api.actions import (
    ActionApiDependencies,
    ActionEvent,
    create_actions_router,
)
from vision_app.api.actions.router import (
    DeletionStatus,
    DeliveryStatus,
    EnabledAction,
)
from vision_app.api.builder import (
    BuilderDependencies,
    add_builder_exception_handlers,
    create_builder_router,
)
from vision_app.api.media import (
    MediaDependencies,
    add_media_exception_handlers,
    create_media_router,
)
from vision_app.api.runs import RunDependencies, RunRecord, create_runs_router
from vision_app.api.runs.router import RunCreate
from vision_app.security.identity.errors import PublicSecurityError
from vision_app.api.v1 import V1Dependencies, create_v1_media_router, create_v1_router
from vision_app.applications import AppService, CalibrationService, VersionService
from vision_app.builder.agent import BuilderAgent
from vision_app.builder.ports import InMemoryBuildTurnStore, SpecValidator
from vision_app.contracts.models import (
    AppVersion,
    BoxN,
    Calibration,
    DecodedFrame,
    Detection,
    DetectionBatch,
    Event,
    FrameRef,
    ModelInvocationMetadata,
    MoneyMicrousd,
    ObservationQuality,
    ProposedVersion,
    ResourceId,
    RunProgress,
    SignalObservation,
    SourceAsset,
    SourceTimeMs,
    TrackedRule,
    TrackedRulesSpec,
    UtcTimestamp,
)
from vision_app.contracts.ports import (
    Clock,
    CompilerModel,
    EventSink,
    IdFactory,
    PreviewService,
    SceneInspector,
    SignalObserver,
)
from vision_app.evidence.extractor import EvidenceExtractor
from vision_app.jobs import InMemoryJobExecutor, JobDispatchService
from vision_app.jobs.executors import Worker
from vision_app.jobs.service import JobState
from vision_app.media.decoder import LocalVideoDecoder
from vision_app.operations.ledger import BudgetLedgerService
from vision_app.operations.limits import ExecutionLimits
from vision_app.operations.tracing import InMemoryTraceSink, SafeTraceSink
from vision_app.perception.detection.config import DetectorConfig
from vision_app.perception.tracking.byte_track import ByteTrackFactory
from vision_app.persistence.memory import InMemoryRepository
from vision_app.persistence.snapshot import LocalStateSnapshot, SnapshotError
from vision_app.providers.gemini.live import MAX_INLINE_BYTES, MAX_VIDEO_DURATION_MS
from vision_app.privacy.service import DeletionService, ResourceRecord
from vision_app.providers.gemini.compiler import CompilerResult
from vision_app.runtime.context import RunContext
from vision_app.runtime.engine import RunEngine
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    OwnershipResolver,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.models import Principal
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity
from vision_app.storage.local import FileSystemMediaStore
from vision_app.validation.registry import REGISTRY
from vision_app.validation.validator import validate_app_spec


@dataclass(frozen=True)
class LocalProfileSettings:
    """Trusted configuration for the local integration profile.

    Values are supplied by the test harness or local launcher, never parsed from an
    untrusted request.
    """

    data_dir: Path
    clock: Clock = field(default_factory=lambda: _SystemClock())
    id_factory: IdFactory = field(default_factory=lambda: _SequentialIdFactory())
    fixture_annotation: Path | None = None
    budget_microusd: int = 1_000_000
    test_user_id: str = "local-user"
    test_email: str | None = None
    test_workspace_id: str = "workspace-local"
    test_token: str = "token-local"
    analysis_mode: str = "scripted"
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str = "gemini-3.6-flash"


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _SequentialIdFactory:
    def __init__(self) -> None:
        import itertools

        self._counter = itertools.count(1)

    def new(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter):04d}"


# ---------------------------------------------------------------------------
# Local profile adapters
# ---------------------------------------------------------------------------


class _RepositoryOwnershipResolver(OwnershipResolver):
    """Resolves ownership by querying the in-memory repository."""

    def __init__(self, core_repo: InMemoryRepository) -> None:
        self._core = core_repo

    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None:
        workspace_id = await self._core.resolve_workspace(family.value, resource_id)
        if workspace_id is None:
            return None
        return ResourceOwnership(family, resource_id, workspace_id)


class _MediaRepositoryAdapter:
    """Asset store implementing the media repository surface and the privacy
    deletion repository surface used by :class:`DeletionService`.
    """

    def __init__(self, store: FileSystemMediaStore) -> None:
        self._store = store
        self._assets: dict[str, SourceAsset] = {}
        self._revisions: dict[str, int] = {}

    async def save_asset(self, asset: SourceAsset) -> None:
        self._assets[asset.id.root] = asset
        self._revisions[asset.id.root] = 0

    async def get_asset(self, asset_id: str, workspace_id: str) -> SourceAsset | None:
        asset = self._assets.get(asset_id)
        if asset is None or asset.workspace_id.root != workspace_id:
            return None
        return asset

    def workspace_for_asset(self, asset_id: str) -> str | None:
        asset = self._assets.get(asset_id)
        return asset.workspace_id.root if asset is not None else None

    # DeletionService repository surface
    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        if kind != "asset":
            return None
        asset = self._assets.get(resource_id)
        if asset is None:
            return None
        # Accept either a Principal-like object or a workspace-id string.
        if isinstance(principal, str):
            allowed = principal == asset.workspace_id.root
        elif isinstance(principal, Principal):
            allowed = principal.is_member(asset.workspace_id.root)
        else:
            allowed = False
        if not allowed:
            return None
        return ResourceRecord(
            kind="asset",
            id=resource_id,
            workspace_id=asset.workspace_id.root,
            generation=asset.generation,
            revision=self._revisions.get(resource_id, 0),
        )

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        if kind != "asset":
            return False
        asset = self._assets.get(resource_id)
        if asset is None or self._revisions.get(resource_id, 0) != revision:
            return False
        if isinstance(value, ResourceRecord):
            new_state = asset.state
            new_deleted_at = asset.deleted_at
            if value.hard_deleted:
                new_state = "deleted"
            elif value.deleted_at is not None:
                new_state = "deleting"
                new_deleted_at = UtcTimestamp(value.deleted_at)
            self._assets[resource_id] = asset.model_copy(
                update={
                    "state": new_state,
                    "generation": value.generation,
                    "deleted_at": new_deleted_at,
                }
            )
            self._revisions[resource_id] = revision + 1
        return True


_FAMILY_TO_COLLECTION: dict[ResourceFamily, str] = {
    ResourceFamily.APP: "vision_app",
    ResourceFamily.VERSION: "app_version",
    ResourceFamily.CALIBRATION: "calibration",
    ResourceFamily.RUN: "run",
    ResourceFamily.EVENT: "events",
    ResourceFamily.RESERVATION: "reservation",
    ResourceFamily.ACTION_DESTINATION: "action_destination",
}


class _ComposedOwnershipResolver(OwnershipResolver):
    """Queries core repository and media adapter for resource ownership."""

    def __init__(
        self,
        core_repo: InMemoryRepository,
        media_repo: _MediaRepositoryAdapter,
        local_workspace_id: str = "workspace-local",
    ) -> None:
        self._core = core_repo
        self._media = media_repo
        self._local_workspace_id = local_workspace_id

    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None:
        if family == ResourceFamily.ASSET:
            workspace_id = self._media.workspace_for_asset(resource_id)
            if workspace_id is not None:
                return ResourceOwnership(family, resource_id, workspace_id)
        if family == ResourceFamily.ACTION_DESTINATION:
            # Local profile treats action destinations as workspace-scoped.
            return ResourceOwnership(
                family, resource_id, self._local_workspace_id
            )
        collection = _FAMILY_TO_COLLECTION.get(family)
        if collection is not None:
            workspace_id = await self._core.resolve_workspace(collection, resource_id)
            if workspace_id is not None:
                return ResourceOwnership(family, resource_id, workspace_id)
        return None


class _PersistenceEventSink(EventSink):
    """Routes engine events/progress through the durable repository."""

    def __init__(self, core_repo: InMemoryRepository, snapshot: LocalStateSnapshot,
                 checkpoint: Callable[[], Awaitable[None]]) -> None:
        self._core = core_repo
        self._snapshot = snapshot
        self._checkpoint = checkpoint

    async def upsert(self, event: Event, fence: int) -> None:
        async with self._snapshot.transaction():
            await self._core.commit_event(
                event.run_id.root, event.attempt_id.root, fence, event
            )
            await self._checkpoint()

    async def progress(self, progress: RunProgress, fence: int) -> None:
        async with self._snapshot.transaction():
            await self._core.commit_progress(
                progress.run_id.root, progress.attempt_id.root, fence, progress
            )
            await self._checkpoint()


class _LocalRunRepository:
    """Run repository backed by the in-memory persistence adapter."""

    def __init__(
        self,
        core_repo: InMemoryRepository,
        id_factory: IdFactory,
        analysis_mode: str = "scripted",
    ) -> None:
        self._core = core_repo
        self._ids = id_factory
        self._analysis_mode = analysis_mode

    def _principal(self, workspace_id: str) -> Principal:
        return Principal("local-owner", None, frozenset({workspace_id}))

    async def create(
        self, workspace_id: str, request: Any, idempotency_key: str
    ) -> RunRecord:
        reservation_id = self._ids.new("reservation")
        run_id = self._ids.new("run")
        version = await _get_version(self._core, request.version_id)
        record = RunRecord(
            app_id=version.app_id.root if version else None,
            analysis_mode=self._analysis_mode,
            id=run_id,
            workspace_id=workspace_id,
            version_id=request.version_id,
            asset_id=request.asset_id,
            calibration_id=request.calibration_id,
        )
        created = await self._core.create_run(
            record, self._principal(workspace_id), idempotency_key, reservation_id
        )
        return cast(RunRecord, created)

    async def get(self, run_id: str) -> RunRecord | None:
        for cols in self._core._store.values():
            doc = cols.get("run", {}).get(run_id)
            if doc is not None and not doc.deleted:
                value = doc.value
                if isinstance(value, RunRecord):
                    return value
        return None

    async def events(self, run_id: str, attempt_id: str) -> list[Event]:
        items, _ = await self._core.list_events(run_id, after=None, limit=10_000)
        return [item for item in items if item.attempt_id.root == attempt_id]

    async def event(self, run_id: str, attempt_id: str, event_id: str) -> Event | None:
        events = await self.events(run_id, attempt_id)
        for item in events:
            if item.id.root == event_id:
                return item
        return None

    async def progress(self, run_id: str, attempt_id: str) -> list[RunProgress]:
        return await self._core.list_progress(
            run_id, attempt_id, after_sequence=-1, limit=10_000
        )


class _UnavailableAnalysis:
    async def compile(self, instruction: str, context: dict[str, Any]) -> Any:
        raise RuntimeError("Gemini analysis is not configured.")

    async def run(self, ctx: RunContext, *, fence: int, is_cancelled: Callable[[], bool]) -> Any:
        raise RuntimeError("Gemini analysis is not configured.")


class _NoOpSceneInspector(SceneInspector):
    async def metadata(self, source_id: str, principal: Any) -> dict[str, Any]:
        return {"source_id": source_id, "available": True}

    async def sample(
        self, source_id: str, times: list[SourceTimeMs], principal: Any
    ) -> list[FrameRef]:
        return []


class _NoOpPreviewService(PreviewService):
    async def start(self, version_id: str, source_id: str) -> str:
        return "preview-run-local"

    async def read(self, run_id: str) -> RunProgress:
        raise NotImplementedError()


class _ScriptedCompiler(CompilerModel):
    """Local compiler that returns a fixed, valid tracked-rules spec.

    This avoids any cloud or model dependency while still exercising the real
    builder agent orchestration, tool schema, and spec validator.
    """

    def __init__(self, id_factory: IdFactory) -> None:
        self._ids = id_factory

    async def compile(self, instruction: str, context: dict[str, Any]) -> Any:
        version_id = str(self._ids.new("version"))
        app_id = context.get("app_id", "app-local")
        workspace_id = context.get("workspace_id", "workspace-local")
        spec = TrackedRulesSpec(
            kind="tracked_rules",
            title="Red light violation",
            objective=instruction,
            rules=[
                TrackedRule(
                    rule_id=ResourceId("stop_line"),
                    capability_id="tracked.red_phase_crossing",
                    object_classes=["car"],
                )
            ],
        )
        version = AppVersion(
            id=ResourceId(version_id),
            app_id=ResourceId(app_id),
            workspace_id=ResourceId(workspace_id),
            parent_id=None,
            spec=spec,
            capability_manifest={"stop_line": "tracked.red_phase_crossing"},
            model_manifest={"compiler": "scripted-local"},
            validation_report=["compiled"],
            created_by=ResourceId("local-user"),
            created_at=UtcTimestamp(datetime.now(UTC)),
        )
        usage = ModelInvocationMetadata(
            provider="scripted",
            model="scripted-local",
            revision="v1",
            prompt_hash="local",
            input_tokens=0,
            output_tokens=0,
            duration_ms=0,
            retry_count=0,
            adapter_mode="scripted",
            estimated_cost=MoneyMicrousd(0),
        )
        return CompilerResult(
            outcome=ProposedVersion(
                kind="proposed_version",
                version=version,
            ),
            usage=usage,
        )


class _FixtureDetector:
    """Reusable detector driven by a synthetic fixture annotation file.

    The fixture is keyed by ``source_time_ms`` so that every run starts from the
    first frame instead of consuming a shared response queue.
    """

    def __init__(self, annotation_path: Path | None, config: DetectorConfig) -> None:
        if annotation_path is not None and annotation_path.exists():
            annotation = json.loads(annotation_path.read_text())
        else:
            annotation = {"video": {"width": 1, "height": 1}, "frames": []}
        self._annotation = annotation
        self._config = config
        self._frames_by_time = {
            frame["source_time_ms"]: frame for frame in annotation.get("frames", [])
        }
        video = annotation.get("video", {})
        self._video_width = video.get("width", 1)
        self._video_height = video.get("height", 1)

    async def detect(self, frame: DecodedFrame) -> DetectionBatch:
        ann_frame = self._frames_by_time.get(frame.frame_ref.source_time_ms.root)
        detections: list[Detection] = []
        if ann_frame is not None:
            for box in ann_frame.get("boxes", []):
                x1, y1, x2, y2 = box["box_px"]
                detections.append(
                    Detection(
                        class_name="car",
                        box=BoxN(
                            x1=x1 / self._video_width,
                            y1=y1 / self._video_height,
                            x2=x2 / self._video_width,
                            y2=y2 / self._video_height,
                        ),
                        score=0.9,
                        model_ref=self._config.model_name,
                    )
                )
        return DetectionBatch(
            frame_ref=frame.frame_ref,
            detections=detections,
            invocation=ModelInvocationMetadata(
                provider="fixture",
                model=self._config.model_name,
                revision=self._config.checkpoint_revision,
                prompt_hash="",
                input_tokens=0,
                output_tokens=0,
                duration_ms=0,
                retry_count=0,
                adapter_mode="scripted",
                estimated_cost=MoneyMicrousd(0),
            ),
        )


class _AnnotationSignalObserver(SignalObserver):
    """Signal observer driven by per-frame signal states in a fixture annotation."""

    def __init__(self, annotation_path: Path | None, roi_id: str = "signal-1") -> None:
        if annotation_path is not None and annotation_path.exists():
            annotation = json.loads(annotation_path.read_text())
            self._states = {
                f["source_time_ms"]: f["signal_state"] for f in annotation["frames"]
            }
        else:
            self._states = {}
        self._roi_id = roi_id

    def observe(self, frame: DecodedFrame, roi_id: str) -> SignalObservation:
        state = self._states.get(frame.frame_ref.source_time_ms.root, "unknown")
        return SignalObservation(
            roi_id=ResourceId(roi_id),
            source_time_ms=frame.frame_ref.source_time_ms,
            state=state,
            quality=ObservationQuality(),
        )


class _JobStateRepository:
    """Simple in-memory store for JobDispatchService job-run state.

    Job state is execution fencing metadata, not an ownership-protected domain
    resource, so this adapter intentionally ignores the principal argument.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        if kind != "job_run":
            return False
        async with self._lock:
            current = self._jobs.get(resource_id)
            current_revision = 0 if current is None else int(current["revision"])
            if current_revision != revision:
                return False
            self._jobs[resource_id] = deepcopy(value)
            return True

    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any | None:
        del principal
        if kind != "job_run":
            return None
        async with self._lock:
            return deepcopy(self._jobs.get(resource_id))


class _LocalJobExecutor(InMemoryJobExecutor):
    """In-process executor that passes the run ID to the worker factory."""

    def __init__(
        self,
        worker_factory: Callable[[str], Worker],
    ) -> None:
        self.worker = None
        self._worker_factory = worker_factory
        self.raise_after_submit_once = False
        self.submission_count = 0
        self.cancelled_invocations: list[str] = []
        self._by_run: dict[str, str] = {}
        self._cancel: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def submit(self, run_id: str) -> str:
        existing = self._by_run.get(run_id)
        if existing is not None:
            return existing
        invocation = f"invocation-{len(self._by_run) + 1}"
        self._by_run[run_id] = invocation
        self.submission_count += 1
        cancelled = asyncio.Event()
        self._cancel[invocation] = cancelled
        worker = self._worker_factory(run_id)
        # For the local profile we run the worker inline on the request path so
        # the integration test (using TestClient) does not depend on background
        # task scheduling between requests.
        self._tasks[invocation] = asyncio.create_task(worker(cancelled))
        if self.raise_after_submit_once:
            self.raise_after_submit_once = False
            raise ConnectionError("submission response lost")
        return invocation

    async def cancel(self, invocation_id: str) -> None:
        cancelled = self._cancel.get(invocation_id)
        if cancelled is not None and not cancelled.is_set():
            cancelled.set()
            self.cancelled_invocations.append(invocation_id)

    async def query(self, invocation_id: str) -> Any:
        task = self._tasks.get(invocation_id)
        cancelled = self._cancel.get(invocation_id)
        if invocation_id not in self._cancel:
            return {"invocation_id": invocation_id, "state": "unknown"}
        if task is not None and task.cancelled():
            state = "cancelled"
        elif task is not None and task.done():
            state = "failed" if task.exception() is not None else "completed"
        elif cancelled is not None and cancelled.is_set():
            state = "cancelling"
        else:
            state = "running"
        return {"invocation_id": invocation_id, "state": state}


class _LocalActionApiService:
    """In-memory action enablement and delivery service for the local profile."""

    def __init__(self) -> None:
        self.enabled: dict[tuple[str, str], EnabledAction] = {}
        self.deliveries: dict[str, DeliveryStatus] = {}

    async def enable(
        self,
        workspace: str,
        app: str,
        action: str,
        destination_url: str,
        idempotency_key: str,
    ) -> EnabledAction:
        del idempotency_key
        key = (workspace, action)
        value = self.enabled.get(key)
        if value is None:
            permission = Permission(action, 1, workspace, destination_url, True)
            value = EnabledAction(action, app, workspace, destination_url, permission)
            self.enabled[key] = value
        return value

    async def get_enabled(self, workspace: str, action: str) -> EnabledAction | None:
        return self.enabled.get((workspace, action))

    async def create_delivery(
        self, event: ActionEvent, enabled: EnabledAction, idempotency_key: str
    ) -> DeliveryStatus:
        context = ActionContext(
            workspace_id=event.workspace_id,
            event_id=event.id,
            event_revision=event.revision,
            machine_decision=event.machine_decision,
            human_review=event.human_review,
            selected_finalized=event.selected_finalized,
            run_mode="normal",
            action_ref=enabled.id,
            explicitly_enabled=True,
            deleted=False,
            cancelled=False,
            budget_available=True,
        )
        decision = eligibility(context, enabled.permission)
        if not decision.eligible:
            raise RuntimeError(f"action not eligible: {','.join(decision.reasons)}")
        digest = hashlib.sha256(
            f"{event.workspace_id}|{event.id}|{event.revision}|{enabled.id}|{idempotency_key}".encode()
        ).hexdigest()[:24]
        delivery_id = f"delivery-{digest}"
        delivery = DeliveryStatus(
            id=delivery_id,
            workspace_id=event.workspace_id,
            run_id=event.run_id,
            event_id=event.id,
            event_revision=event.revision,
            action_id=enabled.id,
        )
        self.deliveries[delivery_id] = delivery
        return delivery

    async def get_delivery(self, delivery_id: str) -> DeliveryStatus | None:
        return self.deliveries.get(delivery_id)

    def preview(self, event: ActionEvent, enabled: EnabledAction) -> dict[str, Any]:
        svc = ActionService(
            store=InMemoryDeliveryStore(),
            transport=InMemoryWebhookSink(),
            signing_secret=b"local",
        )
        context = ActionContext(
            workspace_id=event.workspace_id,
            event_id=event.id,
            event_revision=event.revision,
            machine_decision=event.machine_decision,
            human_review=event.human_review,
            selected_finalized=event.selected_finalized,
            run_mode="normal",
            action_ref=enabled.id,
            explicitly_enabled=True,
            deleted=False,
            cancelled=False,
            budget_available=True,
        )
        return svc.preview(context)


class _LocalPrivacyService:
    """Minimal local deletion service that operates on the media adapter."""

    def __init__(
        self,
        media_repo: _MediaRepositoryAdapter,
        store: FileSystemMediaStore,
    ) -> None:
        self._media_repo = media_repo
        self._store = store
        self._jobs: dict[str, DeletionStatus] = {}

    async def request(
        self,
        deletion_id: str,
        workspace: str,
        kind: str,
        resource_id: str,
        expected_generation: int,
        requested_by: str,
        idempotency_key: str,
    ) -> DeletionStatus:
        del idempotency_key
        if kind != "asset":
            raise RuntimeError("local privacy service only supports asset deletion")
        asset = await self._media_repo.get_asset(resource_id, workspace)
        if asset is None or asset.generation != expected_generation:
            raise RuntimeError("asset generation mismatch")
        job = DeletionStatus(
            id=deletion_id,
            workspace_id=workspace,
            resource_kind=kind,
            resource_id=resource_id,
            requested_by=requested_by,
            state="pending",
            irreversible=False,
        )
        self._jobs[deletion_id] = job
        return job

    async def get(self, deletion_id: str) -> DeletionStatus | None:
        return self._jobs.get(deletion_id)


class _NoOpProviderCleaner:
    async def delete(self, provider_ref: str) -> None:
        return None


class _ActionEventRepository:
    """Action repository reading events from the core repository."""

    def __init__(self, core_repo: InMemoryRepository) -> None:
        self._core = core_repo

    def _find_run_workspace(self, run_id: str) -> str | None:
        for cols in self._core._store.values():
            doc = cols.get("run", {}).get(run_id)
            if doc is not None and not doc.deleted:
                value = doc.value
                if isinstance(value, RunRecord):
                    return value.workspace_id
        return None

    def _event_record(self, event: Event, workspace_id: str) -> ActionEvent:
        return ActionEvent(
            id=event.id.root,
            workspace_id=workspace_id,
            run_id=event.run_id.root,
            revision=event.revision,
            machine_decision=event.machine_decision,
            human_review=event.human_review,
            selected_finalized=True,
        )

    async def get_event(self, event_id: str) -> ActionEvent | None:
        for cols in self._core._store.values():
            doc = cols.get("events", {}).get(event_id)
            if doc is not None and not doc.deleted:
                value = doc.value
                if isinstance(value, Event):
                    workspace_id = self._find_run_workspace(value.run_id.root)
                    if workspace_id is not None:
                        return self._event_record(value, workspace_id)
        return None

    async def review(
        self, event_id: str, expected_revision: int, decision: str, user_id: str
    ) -> ActionEvent:
        event: Event | None = None
        run_id: str | None = None
        for cols in self._core._store.values():
            doc = cols.get("events", {}).get(event_id)
            if doc is not None and not doc.deleted:
                value = doc.value
                if isinstance(value, Event):
                    event = value
                    run_id = value.run_id.root
                    break
        if event is None or run_id is None:
            raise RuntimeError("event not found")
        workspace_id = self._find_run_workspace(run_id)
        if workspace_id is None:
            raise RuntimeError("run not found")
        principal = Principal(user_id, None, frozenset({workspace_id}))
        reviewed = await self._core.review_event(
            run_id, event_id, expected_revision, decision, principal
        )
        if reviewed is None:
            raise RuntimeError("review failed")
        return self._event_record(reviewed, workspace_id)


# ---------------------------------------------------------------------------
# Worker that runs the local runtime engine
# ---------------------------------------------------------------------------


def _create_worker(
    settings: LocalProfileSettings,
    core_repo: InMemoryRepository,
    media_repo: _MediaRepositoryAdapter,
    store: FileSystemMediaStore,
    jobs_service: JobDispatchService,
    engine: Any,
    decoder: LocalVideoDecoder,
    snapshot: LocalStateSnapshot,
    checkpoint: Callable[[], Awaitable[None]],
) -> Callable[[str], Worker]:
    def factory(run_id: str) -> Worker:
        async def worker(cancelled: asyncio.Event) -> None:
            tmp_path: Path | None = None
            lease = None
            heartbeat_task: asyncio.Task[None] | None = None
            try:
                async with snapshot.transaction():
                    lease = await jobs_service.claim(run_id)
                    await core_repo.claim_attempt(
                        run_id, lease.attempt_id, "local-worker", lease.fence
                    )
                    await checkpoint()
                attempt_id, fence = lease.attempt_id, lease.fence

                async def heartbeat() -> None:
                    while True:
                        await asyncio.sleep(10)
                        async with snapshot.transaction():
                            await jobs_service.heartbeat(run_id, attempt_id, fence)
                            await checkpoint()

                heartbeat_task = asyncio.create_task(heartbeat())
                record = await _get_run(core_repo, run_id)
                if record is None:
                    raise RuntimeError(f"run {run_id} not found")

                version = await _get_version(core_repo, record.version_id)
                if version is None:
                    raise RuntimeError(f"version {record.version_id} not found")

                calibration: Calibration | None = None
                if record.calibration_id is not None:
                    calibration = await _get_calibration(
                        core_repo, record.calibration_id
                    )
                    if calibration is None:
                        raise RuntimeError(
                            f"calibration {record.calibration_id} not found"
                        )

                asset = await media_repo.get_asset(
                    record.asset_id, record.workspace_id
                )
                if asset is None or asset.state != "ready":
                    raise RuntimeError("Source video is unavailable.")
                if settings.analysis_mode == "gemini" and (asset.byte_size > MAX_INLINE_BYTES or asset.duration_ms.root > MAX_VIDEO_DURATION_MS):
                    raise RuntimeError("Source video exceeds live analysis limits.")

                meta = await store.get_metadata(asset.storage_ref.root)
                grant = await store.issue_read_grant(
                    meta.owner_id, asset.storage_ref.root
                )
                data = await store.read(grant.grant_id)
                tmp_path = Path(tempfile.mktemp(suffix=".mp4"))
                tmp_path.write_bytes(data)

                run_ctx = RunContext(
                    run_id=ResourceId(run_id),
                    attempt_id=ResourceId(lease.attempt_id),
                    workspace_id=ResourceId(record.workspace_id),
                    owner_id=meta.owner_id,
                    source_id=ResourceId(asset.id.root),
                    source_path=str(tmp_path),
                    storage_ref=asset.storage_ref.root,
                    source_generation=asset.generation,
                    source_sha256=asset.sha256,
                    spec_version_id=ResourceId(version.id.root),
                    spec=version.spec,
                    calibration=calibration,
                    evidence_policy=version.spec.evidence_policy,
                    limits=ExecutionLimits(),
                    review_prompt=None,
                    review_budget=None,
                )

                result = await engine.run(
                    run_ctx, fence=lease.fence, is_cancelled=cancelled.is_set
                )
                async with snapshot.transaction():
                    state = _phase_to_state(result.phase)
                    current = await jobs_service.get(run_id)
                    if state == JobState.CANCELLED or current.cancel_requested:
                        state = JobState.CANCELLED
                        await jobs_service.cancel(run_id)
                    else:
                        await jobs_service.finish(run_id, lease.attempt_id, lease.fence, state)
                    await core_repo.finalize_run(run_id, lease.attempt_id, state.value)
                    await checkpoint()
            except asyncio.CancelledError:
                if lease is not None:
                    async with snapshot.transaction():
                        await jobs_service.cancel(run_id)
                        await core_repo.finalize_run(run_id, lease.attempt_id, JobState.CANCELLED.value)
                        await checkpoint()
                raise
            except Exception:
                if lease is not None:
                    async with snapshot.transaction():
                        current = await jobs_service.get(run_id)
                        if current.state != JobState.CANCELLED:
                            updates = await core_repo.list_progress(run_id, lease.attempt_id, after_sequence=-1, limit=10_000)
                            latest = max(updates, key=lambda item: item.sequence) if updates else None
                            failed_progress = RunProgress(
                                run_id=ResourceId(run_id), attempt_id=ResourceId(lease.attempt_id),
                                phase="failed", processed_ranges=latest.processed_ranges if latest else [],
                                requested_samples=latest.requested_samples if latest else 0,
                                processed_samples=latest.processed_samples if latest else 0,
                                review_backlog=0, cancel_requested=False,
                                usage=latest.usage if latest else MoneyMicrousd(0),
                                sequence=latest.sequence + 1 if latest else 0,
                            )
                            await core_repo.commit_progress(run_id, lease.attempt_id, lease.fence, failed_progress)
                            await jobs_service.finish(run_id, lease.attempt_id, lease.fence, JobState.FAILED)
                            await core_repo.finalize_run(run_id, lease.attempt_id, JobState.FAILED.value)
                        await checkpoint()
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

        return worker

    return factory


async def _get_run(core_repo: InMemoryRepository, run_id: str) -> RunRecord | None:
    for cols in core_repo._store.values():
        doc = cols.get("run", {}).get(run_id)
        if doc is not None and not doc.deleted:
            value = doc.value
            if isinstance(value, RunRecord):
                return value
    return None


async def _get_version(
    core_repo: InMemoryRepository, version_id: str
) -> AppVersion | None:
    for cols in core_repo._store.values():
        doc = cols.get("app_version", {}).get(version_id)
        if doc is not None and not doc.deleted:
            value = doc.value
            if isinstance(value, AppVersion):
                return value
    return None


async def _get_calibration(
    core_repo: InMemoryRepository, calibration_id: str
) -> Calibration | None:
    for cols in core_repo._store.values():
        doc = cols.get("calibration", {}).get(calibration_id)
        if doc is not None and not doc.deleted:
            value = doc.value
            if isinstance(value, Calibration):
                return value
    return None


def _phase_to_state(phase: str) -> JobState:
    mapping = {
        "completed": JobState.COMPLETED,
        "partial": JobState.PARTIAL,
        "failed": JobState.FAILED,
        "cancelled": JobState.CANCELLED,
    }
    return mapping.get(phase, JobState.FAILED)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(profile: str, settings: dict[str, Any] | None = None) -> FastAPI:
    """Create and configure a FastAPI application for the given profile."""
    app = FastAPI(title="Vision App Creator", version="0.1.0")

    if profile in {"local", "live"}:
        options = dict(settings or {})
        if profile == "live":
            options["analysis_mode"] = "gemini"
        _wire_local(app, options)
    else:
        raise NotImplementedError(f"profile {profile!r} is not implemented")

    return app


def _wire_local(app: FastAPI, settings: dict[str, Any]) -> None:
    local = LocalProfileSettings(
        data_dir=Path(settings["data_dir"]),
        clock=settings.get("clock", _SystemClock()),
        id_factory=settings.get("id_factory", _SequentialIdFactory()),
        fixture_annotation=settings.get("fixture_annotation"),
        budget_microusd=settings.get("budget_microusd", 1_000_000),
        test_token=settings.get("test_token", "token-local"),
        test_workspace_id=settings.get("test_workspace_id", "workspace-local"),
        test_user_id=settings.get("test_user_id", "local-user"),
        analysis_mode=settings.get("analysis_mode", "scripted"),
        gemini_api_key=settings.get("gemini_api_key"),
        gemini_model=settings.get("gemini_model", "gemini-3.6-flash"),
    )
    if local.analysis_mode not in {"scripted", "gemini"}:
        raise ValueError("analysis_mode must be scripted or gemini")

    core_repo = InMemoryRepository()
    snapshot = LocalStateSnapshot(local.data_dir)
    jobs_repo = _JobStateRepository()

    async def checkpoint() -> None:
        await snapshot.save(core_repo, media_repo, v1_dependencies, jobs_repo, local.id_factory)

    store = FileSystemMediaStore(
        data_dir=local.data_dir,
        max_bytes=MAX_INLINE_BYTES if local.analysis_mode == "gemini" else 250_000_000,
        clock=local.clock,
    )
    media_repo = _MediaRepositoryAdapter(store)

    identity = FakeIdentityVerifier(
        {
            local.test_token: TestIdentity(
                local.test_user_id,
                local.test_email,
                frozenset({local.test_workspace_id}),
            )
        },
        profile="local",
    )

    resolver = _ComposedOwnershipResolver(
        core_repo, media_repo, local_workspace_id=local.test_workspace_id
    )
    boundary = AuthorizationBoundary(resolver)

    # Application services
    version_service = VersionService(
        core_repo, validate_app_spec, local.clock, local.id_factory
    )
    app_service = AppService(
        core_repo, version_service, validate_app_spec, local.id_factory
    )
    calibration_service = CalibrationService(
        core_repo, local.clock, local.id_factory
    )

    # Builder
    build_turn_store = InMemoryBuildTurnStore()

    async def source_loader(source_id: str, workspace: str) -> bytes:
        from vision_app.api.media.router import MediaService
        principal = Principal(local.test_user_id, None, frozenset({workspace}))
        service = MediaService(app.state.v1_dependencies.media)
        asset = await service.get_asset(principal, workspace, source_id)
        if asset.state != "ready" or asset.byte_size > MAX_INLINE_BYTES or asset.duration_ms.root > MAX_VIDEO_DURATION_MS:
            raise RuntimeError("Source video is not eligible for live analysis.")
        grant = await store.issue_read_grant(principal.user_id, asset.storage_ref.root)
        return await store.read(grant.grant_id)

    compiler: Any
    if local.analysis_mode == "gemini":
        from vision_app.providers.gemini.config import GeminiConfig
        config = GeminiConfig(api_key=local.gemini_api_key, model=local.gemini_model, profile="production", timeout_ms=120_000, sample_fps=5.0)
        if local.gemini_api_key:
            from vision_app.providers.gemini.live import GeminiVideoCompiler
            compiler = GeminiVideoCompiler(config, local.clock, local.id_factory, source_loader=source_loader)
        else:
            compiler = _UnavailableAnalysis()
    else:
        compiler = _ScriptedCompiler(local.id_factory)
    builder_agent = BuilderAgent(
        compiler=compiler,
        inspector=_NoOpSceneInspector(),
        registry=REGISTRY,
        validator=cast(SpecValidator, validate_app_spec),
        preview=_NoOpPreviewService(),
        turns=build_turn_store,
        id_factory=local.id_factory,
    )

    # Media
    decoder = LocalVideoDecoder()

    # Privacy deletion service using the media adapter as its repository.
    privacy_service = DeletionService(
        media_repo, store, _NoOpProviderCleaner(), local.clock.now
    )

    # Budget / operations
    ledger = BudgetLedgerService(
        core_repo, local.id_factory, budget_microusd=local.budget_microusd
    )

    # Runtime engine
    evidence_extractor = EvidenceExtractor(decoder, store)
    event_sink = _PersistenceEventSink(core_repo, snapshot, checkpoint)
    engine: Any
    if local.analysis_mode == "gemini":
        if local.gemini_api_key:
            from vision_app.runtime.semantic_engine import GeminiSemanticEngine
            engine = GeminiSemanticEngine(config, decoder, evidence_extractor, event_sink, local.id_factory)
        else:
            engine = _UnavailableAnalysis()
    else:
        detector_adapter = _FixtureDetector(
            local.fixture_annotation,
            DetectorConfig(
                provider="rfdetr",
                model_name="rfdetr-small-fake",
                checkpoint_path="/dev/null",
                checkpoint_revision="local",
                score_threshold=0.0,
            ),
        )
        signal_observer = (
            _AnnotationSignalObserver(local.fixture_annotation)
            if local.fixture_annotation is not None
            else None
        )
        trace_sink = SafeTraceSink(InMemoryTraceSink())
        tracker_factory = ByteTrackFactory()
        engine = RunEngine(
            decoder=decoder,  # type: ignore[arg-type]
            detector=detector_adapter,
            tracker_factory=tracker_factory,
            signal_observer=signal_observer,
            reasoner=None,
            evidence_extractor=evidence_extractor,
            ledger=ledger,
            event_sink=event_sink,
            trace_sink=trace_sink,
            id_factory=local.id_factory,
        )

    # Jobs and runs
    run_repo = _LocalRunRepository(core_repo, local.id_factory, local.analysis_mode)

    jobs_service: JobDispatchService

    def worker_factory(run_id: str) -> Worker:
        return _create_worker(
            local,
            core_repo,
            media_repo,
            store,
            jobs_service,
            engine,
            decoder,
            snapshot,
            checkpoint,
        )(run_id)

    executor = _LocalJobExecutor(worker_factory)
    jobs_service = JobDispatchService(
        jobs_repo, executor, event_sink, local.clock, local.id_factory
    )

    # Actions
    action_service = _LocalActionApiService()

    # Request id generator
    def request_id() -> str:
        return local.id_factory.new("request")

    # Routers
    app.include_router(
        create_builder_router(
            BuilderDependencies(
                identity_verifier=identity,
                authorization=boundary,
                app_service=app_service,
                version_service=version_service,
                calibration_service=calibration_service,
                builder_agent=builder_agent,
                build_turn_store=build_turn_store,
                request_id=request_id,
            )
        )
    )
    app.include_router(
        create_media_router(
            MediaDependencies(
                identity=identity,
                authorization=boundary,
                store=store,
                decoder=decoder,
                repository=media_repo,
                privacy=privacy_service,
                clock=local.clock,
                request_id=request_id,
            )
        )
    )
    async def validate_run(principal: Principal, body: RunCreate) -> None:
        if local.analysis_mode == "gemini":
            if not local.gemini_api_key:
                raise PublicSecurityError(409, "provider_not_configured", "Gemini analysis is not configured.")
            if not body.confirm_external_processing:
                raise PublicSecurityError(409, "external_processing_confirmation_required", "Confirm external processing before sending video to Gemini.")
        version = await version_service.read(principal, body.version_id)
        application = await app_service.read(principal, version.app_id.root)
        if application.published_version_id != version.id:
            raise PublicSecurityError(409, "action_not_eligible", "App version is not published.")
        asset = await media_repo.get_asset(body.asset_id, version.workspace_id.root)
        if asset is None or asset.state != "ready":
            raise PublicSecurityError(409, "asset_not_ready", "Source video is not ready.")
        if local.analysis_mode == "gemini" and (asset.byte_size > MAX_INLINE_BYTES or asset.duration_ms.root > MAX_VIDEO_DURATION_MS):
            raise PublicSecurityError(409, "source_limit_exceeded", "Video exceeds the live analysis limits.")
        if body.calibration_id is not None:
            calibration = await calibration_service.read(principal, body.calibration_id)
            if calibration.source_id != asset.id or calibration.confirmed_at is None:
                raise PublicSecurityError(409, "calibration_source_mismatch", "A confirmed calibration for this source is required.")
        elif version.spec.kind == "tracked_rules":
            raise PublicSecurityError(409, "action_not_eligible", "Calibration is required before running.")

    app.include_router(
        create_runs_router(
            RunDependencies(
                identity=identity,
                authorization=boundary,
                runs=run_repo,
                jobs=jobs_service,
                validate_run=validate_run,
            )
        )
    )
    app.include_router(
        create_actions_router(
            ActionApiDependencies(
                identity=identity,
                authorization=boundary,
                repository=_ActionEventRepository(core_repo),
                actions=action_service,
                privacy=_LocalPrivacyService(media_repo, store),
            )
        )
    )
    v1_dependencies = V1Dependencies(
                identity=identity,
                authorization=boundary,
                app_service=app_service,
                version_service=version_service,
                calibration_service=calibration_service,
                builder_agent=builder_agent,
                build_turn_store=build_turn_store,
                media=MediaDependencies(
                    identity=identity,
                    authorization=boundary,
                    store=store,
                    decoder=decoder,
                    repository=media_repo,
                    privacy=privacy_service,
                    clock=local.clock,
                    request_id=request_id,
                ),
                runs=run_repo,
                jobs=jobs_service,
                core_repo=core_repo,
                clock=local.clock,
                id_factory=local.id_factory,
                request_id=request_id,
                analysis_mode=local.analysis_mode,
                model=local.gemini_model if local.analysis_mode == "gemini" else "scripted-local",
                configured=local.analysis_mode == "scripted" or bool(local.gemini_api_key),
                job_repository=jobs_repo,
            )
    snapshot.restore(core_repo, media_repo, v1_dependencies, jobs_repo, local.id_factory)
    app.state.snapshot = snapshot
    app.state.checkpoint = checkpoint
    app.state.v1_dependencies = v1_dependencies
    app.state.executor = executor
    app.state.job_repository = jobs_service._repository

    @app.middleware("http")
    async def persist_mutations(request: Request, call_next: Callable[[Request], Any]) -> Any:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        path = request.url.path
        inference = path.endswith(("/turns", "/clarifications"))
        try:
            if inference:
                response = await call_next(request)
                await checkpoint()
                return response
            await request.body()
            async with snapshot.transaction():
                try:
                    return await call_next(request)
                finally:
                    await checkpoint()
        except SnapshotError:
            return JSONResponse(status_code=503, content={
                "code": "persistence_unavailable", "message": "Local state could not be saved. Try again.",
                "field_errors": {}, "request_id": request_id(), "retryable": True,
            })

    @app.middleware("http")
    async def require_live_compile_consent(request: Request, call_next: Callable[[Request], Any]) -> Any:
        if local.analysis_mode == "gemini" and request.method == "POST" and request.url.path.startswith("/workspaces/") and "/builds/" in request.url.path and request.url.path.endswith("/turns"):
            return JSONResponse(status_code=409, content={
                "code": "external_processing_confirmation_required",
                "message": "Use the V1 app builder with explicit external processing confirmation.",
                "field_errors": {}, "request_id": request_id(), "retryable": False,
            })
        return await call_next(request)

    app.include_router(create_v1_router(v1_dependencies))
    app.include_router(
        create_v1_media_router(
            MediaDependencies(
                identity=identity,
                authorization=boundary,
                store=store,
                decoder=decoder,
                repository=media_repo,
                privacy=privacy_service,
                clock=local.clock,
                request_id=request_id,
            ),
            identity,
            boundary,
            core_repo,
        )
    )

    # Exception handlers
    add_builder_exception_handlers(app)
    add_media_exception_handlers(app)

    # Additional local-only routes
    _register_local_routes(app, store, action_service, core_repo)

    # Health, CORS, and security middleware
    _register_health_and_middleware(app)

    # Serve the built frontend for manual E2E testing.
    # bootstrap.py is at backend/src/vision_app/bootstrap.py, so parents[3] is the repo root.
    dist = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"

    @app.get("/{full_path:path}", response_model=None)
    async def serve_frontend(full_path: str) -> FileResponse | JSONResponse:
        if not dist.is_dir():
            return JSONResponse(status_code=404, content={"code": "not_found"})
        file_path = dist / full_path
        if not file_path.is_file():
            file_path = dist / "index.html"
        return FileResponse(str(file_path))


def _register_local_routes(
    app: FastAPI,
    store: FileSystemMediaStore,
    action_service: _LocalActionApiService,
    core_repo: InMemoryRepository,
) -> None:
    """Register routes that only exist for the local file-system profile."""

    @app.post("/workspaces/{workspace}/uploads/{upload_id}/bytes")
    async def upload_bytes(
        workspace: str,
        upload_id: str,
        request: Request,
    ) -> Response:
        del workspace
        data = await request.body()
        await store.receive_upload(upload_id, data)
        return Response(status_code=204)

    @app.post(
        "/workspaces/{workspace}/runs/{run_id}/events/{event_id}/actions/preview"
    )
    async def action_preview(
        workspace: str,
        run_id: str,
        event_id: str,
    ) -> JSONResponse:
        del run_id
        repo = _ActionEventRepository(core_repo)
        event = await repo.get_event(event_id)
        if event is None or event.workspace_id != workspace:
            return JSONResponse(
                status_code=404, content={"code": "resource_not_found"}
            )
        enabled = await action_service.get_enabled(
            workspace, "action.webhook_dispatch"
        )
        if enabled is None:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "action_not_eligible",
                    "message": "action not enabled",
                },
            )
        preview = action_service.preview(event, enabled)
        return JSONResponse(content=preview)


def _register_health_and_middleware(app: FastAPI) -> None:
    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(content={"status": "ok", "profile": "local"})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Any]
    ) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
