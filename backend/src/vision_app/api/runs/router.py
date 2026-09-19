"""FastAPI routes for durable run creation, progress, events and cancellation."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from vision_app.contracts.models import Event, RunProgress
from vision_app.contracts.ports import IdentityVerifier
from vision_app.jobs.service import JobDispatchService, JobNotFound, JobSnapshot
from vision_app.security.authorization.boundary import AuthorizationBoundary
from vision_app.security.identity.errors import IdentityError, PublicSecurityError, map_security_error
from vision_app.security.identity.models import Principal


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    calibration_id: str | None = None
    confirm_external_processing: bool = False


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    workspace_id: str
    version_id: str
    asset_id: str
    calibration_id: str | None
    selected_attempt_id: str | None = None
    app_id: str | None = None
    analysis_mode: str = "scripted"


class RunRepository(Protocol):
    async def create(self, workspace_id: str, request: RunCreate, idempotency_key: str) -> RunRecord: ...
    async def get(self, run_id: str) -> RunRecord | None: ...
    async def events(self, run_id: str, attempt_id: str) -> list[Event]: ...
    async def event(self, run_id: str, attempt_id: str, event_id: str) -> Event | None: ...
    async def progress(self, run_id: str, attempt_id: str) -> list[RunProgress]: ...


@dataclass(frozen=True, slots=True)
class RunDependencies:
    identity: IdentityVerifier
    authorization: AuthorizationBoundary
    runs: RunRepository
    jobs: JobDispatchService
    validate_run: Callable[[Principal, RunCreate], Awaitable[None]] | None = None


def create_runs_router(dependencies: RunDependencies) -> APIRouter:
    router = APIRouter(prefix="/workspaces/{workspace}/runs", tags=["runs"])

    @router.post("", status_code=202)
    async def create_run(
        workspace: str,
        body: RunCreate,
        request: Request,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    ) -> Any:
        try:
            principal = await _principal(request, dependencies.identity)
            _require_workspace(principal, workspace)
            resources = [
                await dependencies.authorization.version(principal, body.version_id),
                await dependencies.authorization.asset(principal, body.asset_id),
            ]
            if body.calibration_id is not None:
                resources.append(
                    await dependencies.authorization.calibration(principal, body.calibration_id)
                )
            if any(resource.workspace_id != workspace for resource in resources):
                raise _not_found()
            if dependencies.validate_run is not None:
                await dependencies.validate_run(principal, body)
            record = await dependencies.runs.create(workspace, body, idempotency_key)
            try:
                await dependencies.jobs.create(record.id)
            except Exception as error:
                if not isinstance(error, JobNotFound):
                    # Job creation is a CAS insert. Existing state means idempotent replay.
                    snapshot = await dependencies.jobs.get(record.id)
                    if snapshot.run_id != record.id:
                        raise
            await dependencies.jobs.dispatch(record.id)
            return _run_body(record, await dependencies.jobs.get(record.id))
        except (IdentityError, PublicSecurityError) as error:
            return _security_response(error, request)

    @router.get("/{run}")
    async def get_run(workspace: str, run: str, request: Request) -> Any:
        try:
            _, record = await _authorized_run(dependencies, request, workspace, run)
            return _run_body(record, await dependencies.jobs.get(run))
        except (IdentityError, PublicSecurityError, JobNotFound) as error:
            return _security_response(_as_public(error), request)

    @router.get("/{run}/progress")
    async def get_progress(
        workspace: str,
        run: str,
        request: Request,
        after: int = Query(default=-1, ge=-1),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> Any:
        try:
            _, record = await _authorized_run(dependencies, request, workspace, run)
            updates = [] if record.selected_attempt_id is None else await dependencies.runs.progress(
                run, record.selected_attempt_id
            )
            ordered = sorted((item for item in updates if item.sequence > after), key=lambda item: item.sequence)
            page = ordered[:limit]
            return {
                "items": [item.model_dump(mode="json") for item in page],
                "next_cursor": page[-1].sequence if page else after,
            }
        except (IdentityError, PublicSecurityError) as error:
            return _security_response(error, request)

    @router.get("/{run}/events")
    async def list_events(
        workspace: str,
        run: str,
        request: Request,
        cursor: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> Any:
        try:
            _, record = await _authorized_run(dependencies, request, workspace, run)
            events = [] if record.selected_attempt_id is None else await dependencies.runs.events(
                run, record.selected_attempt_id
            )
            ordered = sorted(events, key=_event_key)
            if cursor is not None:
                cursor_key = _decode_cursor(cursor)
                ordered = [item for item in ordered if _event_key(item) > cursor_key]
            page = ordered[:limit]
            return {
                "items": [item.model_dump(mode="json") for item in page],
                "next_cursor": _encode_cursor(_event_key(page[-1])) if len(ordered) > limit else None,
            }
        except (IdentityError, PublicSecurityError, ValueError) as error:
            if isinstance(error, ValueError):
                return JSONResponse(status_code=422, content=_error("invalid_cursor", "Invalid cursor.", request))
            return _security_response(error, request)

    @router.get("/{run}/events/{event}")
    async def get_event(workspace: str, run: str, event: str, request: Request) -> Any:
        try:
            principal, record = await _authorized_run(dependencies, request, workspace, run)
            await dependencies.authorization.event(principal, event)
            item = None if record.selected_attempt_id is None else await dependencies.runs.event(
                run, record.selected_attempt_id, event
            )
            if item is None:
                raise _not_found()
            return item.model_dump(mode="json")
        except (IdentityError, PublicSecurityError) as error:
            return _security_response(error, request)

    @router.post("/{run}/cancel", status_code=202)
    async def cancel_run(workspace: str, run: str, request: Request) -> Any:
        try:
            _, record = await _authorized_run(dependencies, request, workspace, run)
            await dependencies.jobs.cancel(run)
            return _run_body(record, await dependencies.jobs.get(run))
        except (IdentityError, PublicSecurityError, JobNotFound) as error:
            return _security_response(_as_public(error), request)

    return router


async def _principal(request: Request, verifier: IdentityVerifier) -> Principal:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise IdentityError()
    principal = await verifier.verify(token)
    if not isinstance(principal, Principal):
        raise IdentityError()
    return principal


async def _authorized_run(
    dependencies: RunDependencies, request: Request, workspace: str, run_id: str
) -> tuple[Principal, RunRecord]:
    principal = await _principal(request, dependencies.identity)
    _require_workspace(principal, workspace)
    ownership = await dependencies.authorization.run(principal, run_id)
    if ownership.workspace_id != workspace:
        raise _not_found()
    record = await dependencies.runs.get(run_id)
    if record is None or record.workspace_id != workspace:
        raise _not_found()
    return principal, record


def _require_workspace(principal: Principal, workspace: str) -> None:
    if not principal.is_member(workspace):
        raise _not_found()


def _not_found() -> PublicSecurityError:
    return PublicSecurityError(404, "resource_not_found", "Resource not found.")


def _as_public(error: Exception) -> Exception:
    return _not_found() if isinstance(error, JobNotFound) else error


def _security_response(error: Exception, request: Request) -> JSONResponse:
    status = error.status_code if isinstance(error, PublicSecurityError) else 401
    return JSONResponse(status_code=status, content=map_security_error(error, _request_id(request)))


def _error(code: str, message: str, request: Request) -> dict[str, Any]:
    return {"code": code, "message": message, "field_errors": [], "request_id": _request_id(request), "retryable": False}


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id", "request-unknown")


def _run_body(record: RunRecord, job: JobSnapshot) -> dict[str, Any]:
    return {
        "id": record.id, "workspace_id": record.workspace_id, "version_id": record.version_id,
        "app_id": record.app_id, "analysis_mode": record.analysis_mode,
        "failure_reason": "Analysis failed. Check the source and try again." if job.state.value == "failed" else None,
        "asset_id": record.asset_id, "calibration_id": record.calibration_id,
        "selected_attempt_id": record.selected_attempt_id, "state": job.state.value,
        "cancel_requested": job.cancel_requested, "progress_sequence": job.progress_sequence,
    }


def _event_key(event: Event) -> tuple[int, str]:
    return event.source_range.start_ms.root, event.id.root


def _encode_cursor(key: tuple[int, str]) -> str:
    raw = json.dumps([key[0], key[1]], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], int) or not isinstance(value[1], str):
            raise ValueError
        return value[0], value[1]
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid cursor") from error
