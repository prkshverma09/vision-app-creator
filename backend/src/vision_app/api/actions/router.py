"""Authenticated review, action delivery, destination enablement, and deletion routes."""
from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from vision_app.actions import ActionContext, Permission, eligibility
from vision_app.contracts.ports import IdentityVerifier
from vision_app.security.authorization.boundary import AuthorizationBoundary
from vision_app.security.identity.errors import IdentityError, PublicSecurityError, map_security_error
from vision_app.security.identity.models import Principal


class ApiConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UnsafeDestination(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ActionEvent:
    id: str
    workspace_id: str
    run_id: str
    revision: int
    machine_decision: str
    human_review: str
    selected_finalized: bool
    reviewed_revision: int | None = None
    reviewed_by: str | None = None


@dataclass(frozen=True, slots=True)
class EnabledAction:
    id: str
    app_id: str
    workspace_id: str
    destination_url: str
    permission: Permission


@dataclass(frozen=True, slots=True)
class DeliveryStatus:
    id: str
    workspace_id: str
    run_id: str
    event_id: str
    event_revision: int
    action_id: str
    state: str = "pending"


@dataclass(frozen=True, slots=True)
class DeletionStatus:
    id: str
    workspace_id: str
    resource_kind: str
    resource_id: str
    requested_by: str
    state: str = "pending"
    irreversible: bool = False


class ActionRepository(Protocol):
    async def get_event(self, event_id: str) -> ActionEvent | None: ...
    async def review(self, event_id: str, expected_revision: int, decision: str, user_id: str) -> ActionEvent: ...


class ActionApiService(Protocol):
    async def enable(self, workspace: str, app: str, action: str, destination_url: str, idempotency_key: str) -> EnabledAction: ...
    async def get_enabled(self, workspace: str, action: str) -> EnabledAction | None: ...
    async def create_delivery(self, event: ActionEvent, enabled: EnabledAction, idempotency_key: str) -> DeliveryStatus: ...
    async def get_delivery(self, delivery_id: str) -> DeliveryStatus | None: ...


class PrivacyApiService(Protocol):
    async def request(self, deletion_id: str, workspace: str, kind: str, resource_id: str, expected_generation: int, requested_by: str, idempotency_key: str) -> DeletionStatus: ...
    async def get(self, deletion_id: str) -> DeletionStatus | None: ...


@dataclass(frozen=True, slots=True)
class ActionApiDependencies:
    identity: IdentityVerifier
    authorization: AuthorizationBoundary
    repository: ActionRepository
    actions: ActionApiService
    privacy: PrivacyApiService


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["confirmed_by_user", "dismissed_by_user"]
    expected_revision: int = Field(ge=0)


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class EnableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_url: str = Field(min_length=1)
    confirm_external_delivery: bool


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_kind: Literal["app", "version", "asset", "run", "event", "delivery"]
    resource_id: str = Field(min_length=1)
    expected_generation: int = Field(ge=1)


def create_actions_router(dependencies: ActionApiDependencies) -> APIRouter:
    router = APIRouter(tags=["actions", "privacy"])

    @router.post("/workspaces/{workspace}/runs/{run}/events/{event}/review")
    async def submit_review(workspace: str, run: str, event: str, body: ReviewRequest, request: Request) -> Any:
        try:
            principal, item = await _authorized_event(dependencies, request, workspace, run, event)
            updated = await dependencies.repository.review(event, body.expected_revision, body.decision, principal.user_id)
            return _review_body(updated)
        except (IdentityError, PublicSecurityError, ApiConflict) as error:
            return _response(error, request)

    @router.get("/workspaces/{workspace}/runs/{run}/events/{event}/review")
    async def get_review(workspace: str, run: str, event: str, request: Request) -> Any:
        try:
            _, item = await _authorized_event(dependencies, request, workspace, run, event)
            return _review_body(item)
        except (IdentityError, PublicSecurityError) as error:
            return _response(error, request)

    @router.post("/workspaces/{workspace}/runs/{run}/events/{event}/deliveries", status_code=202)
    async def create_delivery(workspace: str, run: str, event: str, body: DeliveryRequest, request: Request, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)]) -> Any:
        try:
            principal, item = await _authorized_event(dependencies, request, workspace, run, event)
            ownership = await dependencies.authorization.action_destination(principal, body.action_id)
            if ownership.workspace_id != workspace or item.revision != body.expected_revision:
                if item.revision != body.expected_revision:
                    raise ApiConflict("stale_revision", "Event revision has changed.")
                raise _not_found()
            enabled = await dependencies.actions.get_enabled(workspace, body.action_id)
            if enabled is None:
                raise ApiConflict("action_not_eligible", "Action destination is not enabled.")
            return _delivery_body(await dependencies.actions.create_delivery(item, enabled, idempotency_key))
        except (IdentityError, PublicSecurityError, ApiConflict) as error:
            return _response(error, request)

    @router.get("/workspaces/{workspace}/runs/{run}/events/{event}/deliveries/{delivery}")
    async def get_delivery(workspace: str, run: str, event: str, delivery: str, request: Request) -> Any:
        try:
            await _authorized_event(dependencies, request, workspace, run, event)
            item = await dependencies.actions.get_delivery(delivery)
            if item is None or (item.workspace_id, item.run_id, item.event_id) != (workspace, run, event):
                raise _not_found()
            return _delivery_body(item)
        except (IdentityError, PublicSecurityError) as error:
            return _response(error, request)

    @router.post("/workspaces/{workspace}/apps/{app}/actions/{action}/enable")
    async def enable_action(workspace: str, app: str, action: str, body: EnableRequest, request: Request, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)]) -> Any:
        try:
            principal = await _principal(request, dependencies.identity)
            _require_workspace(principal, workspace)
            app_owner = await dependencies.authorization.app(principal, app)
            action_owner = await dependencies.authorization.action_destination(principal, action)
            if app_owner.workspace_id != workspace or action_owner.workspace_id != workspace:
                raise _not_found()
            if not body.confirm_external_delivery:
                raise UnsafeDestination("Explicit external delivery confirmation is required.")
            _validate_destination(body.destination_url)
            return _enabled_body(await dependencies.actions.enable(workspace, app, action, body.destination_url, idempotency_key))
        except (IdentityError, PublicSecurityError, UnsafeDestination) as error:
            return _response(error, request)

    @router.post("/workspaces/{workspace}/deletions/{deletion}", status_code=202)
    async def request_deletion(workspace: str, deletion: str, body: DeletionRequest, request: Request, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)]) -> Any:
        try:
            principal = await _principal(request, dependencies.identity)
            _require_workspace(principal, workspace)
            owner = await dependencies.authorization.deletion_job(principal, deletion)
            if owner.workspace_id != workspace:
                raise _not_found()
            result = await dependencies.privacy.request(deletion, workspace, body.resource_kind, body.resource_id, body.expected_generation, principal.user_id, idempotency_key)
            return _deletion_body(result)
        except (IdentityError, PublicSecurityError, ApiConflict) as error:
            return _response(error, request)

    @router.get("/workspaces/{workspace}/deletions/{deletion}")
    async def get_deletion(workspace: str, deletion: str, request: Request) -> Any:
        try:
            principal = await _principal(request, dependencies.identity)
            _require_workspace(principal, workspace)
            owner = await dependencies.authorization.deletion_job(principal, deletion)
            item = await dependencies.privacy.get(deletion)
            if owner.workspace_id != workspace or item is None or item.workspace_id != workspace:
                raise _not_found()
            return _deletion_body(item)
        except (IdentityError, PublicSecurityError) as error:
            return _response(error, request)

    return router


