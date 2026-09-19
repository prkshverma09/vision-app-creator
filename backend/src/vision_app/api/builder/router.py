"""FastAPI router factory for builder/app/calibration/chat-turn routes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from fastapi import APIRouter, Depends, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

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


class BuilderAgentPort(Protocol):
    async def build(self, request: BuilderRequest) -> Any: ...
from vision_app.contracts.models import AppSpec, ErrorEnvelope, FrameRef, VisionApp
from vision_app.security.authorization.boundary import AuthorizationBoundary
from vision_app.security.identity.errors import IdentityError, PublicSecurityError
from vision_app.security.identity.models import Principal


class IdentityVerifier(Protocol):
    async def verify(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class BuilderDependencies:
    identity_verifier: IdentityVerifier
    authorization: AuthorizationBoundary
    app_service: AppService
    version_service: VersionService
    calibration_service: CalibrationService
    builder_agent: BuilderAgentPort
    build_turn_store: BuildTurnStore
    request_id: Callable[[], str]


class _CreateAppRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class _VersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    base_version_id: str | None = None
    spec: AppSpec


class _PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    calibration_id: str | None = None
    approved_action_refs: list[str] = []


class _CalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    camera_binding: str
    reference_frame: FrameRef
    lanes: dict[str, list[Any]]
    lines: dict[str, list[Any]]
    rois: dict[str, Any]
    governing_signals: dict[str, str]
    scene_fingerprint: str
    calibration_id: str | None = None
    expected_revision: int | None = None


class _ConfirmCalibrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    confirmed_by: str


class _BuildTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str
    base_revision: int = 0
    base_version_id: str | None = None
    source_id: str | None = None
    preview: bool = False
    timeout_seconds: float = 30.0


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


def create_builder_router(deps: BuilderDependencies) -> APIRouter:
    router = APIRouter(tags=["builder"])

    async def _require_principal(authorization: str | None = Header(None)) -> Principal:
        if authorization is None or not authorization.startswith("Bearer "):
            raise IdentityError("missing_token")
        token = authorization[len("Bearer "):]
        try:
            return await deps.identity_verifier.verify(token)
        except IdentityError:
            raise
        except Exception as exc:  # pragma: no cover - verifier must raise IdentityError
            raise IdentityError(str(exc)) from exc

    async def _current_principal(authorization: str | None = Header(None)) -> Principal:
        return await _require_principal(authorization)

    def _workspace_check(principal: Principal, workspace: str) -> None:
        if not principal.is_member(workspace):
            raise PublicSecurityError(404, "resource_not_found", "Resource not found.")

    @router.post("/workspaces/{workspace}/apps", status_code=201)
    async def create_app(workspace: str, body: _CreateAppRequest, principal: Principal = Depends(_current_principal)) -> VisionApp:
        _workspace_check(principal, workspace)
        return await deps.app_service.create(workspace, body.title)

    @router.get("/workspaces/{workspace}/apps")
    async def list_apps(workspace: str, principal: Principal = Depends(_current_principal)) -> list[VisionApp]:
        _workspace_check(principal, workspace)
        return await deps.app_service.list(workspace)

    @router.get("/workspaces/{workspace}/apps/{app_id}")
    async def get_app(workspace: str, app_id: str, principal: Principal = Depends(_current_principal)) -> VisionApp:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        return await deps.app_service.read(workspace, app_id)

    @router.post("/workspaces/{workspace}/apps/{app_id}/versions", status_code=201)
    async def create_version(
        workspace: str, app_id: str, body: _VersionCreateRequest, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        version = await deps.app_service.revise(
            workspace,
            app_id,
            body.expected_revision,
            body.base_version_id,
            body.spec,
        )
        return version

    @router.get("/workspaces/{workspace}/apps/{app_id}/versions/{version_id}")
    async def get_version(
        workspace: str, app_id: str, version_id: str, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        await deps.authorization.version(principal, version_id)
        return await deps.version_service.read(workspace, version_id)

    @router.post("/workspaces/{workspace}/apps/{app_id}/versions/{version_id}/publish")
    async def publish_version(
        workspace: str,
        app_id: str,
        version_id: str,
        body: _PublishRequest,
        principal: Principal = Depends(_current_principal),
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        await deps.authorization.version(principal, version_id)
        calibration = None
        if body.calibration_id is not None:
            await deps.authorization.calibration(principal, body.calibration_id)
            calibration = await deps.calibration_service.read(workspace, body.calibration_id)
        approved_refs = frozenset(body.approved_action_refs)
        return await deps.app_service.publish(
            workspace,
            app_id,
            body.expected_revision,
            version_id,
            calibration=calibration,
            approved_action_refs=approved_refs,
        )

    @router.post("/workspaces/{workspace}/apps/{app_id}/calibrations", status_code=201)
    async def create_or_update_calibration(
        workspace: str, app_id: str, body: _CalibrationRequest, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        await deps.authorization.asset(principal, body.source_id)
        if body.calibration_id is not None:
            if body.expected_revision is None:
                return _error_response(
                    422, "invalid_request", "expected_revision is required for calibration update", deps.request_id()
                )
            await deps.authorization.calibration(principal, body.calibration_id)
            updated = await deps.calibration_service.bind_source(
                workspace,
                body.calibration_id,
                body.expected_revision,
                body.source_id,
                body.reference_frame,
                body.scene_fingerprint,
            )
            return JSONResponse(status_code=200, content=updated.model_dump(mode="json"))
        return await deps.calibration_service.create(
            workspace,
            body.source_id,
            body.camera_binding,
            body.reference_frame,
            body.lanes,
            body.lines,
            body.rois,
            body.governing_signals,
            body.scene_fingerprint,
        )

    @router.get("/workspaces/{workspace}/apps/{app_id}/calibrations/{calibration_id}")
    async def get_calibration(
        workspace: str, app_id: str, calibration_id: str, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        await deps.authorization.calibration(principal, calibration_id)
        return await deps.calibration_service.read(workspace, calibration_id)

    @router.post("/workspaces/{workspace}/apps/{app_id}/calibrations/{calibration_id}/confirm")
    async def confirm_calibration(
        workspace: str,
        app_id: str,
        calibration_id: str,
        body: _ConfirmCalibrationRequest,
        principal: Principal = Depends(_current_principal),
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, app_id)
        await deps.authorization.calibration(principal, calibration_id)
        return await deps.calibration_service.confirm(
            workspace, calibration_id, body.expected_revision, body.confirmed_by
        )

    @router.post("/workspaces/{workspace}/builds/{build_id}/turns", status_code=202)
    async def submit_turn(
        workspace: str, build_id: str, body: _BuildTurnRequest, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, build_id)
        request = BuilderRequest(
            app_id=build_id,
            workspace_id=workspace,
            instruction=body.instruction,
            base_revision=body.base_revision,
            base_version_id=body.base_version_id,
            source_id=body.source_id,
            principal=principal,
            preview=body.preview,
            timeout_seconds=body.timeout_seconds,
        )
        return await deps.builder_agent.build(request)

    @router.get("/workspaces/{workspace}/builds/{build_id}/turns/{turn_id}")
    async def get_turn(
        workspace: str, build_id: str, turn_id: str, principal: Principal = Depends(_current_principal)
    ) -> Any:
        _workspace_check(principal, workspace)
        await deps.authorization.app(principal, build_id)
        await deps.authorization.build_turn(principal, turn_id)
        turn = await deps.build_turn_store.get(turn_id)
        if turn is None:
            raise AppNotFound(turn_id)
        return turn

    return router


def add_builder_exception_handlers(app: Any) -> None:
    async def _identity_handler(_request: Request, exc: IdentityError) -> JSONResponse:
        return _error_response(401, "invalid_identity", "Authentication is required.", "identity")

    async def _security_handler(_request: Request, exc: PublicSecurityError) -> JSONResponse:
        return _error_response(
            exc.status_code, exc.code, exc.message, "security", retryable=exc.status_code == 429
        )

    async def _conflict_handler(_request: Request, exc: AppConflict) -> JSONResponse:
        return _error_response(409, "conflict", str(exc), "conflict")

    async def _not_found_handler(_request: Request, exc: AppNotFound) -> JSONResponse:
        return _error_response(404, "resource_not_found", str(exc), "not-found")

    async def _invalid_proposal_handler(_request: Request, exc: InvalidProposal) -> JSONResponse:
        field_errors = {
            issue.field or issue.code: issue.message
            for issue in exc.outcome.issues
            if issue.severity == "error"
        }
        return _error_response(422, "invalid_spec", "Proposed specification is invalid.", "invalid-spec", field_errors=field_errors)

    async def _publication_blocked_handler(_request: Request, exc: PublicationBlocked) -> JSONResponse:
        return _error_response(
            422, "not_publication_ready", str(exc), "publication", retryable=False
        )

    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors: dict[str, str] = {}
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", []))
            field_errors[loc] = error.get("msg", "invalid value")
        return _error_response(422, "invalid_request", "Request body failed validation.", "validation", field_errors=field_errors)

    async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(422, "invalid_request", str(exc), "value-error")

    app.add_exception_handler(IdentityError, _identity_handler)
    app.add_exception_handler(PublicSecurityError, _security_handler)
    app.add_exception_handler(AppConflict, _conflict_handler)
    app.add_exception_handler(AppNotFound, _not_found_handler)
    app.add_exception_handler(InvalidProposal, _invalid_proposal_handler)
    app.add_exception_handler(PublicationBlocked, _publication_blocked_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(ValueError, _value_error_handler)
