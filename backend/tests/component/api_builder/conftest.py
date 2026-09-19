"""Fixtures for builder API component tests."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vision_app.api.builder import BuilderDependencies, create_builder_router, add_builder_exception_handlers
from vision_app.applications import AppService, CalibrationService, VersionService
from vision_app.applications.services import ApplicationRepository
from vision_app.builder.agent import BuilderRequest
from vision_app.builder.ports import BuildTurnStore, InMemoryBuildTurnStore
from vision_app.contracts.models import BuildTurn, ResourceId
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity
from vision_app.validation.validator import validate_app_spec


class FakeRepository(ApplicationRepository):
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}

    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        return deepcopy(self.values.get((kind, resource_id)))

    async def list_owned(self, kind: str, principal: Any) -> list[Any]:
        workspace = str(principal)
        return [
            deepcopy(v)
            for (k, _), v in self.values.items()
            if k == kind
            and getattr(v, "workspace_id", ResourceId(workspace)).root == workspace
        ]

    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool:
        key = (kind, resource_id)
        if key in self.values:
            return False
        self.values[key] = deepcopy(value)
        return True

    async def compare_and_swap(
        self, kind: str, resource_id: str, revision: int, value: Any
    ) -> bool:
        key = (kind, resource_id)
        current = self.values.get(key)
        current_revision = 0 if current is None else current.revision
        if current_revision != revision:
            return False
        self.values[key] = deepcopy(value)
        return True


class FixedClock:
    value: datetime

    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


class SequentialIdFactory:
    def __init__(self) -> None:
        self._counter = 0

    def new(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"


class MutableOwnershipResolver:
    def __init__(self) -> None:
        self._items: dict[tuple[ResourceFamily, str], ResourceOwnership] = {}

    def register(self, ownership: ResourceOwnership) -> None:
        self._items[(ownership.family, ownership.resource_id)] = ownership

    async def resolve(
        self, family: ResourceFamily, resource_id: str
    ) -> ResourceOwnership | None:
        return self._items.get((family, resource_id))


class FakeBuilderAgent:
    def __init__(self, ids: SequentialIdFactory, store: BuildTurnStore) -> None:
        self._ids = ids
        self._store = store

    async def build(self, request: BuilderRequest) -> BuildTurn:
        turn = BuildTurn(
            id=ResourceId(self._ids.new("build-turn")),
            app_id=ResourceId(request.app_id),
            instruction=request.instruction,
            base_version_id=ResourceId(request.base_version_id) if request.base_version_id else None,
            base_revision=request.base_revision,
            status="proposed",
            tool_progress=["fake.compiler"],
            clarification=None,
            proposed_version_id=None,
            preview_run_id=None,
            usage=None,
        )
        await self._store.save(turn)
        return turn


@dataclass
class Deps:
    repo: FakeRepository
    ids: SequentialIdFactory
    clock: FixedClock
    app_service: AppService
    version_service: VersionService
    calibration_service: CalibrationService
    turn_store: InMemoryBuildTurnStore
    resolver: MutableOwnershipResolver
    boundary: AuthorizationBoundary
    verifier: FakeIdentityVerifier
    builder: FakeBuilderAgent


@pytest.fixture
def deps() -> Deps:
    repo = FakeRepository()
    ids = SequentialIdFactory()
    clock = FixedClock()
    versions = VersionService(repo, validate_app_spec, clock, ids)
    calibrations = CalibrationService(repo, clock, ids)
    apps = AppService(repo, versions, validate_app_spec, ids)
    store = InMemoryBuildTurnStore()
    resolver = MutableOwnershipResolver()
    boundary = AuthorizationBoundary(resolver)
    verifier = FakeIdentityVerifier(
        {
            "token-a": TestIdentity("user-a", "a@example.test", frozenset({"workspace-a"})),
            "token-b": TestIdentity("user-b", "b@example.test", frozenset({"workspace-b"})),
        },
        profile="cpu",
    )
    builder = FakeBuilderAgent(ids, store)
    return Deps(
        repo=repo,
        ids=ids,
        clock=clock,
        app_service=apps,
        version_service=versions,
        calibration_service=calibrations,
        turn_store=store,
        resolver=resolver,
        boundary=boundary,
        verifier=verifier,
        builder=builder,
    )


@pytest.fixture
def client(deps: Deps) -> TestClient:
    def _request_id() -> str:
        return f"req-{deps.ids.new('request')}"

    router = create_builder_router(
        BuilderDependencies(
            identity_verifier=deps.verifier,
            authorization=deps.boundary,
            app_service=deps.app_service,
            version_service=deps.version_service,
            calibration_service=deps.calibration_service,
            builder_agent=deps.builder,
            build_turn_store=deps.turn_store,
            request_id=_request_id,
        )
    )
    app = FastAPI()
    app.include_router(router)
    add_builder_exception_handlers(app)
    return TestClient(app)