class InMemoryActionRepository:
    def __init__(self, events: list[ActionEvent] = []) -> None:
        self.events = {item.id: item for item in events}

    async def get_event(self, event_id: str) -> ActionEvent | None:
        return self.events.get(event_id)

    async def review(self, event_id: str, expected_revision: int, decision: str, user_id: str) -> ActionEvent:
        item = self.events[event_id]
        if item.revision != expected_revision:
            raise ApiConflict("stale_revision", "Event revision has changed.")
        updated = replace(item, revision=item.revision + 1, human_review=decision, reviewed_revision=item.revision + 1, reviewed_by=user_id)
        self.events[event_id] = updated
        return updated


class InMemoryActionApiService:
    def __init__(self) -> None:
        self.enabled: dict[tuple[str, str], EnabledAction] = {}
        self.deliveries: dict[str, DeliveryStatus] = {}
        self.external_calls = 0

    async def enable(self, workspace: str, app: str, action: str, destination_url: str, idempotency_key: str) -> EnabledAction:
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

    async def create_delivery(self, event: ActionEvent, enabled: EnabledAction, idempotency_key: str) -> DeliveryStatus:
        context = ActionContext(event.workspace_id, event.id, event.revision, event.machine_decision, event.human_review, event.selected_finalized, "normal", enabled.id, True, False, False, True)
        result = eligibility(context, enabled.permission, reviewed_revision=event.reviewed_revision)
        if not result.eligible:
            raise ApiConflict("action_not_eligible", ",".join(result.reasons))
        digest = hashlib.sha256(f"{event.workspace_id}|{event.id}|{event.revision}|{enabled.id}|{idempotency_key}".encode()).hexdigest()[:24]
        delivery_id = f"delivery-{digest}"
        return self.deliveries.setdefault(delivery_id, DeliveryStatus(delivery_id, event.workspace_id, event.run_id, event.id, event.revision, enabled.id))

    async def get_delivery(self, delivery_id: str) -> DeliveryStatus | None:
        return self.deliveries.get(delivery_id)


