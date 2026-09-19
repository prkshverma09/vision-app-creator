"""V1 public API routes consumed by the web frontend.

These endpoints are thin wrappers around the domain services. They derive the
workspace from the authenticated principal so the UI can use plain `/v1` paths.
This module is intentionally a compatibility shim and uses ``Any`` return types
to avoid leaking FastAPI/Pydantic details into the frontend contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from vision_app.providers.gemini.live import MAX_INLINE_BYTES, MAX_VIDEO_DURATION_MS
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from vision_app.api.media.router import MediaDependencies, MediaService
from vision_app.api.runs.router import RunCreate
from vision_app.applications.services import (
    AppConflict,
    AppNotFound,
    AppService,
    CalibrationService,
    InvalidProposal,
    PublicationBlocked,
    VersionService,
)
from vision_app.builder.agent import BuilderRequest
from vision_app.builder.ports import BuildTurnStore
from vision_app.contracts.models import (
    AppSpec,
    BoxN,
    BuildTurn,
    ErrorEnvelope,
    Event,
    FrameRef,
    PointN,
    ResourceId,
    RunProgress,
    SourceAsset,
    SourceTimeMs,
    VisionApp,
)
from vision_app.contracts.ports import Clock, IdFactory
from vision_app.jobs.service import JobDispatchService, JobNotFound, JobState
from vision_app.persistence.memory import InMemoryRepository
from vision_app.security.authorization.boundary import AuthorizationBoundary
from vision_app.security.identity.errors import IdentityError, PublicSecurityError
from vision_app.security.identity.models import Principal


class IdentityVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


class BuilderAgentPort(Protocol):
    async def build(self, request: BuilderRequest) -> BuildTurn: ...


class RunRepository(Protocol):
    async def create(self, workspace_id: str, request: Any, idempotency_key: str) -> Any: ...
    async def get(self, run_id: str) -> Any | None: ...
    async def events(self, run_id: str, attempt_id: str) -> list[Event]: ...
    async def progress(self, run_id: str, attempt_id: str) -> list[RunProgress]: ...


@dataclass(frozen=True)
class V1Dependencies:
    identity: IdentityVerifier
    authorization: AuthorizationBoundary
    app_service: AppService
    version_service: VersionService
    calibration_service: CalibrationService
    builder_agent: BuilderAgentPort
    build_turn_store: BuildTurnStore
    media: MediaDependencies
    runs: RunRepository
    jobs: JobDispatchService
    core_repo: InMemoryRepository
    clock: Clock
    id_factory: IdFactory
    request_id: Callable[[], str]
    app_sources: dict[str, str] = field(default_factory=dict)
    app_calibrations: dict[str, str] = field(default_factory=dict)
    upload_resources: dict[str, str] = field(default_factory=dict)
    app_seed_assets: dict[str, str] = field(default_factory=dict)
    analysis_mode: str = "scripted"
    model: str = "scripted-local"
    configured: bool = True
    max_duration_ms: int = MAX_VIDEO_DURATION_MS
    max_bytes: int = MAX_INLINE_BYTES
    job_repository: Any = None


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class _CreateAppRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "Untitled app"


class _TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    confirm_external_processing: bool = False


class _LiveBuilderRequest(BuilderRequest):
    timeout_seconds: float = Field(default=150.0, gt=0, le=150.0)


class _StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = Field(default=None, min_length=1)
    calibration_id: str | None = Field(default=None, min_length=1)
    version_id: str | None = Field(default=None, min_length=1)
    confirm_external_processing: bool = False


class _ClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[str]
    confirm_external_processing: bool = False


class _AcceptVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: AppSpec


class _InitiateUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = ""
    content_type: str
    size_bytes: int = Field(gt=0)


class _AttachSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str


class _CalibrationGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    label: str | None = None
    point: dict[str, Any] | None = None
    box: dict[str, Any] | None = None
    points: list[dict[str, Any]] | None = None


class _CreateCalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometries: list[_CalibrationGeometry]


class _ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    human_review: str
    note: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workspace(principal: Principal) -> str:
    return next(iter(principal.workspace_ids))


def _error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    field_errors: dict[str, str] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        code=code,
        message=message,
        field_errors=field_errors or {},
        request_id=request_id,
        retryable=retryable,
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _app_summary(app: VisionApp, spec: AppSpec | None = None) -> dict[str, Any]:
    return {
        "id": app.id.root,
        "name": spec.title if spec is not None else app.title,
    }


def _source_body(asset: SourceAsset) -> dict[str, Any]:
    return {
        "asset_id": asset.id.root,
        "status": asset.state,
        "duration_ms": asset.duration_ms.root,
        "width": asset.width,
        "height": asset.height,
        "byte_size": asset.byte_size,
        "codec": asset.codec,
        "playback_url": f"/api/v1/media/{asset.storage_ref.root}",
    }


def _build_turn_response(turn: BuildTurn) -> dict[str, Any]:
    outcome: dict[str, Any]
    if turn.status == "needs_input":
        outcome = {
            "kind": "needs_input",
            "questions": [turn.clarification] if turn.clarification else ["Please provide more information."],
        }
        reply = "I need a little more information before I can build this app."
    elif turn.status == "unsupported":
        from vision_app.providers.gemini.live import VideoProviderError
        code = next((item.removeprefix("unsupported:") for item in turn.tool_progress if item.startswith("unsupported:")), "unsupported_request")
        safe_codes = {"configuration", "video_limit", "source_unavailable", "provider_http", "provider_model_unavailable", "provider_auth", "provider_quota", "provider_invalid_request", "provider_payload_too_large", "provider_unavailable", "provider_timeout", "invalid_response"}
        reason = VideoProviderError(code).message if code in safe_codes else "The request is not supported by the current capability set."
        outcome = {"kind": "unsupported_request", "code": code if code in safe_codes else "unsupported_request", "reason": reason}
        reply = reason
    elif turn.status == "failed":
        outcome = {"kind": "unsupported_request", "code": "build_failed", "reason": "The builder could not produce a valid app spec."}
        reply = "I was not able to build a valid app from that request."
    elif turn.status == "proposed" and turn.proposed_version_spec is not None:
        # The V1 UI contract expects outcome.version to be the AppSpec itself.
        outcome = {"kind": "proposed_version", "version": turn.proposed_version_spec.model_dump(mode="json")}
        reply = "I created a proposed app definition. Review it and accept when ready."
    else:
        outcome = {"kind": "unsupported_request", "code": "unexpected", "reason": "Unexpected builder result."}
        reply = "The builder returned an unexpected result."
    return {"reply": reply, "outcome": outcome}


def _geometry_to_calibration_parts(
    geometries: list[_CalibrationGeometry], asset: SourceAsset
) -> tuple[dict[str, list[PointN]], dict[str, list[PointN]], dict[str, BoxN], dict[str, str]]:
    lanes: dict[str, list[PointN]] = {}
    lines: dict[str, list[PointN]] = {}
    rois: dict[str, BoxN] = {}
    governing_signals: dict[str, str] = {}
    for g in geometries:
        label = g.label or g.id
        if g.kind == "line":
            pts = [PointN(x=p["x"], y=p["y"]) for p in (g.points or [])]
            if len(pts) >= 2:
                lines[label] = pts[:2]
                governing_signals[label] = "signal-1"
        elif g.kind == "box":
            box = g.box or {}
            rois[label] = BoxN(
                x1=box.get("x1", 0.0),
                y1=box.get("y1", 0.0),
                x2=box.get("x2", 1.0),
                y2=box.get("y2", 1.0),
            )
            governing_signals[label] = label
        elif g.kind == "polygon":
            lanes[label] = [PointN(x=p["x"], y=p["y"]) for p in (g.points or [])]
    if not lines:
        lines["stop_line"] = [PointN(x=0.5, y=0.0), PointN(x=0.5, y=1.0)]
    if not rois:
        rois["signal-1"] = BoxN(x1=0.85, y1=0.05, x2=0.95, y2=0.18)
    if not governing_signals:
        governing_signals["stop_line"] = "signal-1"
    return lanes, lines, rois, governing_signals


def _run_status(job: Any) -> str:
    state = getattr(job, "state", None)
    mapping = {
        JobState.QUEUED: "queued",
        JobState.DISPATCHING: "running",
        JobState.DISPATCHED: "running",
        JobState.RUNNING: "running",
        JobState.COMPLETED: "succeeded",
        JobState.PARTIAL: "succeeded",
        JobState.FAILED: "failed",
        JobState.CANCELLED: "cancelled",
    }
    return mapping.get(state, "running")  # type: ignore[arg-type]


def _handle(error: Exception, request_id: str) -> JSONResponse:
    if isinstance(error, PublicSecurityError):
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            request_id,
        )
    if isinstance(error, (AppConflict, InvalidProposal, PublicationBlocked)):
        return _error_response(409, "conflict", str(error), request_id)
    if isinstance(error, AppNotFound):
        return _error_response(404, "resource_not_found", str(error), request_id)
    return _error_response(500, "internal_error", "The operation could not be completed.", request_id)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_v1_router(deps: V1Dependencies) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["v1"])
    media_service = MediaService(deps.media)

    def _require_external_processing(confirmed: bool) -> None:
        if deps.analysis_mode != "gemini":
            return
        if not deps.configured:
            raise PublicSecurityError(409, "provider_not_configured", "Gemini analysis is not configured.")
        if not confirmed:
            raise PublicSecurityError(409, "external_processing_confirmation_required", "Confirm external processing before sending video to Gemini.")

    async def _ready_asset(principal: Principal, asset_id: str) -> SourceAsset:
        asset = await media_service.get_asset(principal, _workspace(principal), asset_id)
        if asset.state != "ready":
            raise PublicSecurityError(409, "asset_not_ready", "Source video is not ready.")
        if deps.analysis_mode == "gemini" and (asset.duration_ms.root > deps.max_duration_ms or asset.byte_size > deps.max_bytes):
            raise PublicSecurityError(409, "source_limit_exceeded", "Video exceeds the live analysis limits.")
        return asset

    @router.get("/runtime")
    async def runtime() -> Any:
        return {
            "analysis_mode": deps.analysis_mode,
            "provider": "gemini" if deps.analysis_mode == "gemini" else "scripted",
            "model": deps.model,
            "configured": deps.configured,
            "external_processing": deps.analysis_mode == "gemini",
            "limits": {"max_duration_ms": deps.max_duration_ms, "max_bytes": deps.max_bytes},
        }

    async def _require_principal(authorization: str | None = Header(None)) -> Principal:
        # Hackathon/local mode: authentication is disabled. Any or no token maps to the local workspace.
        token = authorization[len("Bearer "):] if authorization and authorization.startswith("Bearer ") else ""
        try:
            return await deps.identity.verify(token)
        except IdentityError:
            return Principal("local-user", None, frozenset({"workspace-local"}))
        except Exception as exc:
            raise IdentityError(str(exc)) from exc

    async def _app_spec(app: VisionApp, principal: Principal) -> AppSpec | None:
        version_id = app.published_version_id or app.draft_version_id
        if version_id is None:
            return None
        try:
            version = await deps.version_service.read(principal, version_id.root)
        except AppNotFound:
            return None
        return version.spec

    async def _app_detail(app_id: str, principal: Principal) -> dict[str, Any]:
        workspace = _workspace(principal)
        app = await deps.app_service.read(workspace, app_id)
        source = None
        asset_id = deps.app_sources.get(app_id)
        if asset_id is not None:
            try:
                asset = await media_service.get_asset(principal, workspace, asset_id)
                source = _source_body(asset)
            except Exception:
                source = None
        spec = await _app_spec(app, principal)
        return {
            **_app_summary(app, spec),
            "spec": spec.model_dump(mode="json") if spec else None,
            "source": source,
            "calibration_id": deps.app_calibrations.get(app_id),
            "analysis_mode": deps.analysis_mode,
            "published_version_id": app.published_version_id.root if app.published_version_id else None,
            "draft_version_id": app.draft_version_id.root if app.draft_version_id else None,
            "requires_calibration": spec is not None and spec.kind == "tracked_rules",
            "seed_asset_id": deps.app_seed_assets.get(app_id),
        }

    # --- apps ---

    @router.get("/apps")
    async def list_apps(principal: Principal = Depends(_require_principal)) -> Any:
        workspace = _workspace(principal)
        apps = await deps.app_service.list(workspace)
        return {"apps": [_app_summary(a, await _app_spec(a, principal)) for a in apps]}

    @router.post("/apps", status_code=201)
    async def create_app(
        body: _CreateAppRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        app = await deps.app_service.create(workspace, body.name)
        return _app_summary(app)

    @router.get("/apps/{app_id}")
    async def get_app(
        app_id: str, principal: Principal = Depends(_require_principal)
    ) -> Any:
        await deps.authorization.app(principal, app_id)
        return await _app_detail(app_id, principal)

    # --- builder turns ---

    @router.post("/apps/{app_id}/turns")
    async def submit_turn(
        app_id: str, body: _TurnRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        await deps.authorization.app(principal, app_id)
        app = await deps.app_service.read(workspace, app_id)
        request_type = _LiveBuilderRequest if deps.analysis_mode == "gemini" else BuilderRequest
        request = request_type(
            app_id=app_id,
            workspace_id=workspace,
            instruction=body.message,
            base_revision=app.revision,
            base_version_id=app.draft_version_id.root if app.draft_version_id else None,
            source_id=deps.app_seed_assets.get(app_id) or deps.app_sources.get(app_id),
            preview=False,
            timeout_seconds=150.0 if deps.analysis_mode == "gemini" else 30.0,
        )
        try:
            _require_external_processing(body.confirm_external_processing)
            if deps.analysis_mode == "gemini":
                if request.source_id is None:
                    raise PublicSecurityError(409, "source_required", "Attach a seed video before compiling.")
                await _ready_asset(principal, request.source_id)
            turn = await deps.builder_agent.build(request)
        except Exception as exc:
            return _handle(exc, deps.request_id())
        return _build_turn_response(turn)

    @router.post("/apps/{app_id}/clarifications")
    async def submit_clarification(
        app_id: str, body: _ClarifyRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        await deps.authorization.app(principal, app_id)
        app = await deps.app_service.read(workspace, app_id)
        combined = "Clarification answers: " + "; ".join(body.answers)
        request_type = _LiveBuilderRequest if deps.analysis_mode == "gemini" else BuilderRequest
        request = request_type(
            app_id=app_id,
            workspace_id=workspace,
            instruction=combined,
            base_revision=app.revision,
            base_version_id=app.draft_version_id.root if app.draft_version_id else None,
            source_id=deps.app_seed_assets.get(app_id) or deps.app_sources.get(app_id),
            preview=False,
            timeout_seconds=150.0 if deps.analysis_mode == "gemini" else 30.0,
        )
        try:
            _require_external_processing(body.confirm_external_processing)
            if deps.analysis_mode == "gemini":
                if request.source_id is None:
                    raise PublicSecurityError(409, "source_required", "Attach a seed video before compiling.")
                await _ready_asset(principal, request.source_id)
            turn = await deps.builder_agent.build(request)
        except Exception as exc:
            return _handle(exc, deps.request_id())
        return _build_turn_response(turn)

    @router.post("/apps/{app_id}/versions")
    async def accept_version(
        app_id: str, body: _AcceptVersionRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        await deps.authorization.app(principal, app_id)
        app = await deps.app_service.read(workspace, app_id)
        try:
            version = await deps.app_service.revise(
                workspace,
                app_id,
                app.revision,
                app.draft_version_id.root if app.draft_version_id else None,
                body.spec,
            )
            if body.spec.kind == "semantic_windows":
                updated = await deps.app_service.read(workspace, app_id)
                await deps.app_service.publish(workspace, app_id, updated.revision, version.id.root)
        except Exception as exc:
            return _handle(exc, deps.request_id())
        return await _app_detail(app_id, principal)

    # --- source / upload ---

    @router.post("/uploads")
    async def initiate_upload(
        body: _InitiateUploadRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        # The V1 contract does not require a client-side hash; finalize from uploaded bytes.
        grant = await media_service.initiate_upload(
            principal,
            workspace,
            body.content_type,
            body.size_bytes,
            None,
        )
        deps.upload_resources[grant.grant_id] = grant.resource_id.root
        return {
            "upload_id": grant.grant_id,
            "upload_url": f"/v1/uploads/{grant.grant_id}/bytes",
        }

    @router.post("/uploads/{upload_id}/complete")
    async def complete_upload(
        upload_id: str, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        resource_id = deps.upload_resources.get(upload_id)
        if resource_id is None:
            return _error_response(404, "resource_not_found", "Upload grant not found.", deps.request_id())
        object_path = deps.media.store._object_path(resource_id)  # type: ignore[attr-defined]
        data = object_path.read_bytes()
        import hashlib
        actual_size = len(data)
        actual_sha256 = hashlib.sha256(data).hexdigest()
        asset = await media_service.finalize_upload(
            principal, workspace, upload_id, actual_size, actual_sha256
        )
        if deps.analysis_mode == "gemini" and (asset.duration_ms.root > deps.max_duration_ms or asset.byte_size > deps.max_bytes):
            await deps.media.repository.save_asset(asset.model_copy(update={"state": "invalid"}))
            return _error_response(422, "source_limit_exceeded", "Video exceeds the live analysis limits.", deps.request_id())
        await deps.media.repository.save_asset(asset)
        return _source_body(asset)

    @router.put("/uploads/{upload_id}/bytes")
    async def upload_bytes(
        upload_id: str,
        request: Request,
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        data = await request.body()
        # Local file-system store exposes receive_upload outside the MediaStore protocol.
        await deps.media.store.receive_upload(upload_id, data)  # type: ignore[attr-defined]
        return Response(status_code=204)

    @router.get("/assets/{asset_id}")
    async def get_asset(
        asset_id: str, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        asset = await media_service.get_asset(principal, workspace, asset_id)
        return _source_body(asset)

    @router.get("/api/v1/media/{asset_id}")
    async def read_media(
        asset_id: str, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        return await media_service.read_media(principal, workspace, asset_id)

    @router.post("/apps/{app_id}/source")
    async def attach_source(
        app_id: str, body: _AttachSourceRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        await deps.authorization.app(principal, app_id)
        await _ready_asset(principal, body.asset_id)
        deps.app_seed_assets.setdefault(app_id, body.asset_id)
        if deps.app_sources.get(app_id) != body.asset_id:
            deps.app_calibrations.pop(app_id, None)
        deps.app_sources[app_id] = body.asset_id
        return await _app_detail(app_id, principal)

    # --- calibration ---

    @router.post("/apps/{app_id}/calibrations")
    async def create_calibration(
        app_id: str, body: _CreateCalibrationRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        workspace = _workspace(principal)
        await deps.authorization.app(principal, app_id)
        asset_id = deps.app_sources.get(app_id)
        if not asset_id:
            return _error_response(422, "invalid_request", "Attach a source video before calibrating.", deps.request_id())
        asset = await media_service.get_asset(principal, workspace, asset_id)
        lanes, lines, rois, governing_signals = _geometry_to_calibration_parts(body.geometries, asset)
        reference = FrameRef(
            source_id=ResourceId(asset_id),
            source_hash=asset.sha256,
            pts=0,
            time_base_num=1,
            time_base_den=1000,
            source_time_ms=SourceTimeMs(0),
            sequence=0,
            width=asset.width,
            height=asset.height,
            transform_id=ResourceId("tfm-1"),
        )
        try:
            calibration = await deps.calibration_service.create(
                workspace,
                asset_id,
                "fixed-camera",
                reference,
                lanes,
                lines,
                rois,
                governing_signals,
                "fingerprint-1",
            )
            confirmed = await deps.calibration_service.confirm(
                workspace, calibration.id.root, calibration.revision, principal.user_id
            )
            app = await deps.app_service.read(workspace, app_id)
            if app.draft_version_id is not None:
                await deps.app_service.publish(
                    workspace,
                    app_id,
                    app.revision,
                    app.draft_version_id.root,
                    calibration=confirmed,
                    approved_action_refs=frozenset(),
                )
        except Exception as exc:
            return _handle(exc, deps.request_id())
        deps.app_calibrations[app_id] = confirmed.id.root
        return {"calibration_id": confirmed.id.root}

    # --- runs ---

    @router.post("/apps/{app_id}/runs", status_code=202)
    async def start_run(
        app_id: str,
        body: _StartRunRequest = Body(default_factory=_StartRunRequest),
        principal: Principal = Depends(_require_principal),
    ) -> Any:
        workspace = _workspace(principal)
        await deps.authorization.app(principal, app_id)
        try:
            _require_external_processing(body.confirm_external_processing)
            app = await deps.app_service.read(workspace, app_id)
            version_id = body.version_id or (app.published_version_id.root if app.published_version_id else None)
            if version_id is None or app.published_version_id is None or version_id != app.published_version_id.root:
                raise PublicSecurityError(409, "action_not_eligible", "App version is not published.")
            version = await deps.version_service.read(principal, version_id)
            if version.app_id.root != app_id:
                raise PublicSecurityError(409, "action_not_eligible", "Version does not belong to this app.")
            asset_id = body.asset_id or deps.app_sources.get(app_id)
            if not asset_id:
                raise PublicSecurityError(409, "action_not_eligible", "No source video attached.")
            await _ready_asset(principal, asset_id)
            calibration_id = body.calibration_id
            if "calibration_id" not in body.model_fields_set and asset_id == deps.app_sources.get(app_id):
                calibration_id = deps.app_calibrations.get(app_id)
            if calibration_id is not None:
                calibration = await deps.calibration_service.read(principal, calibration_id)
                if calibration.source_id.root != asset_id or calibration.confirmed_at is None:
                    raise PublicSecurityError(409, "calibration_source_mismatch", "A confirmed calibration for this source is required.")
            if version.spec.kind == "tracked_rules" and calibration_id is None:
                raise PublicSecurityError(409, "action_not_eligible", "Calibration is required before running.")
            run_req = RunCreate(version_id=version_id, asset_id=asset_id, calibration_id=calibration_id,
                                confirm_external_processing=body.confirm_external_processing)
            record = await deps.runs.create(workspace, run_req, deps.id_factory.new("idem"))
            await deps.jobs.create(record.id)
            await deps.jobs.dispatch(record.id)
        except Exception as exc:
            return _handle(exc, deps.request_id())
        return {"run_id": record.id}

    async def _run_detail(record: Any, principal: Principal) -> tuple[dict[str, Any], list[Event]]:
        job: Any
        try:
            job = await deps.jobs.get(record.id)
        except JobNotFound:
            job = None
        attempt_id = record.selected_attempt_id or (job.attempt_id if job else None)
        events = await deps.runs.events(record.id, attempt_id) if attempt_id else []
        progress = await deps.runs.progress(record.id, attempt_id) if attempt_id else []
        if job is None:
            latest = max(progress, key=lambda item: item.sequence) if progress else None
            terminal = {"completed": JobState.COMPLETED, "partial": JobState.PARTIAL,
                        "cancelled": JobState.CANCELLED, "failed": JobState.FAILED}
            job = SimpleNamespace(state=terminal.get(latest.phase if latest else "failed", JobState.FAILED))
        failure_reason = None
        if job.state == JobState.FAILED:
            failure_reason = "Analysis failed. Check the source and try again."
            if deps.job_repository is not None:
                persisted = await deps.job_repository.get_owned("job_run", record.id, record.workspace_id)
                if persisted and persisted.get("failure_reason") == "interrupted_by_restart":
                    failure_reason = "interrupted_by_restart"
        version = await deps.version_service.read(principal, record.version_id)
        app_id = version.app_id.root
        asset = await media_service.get_asset(principal, record.workspace_id, record.asset_id)
        failed = job.state == JobState.FAILED
        detail = {
            "id": record.id, "app_id": app_id, "status": _run_status(job),
            "version_id": record.version_id, "asset_id": record.asset_id,
            "spec": version.spec.model_dump(mode="json"),
            "analysis_complete": job.state == JobState.COMPLETED,
            "calibration_id": record.calibration_id,
            "is_seed_run": record.asset_id == deps.app_seed_assets.get(app_id),
            "analysis_mode": getattr(record, "analysis_mode", deps.analysis_mode),
            "source": _source_body(asset),
            "playback_url": f"/api/v1/media/{record.asset_id}",
            "coverage_note": "Analysis did not complete." if failed else ("Analysis completed partially." if job.state == JobState.PARTIAL else ""),
            "failure_reason": failure_reason,
            "progress": [item.model_dump(mode="json") for item in progress],
        }
        return detail, events

    @router.get("/apps/{app_id}/runs")
    async def list_app_runs(app_id: str, principal: Principal = Depends(_require_principal)) -> Any:
        await deps.authorization.app(principal, app_id)
        records = await deps.core_repo.list_owned("run", principal)
        runs = []
        for record in records:
            version = await deps.version_service.read(principal, record.version_id)
            if version.app_id.root == app_id:
                detail, _ = await _run_detail(record, principal)
                runs.append(detail)
        return {"runs": runs}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, principal: Principal = Depends(_require_principal)) -> Any:
        workspace = _workspace(principal)
        record = await deps.runs.get(run_id)
        if record is None or record.workspace_id != workspace:
            return _error_response(404, "resource_not_found", "Run not found.", deps.request_id())
        await deps.authorization.run(principal, run_id)
        detail, events = await _run_detail(record, principal)
        return {"run": detail, "events": [e.model_dump(mode="json") for e in events], "progress": detail["progress"]}

    @router.get("/runs/{run_id}/progress")
    async def get_run_progress(run_id: str, principal: Principal = Depends(_require_principal)) -> Any:
        await deps.authorization.run(principal, run_id)
        record = await deps.runs.get(run_id)
        if record is None:
            return _error_response(404, "resource_not_found", "Run not found.", deps.request_id())
        detail, _ = await _run_detail(record, principal)
        return {"items": detail["progress"], "status": detail["status"]}

    # --- events ---

    @router.post("/events/{event_id}/review")
    async def review_event(
        event_id: str, body: _ReviewRequest, principal: Principal = Depends(_require_principal)
    ) -> Any:
        await deps.authorization.event(principal, event_id)
        found = None
        run_id_value = None
        for ws_key, collections in deps.core_repo._store.items():
            for doc in collections.get("events", {}).values():
                if doc.value.id.root == event_id:
                    found = doc.value
                    run_id_value = doc.value.run_id.root
                    break
            if found is not None:
                break
        if found is None or run_id_value is None:
            return _error_response(404, "resource_not_found", "Event not found.", deps.request_id())
        reviewed = await deps.core_repo.review_event(
            run_id_value, event_id, found.revision, body.human_review, principal
        )
        if reviewed is None:
            return _error_response(409, "conflict", "Event was modified concurrently.", deps.request_id())
        return reviewed.model_dump(mode="json")

    return router


def create_v1_media_router(media_deps: MediaDependencies, identity: IdentityVerifier, authorization: AuthorizationBoundary, core_repo: InMemoryRepository | None = None) -> APIRouter:
    """Serve media bytes at the path the frontend expects for thumbnails/clips."""
    router = APIRouter(prefix="/api/v1", tags=["v1-media"])
    media_service = MediaService(media_deps)

    async def _require_principal(authorization_header: str | None = Header(None)) -> Principal:
        # Hackathon/local mode: authentication is disabled.
        token = (
            authorization_header[len("Bearer "):]
            if authorization_header and authorization_header.startswith("Bearer ")
            else ""
        )
        try:
            return await identity.verify(token)
        except IdentityError:
            return Principal("local-user", None, frozenset({"workspace-local"}))
        except Exception as exc:
            raise IdentityError(str(exc)) from exc

    @router.get("/media/{asset_id}/preview.webm")
    async def read_preview(asset_id: str, principal: Principal = Depends(_require_principal)) -> Any:
        workspace = next(iter(principal.workspace_ids))
        return await media_service.read_preview(principal, workspace, asset_id)

    @router.get("/media/{asset_id}")
    async def read_media(asset_id: str, principal: Principal = Depends(_require_principal)) -> Any:
        workspace = next(iter(principal.workspace_ids))
        if await media_deps.repository.get_asset(asset_id, workspace) is not None:
            return await media_service.read_media(principal, workspace, asset_id)
        if core_repo is not None:
            for event in await core_repo.list_owned("events", principal):
                if asset_id not in [ref.root for ref in (event.evidence.thumbnail_ref, event.evidence.clip_ref) if ref is not None]:
                    continue
                await authorization.event(principal, event.id.root)
                run = await core_repo.get_owned("run", event.run_id.root, principal)
                if run is None:
                    continue
                source = await media_deps.repository.get_asset(run.asset_id, workspace)
                if source is None or source.state != "ready":
                    continue
                metadata = await media_deps.store.get_metadata(asset_id)
                grant = await media_deps.store.issue_read_grant(metadata.owner_id, asset_id)
                data = await media_deps.store.read(grant.grant_id)
                return Response(content=data, media_type=metadata.content_type)
        raise PublicSecurityError(404, "resource_not_found", "Resource not found.")

    return router
