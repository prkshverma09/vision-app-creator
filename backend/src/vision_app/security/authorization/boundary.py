"""Single default-deny resource authorization boundary for API composition."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from vision_app.security.identity.errors import PublicSecurityError
from vision_app.security.identity.models import Principal


class ResourceFamily(StrEnum):
    APP = "app"
    VERSION = "version"
    ASSET = "asset"
    CALIBRATION = "calibration"
    BUILD_TURN = "build_turn"
    RUN = "run"
    ATTEMPT = "attempt"
    EVENT = "event"
    EVIDENCE = "evidence"
    DELIVERY = "delivery"
    RESERVATION = "reservation"
    DELETION_JOB = "deletion_job"
    UPLOAD = "upload"
    ACTION_DESTINATION = "action_destination"


@dataclass(frozen=True, slots=True)
class ResourceOwnership:
    family: ResourceFamily
    resource_id: str
    workspace_id: str


class OwnershipResolver(Protocol):
    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None: ...


class InMemoryOwnershipResolver:
    """Repository double used for authorization conformance without cloud calls."""

    def __init__(self, ownership: list[ResourceOwnership]) -> None:
        self._items = {(item.family, item.resource_id): item for item in ownership}

    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None:
        return self._items.get((family, resource_id))


class AuthorizationBoundary:
    """Resolve server-side ownership and hide absence vs forbidden access.

    ``caller_workspace_id`` is accepted only to make accidental reliance testable; it is never
    used to grant access. API handlers should pass authenticated Principal plus opaque resource ID.
    """

    def __init__(self, resolver: OwnershipResolver) -> None:
        self._resolver = resolver

    async def require(
        self,
        principal: Principal,
        family: ResourceFamily,
        resource_id: str,
        *,
        caller_workspace_id: str | None = None,
    ) -> ResourceOwnership:
        del caller_workspace_id
        ownership = await self._resolver.resolve(family, resource_id)
        if ownership is None or not principal.is_member(ownership.workspace_id):
            raise PublicSecurityError(404, "resource_not_found", "Resource not found.")
        return ownership

    async def app(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.APP, resource_id)

    async def version(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.VERSION, resource_id)

    async def asset(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.ASSET, resource_id)

    async def calibration(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.CALIBRATION, resource_id)

    async def build_turn(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.BUILD_TURN, resource_id)

    async def run(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.RUN, resource_id)

    async def attempt(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.ATTEMPT, resource_id)

    async def event(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.EVENT, resource_id)

    async def evidence(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.EVIDENCE, resource_id)

    async def delivery(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.DELIVERY, resource_id)

    async def reservation(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.RESERVATION, resource_id)

    async def deletion_job(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.DELETION_JOB, resource_id)

    async def upload(self, principal: Principal, resource_id: str) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.UPLOAD, resource_id)

    async def action_destination(
        self, principal: Principal, resource_id: str
    ) -> ResourceOwnership:
        return await self.require(principal, ResourceFamily.ACTION_DESTINATION, resource_id)