class InMemoryPrivacyApiService:
    def __init__(self, generations: dict[tuple[str, str], int] | None = None, *, fixed_id: str | None = None) -> None:
        self.generations = dict(generations or {})
        self.jobs: dict[str, DeletionStatus] = {}
        self.fixed_id = fixed_id

    async def request(self, deletion_id: str, workspace: str, kind: str, resource_id: str, expected_generation: int, requested_by: str, idempotency_key: str) -> DeletionStatus:
        del idempotency_key
        if self.fixed_id is not None and deletion_id != self.fixed_id:
            raise ApiConflict("deletion_id_mismatch", "Deletion identifier does not match.")
        current = self.generations.get((kind, resource_id))
        if current != expected_generation:
            raise ApiConflict("generation_mismatch", "Resource generation has changed.")
        value = self.jobs.get(deletion_id)
        if value is None:
            value = DeletionStatus(deletion_id, workspace, kind, resource_id, requested_by)
            self.jobs[deletion_id] = value
            self.generations[(kind, resource_id)] = current + 1
        return value

    async def get(self, deletion_id: str) -> DeletionStatus | None:
        return self.jobs.get(deletion_id)


async def _authorized_event(dependencies: ActionApiDependencies, request: Request, workspace: str, run: str, event: str) -> tuple[Principal, ActionEvent]:
    principal = await _principal(request, dependencies.identity)
    _require_workspace(principal, workspace)
    run_owner = await dependencies.authorization.run(principal, run)
    event_owner = await dependencies.authorization.event(principal, event)
    item = await dependencies.repository.get_event(event)
    if run_owner.workspace_id != workspace or event_owner.workspace_id != workspace or item is None or (item.workspace_id, item.run_id) != (workspace, run):
        raise _not_found()
    return principal, item


async def _principal(request: Request, verifier: IdentityVerifier) -> Principal:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise IdentityError()
    principal = await verifier.verify(token)
    if not isinstance(principal, Principal):
        raise IdentityError()
    return principal


def _require_workspace(principal: Principal, workspace: str) -> None:
    if not principal.is_member(workspace):
        raise _not_found()


def _validate_destination(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise UnsafeDestination("Destination must be a credential-free HTTPS URL.")
    if parsed.hostname.lower() == "localhost":
        raise UnsafeDestination("Private destinations are forbidden.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise UnsafeDestination("Private destinations are forbidden.")


def _not_found() -> PublicSecurityError:
    return PublicSecurityError(404, "resource_not_found", "Resource not found.")


def _response(error: Exception, request: Request) -> JSONResponse:
    if isinstance(error, (IdentityError, PublicSecurityError)):
        status = error.status_code if isinstance(error, PublicSecurityError) else 401
        return JSONResponse(status_code=status, content=map_security_error(error, _request_id(request)))
    if isinstance(error, UnsafeDestination):
        return JSONResponse(status_code=422, content=_error("unsafe_destination", str(error), request))
    assert isinstance(error, ApiConflict)
    return JSONResponse(status_code=409, content=_error(error.code, str(error), request))


def _error(code: str, message: str, request: Request) -> dict[str, Any]:
    return {"code": code, "message": message, "field_errors": [], "request_id": _request_id(request), "retryable": False}


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id", "request-unknown")


def _review_body(item: ActionEvent) -> dict[str, Any]:
    return {"event_id": item.id, "event_revision": item.revision, "decision": item.human_review, "reviewed_revision": item.reviewed_revision, "reviewed_by": item.reviewed_by}


def _enabled_body(item: EnabledAction) -> dict[str, Any]:
    return {"id": item.id, "app_id": item.app_id, "workspace_id": item.workspace_id, "destination_url": item.destination_url, "enabled": item.permission.enabled, "permission_version": item.permission.version}


def _delivery_body(item: DeliveryStatus) -> dict[str, Any]:
    return {"id": item.id, "event_id": item.event_id, "event_revision": item.event_revision, "action_id": item.action_id, "state": item.state}


def _deletion_body(item: DeletionStatus) -> dict[str, Any]:
    return {"id": item.id, "resource_kind": item.resource_kind, "resource_id": item.resource_id, "state": item.state, "irreversible": item.irreversible}
