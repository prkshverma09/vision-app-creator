from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from vision_app.applications import (
    AppConflict,
    AppService,
    CalibrationService,
    CacheReuseService,
    InvalidProposal,
    VersionService,
)
from vision_app.contracts.models import (
    BoxN,
    FrameRef,
    PointN,
    ResourceId,
    SemanticCondition,
    SemanticWindowsSpec,
    SourceTimeMs,
    TrackedRule,
    TrackedRulesSpec,
)
from vision_app.validation.validator import validate_app_spec


class FakeRepository:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}

    async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
        return deepcopy(self.values.get((kind, resource_id)))

    async def list_owned(self, kind: str, principal: Any) -> list[Any]:
        workspace = str(principal)
        return [deepcopy(v) for (k, _), v in self.values.items() if k == kind and getattr(v, "workspace_id", ResourceId(workspace)).root == workspace]

    async def add_immutable(self, kind: str, resource_id: str, value: Any) -> bool:
        key = (kind, resource_id)
        if key in self.values:
            return False
        self.values[key] = deepcopy(value)
        return True

    async def compare_and_swap(self, kind: str, resource_id: str, revision: int, value: Any) -> bool:
        key = (kind, resource_id)
        current = self.values.get(key)
        current_revision = 0 if current is None else current.revision
        if current_revision != revision:
            return False
        self.values[key] = deepcopy(value)
        return True


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def new(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}-{self.value}"


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


def tracked(title: str = "Traffic", classes: list[str] | None = None) -> TrackedRulesSpec:
    return TrackedRulesSpec(kind="tracked_rules", title=title, objective="Count crossings", rules=[TrackedRule(rule_id=ResourceId("rule"), capability_id="tracked.line_crossing", object_classes=classes or ["car"])])


def semantic(title: str = "Safety") -> SemanticWindowsSpec:
    return SemanticWindowsSpec(kind="semantic_windows", title=title, objective="Find smoke", conditions=[SemanticCondition(condition_id=ResourceId("condition"), prompt="Smoke is visible")], window_ms=5000, stride_ms=2500, sample_fps=1)


def frame(source: str) -> FrameRef:
    return FrameRef(source_id=ResourceId(source), source_hash="a" * 64, pts=0, time_base_num=1, time_base_den=1000, source_time_ms=SourceTimeMs(0), sequence=0, width=1920, height=1080, transform_id=ResourceId("transform"))


@pytest.fixture
def services() -> tuple[FakeRepository, AppService, VersionService, CalibrationService]:
    repo = FakeRepository()
    ids = Ids()
    versions = VersionService(repo, validate_app_spec, Clock(), ids)
    calibrations = CalibrationService(repo, Clock(), ids)
    return repo, AppService(repo, versions, validate_app_spec, ids), versions, calibrations


@pytest.mark.asyncio
async def test_revising_draft_does_not_mutate_published_version(services: tuple[FakeRepository, AppService, VersionService, CalibrationService]) -> None:
    _, apps, _, calibrations = services
    app = await apps.create("workspace", "Traffic")
    calibration = await calibrations.create("workspace", "source-1", "camera-a", frame("source-1"), {"lane": [PointN(x=0, y=0), PointN(x=1, y=0), PointN(x=1, y=1)]}, {"stop": [PointN(x=0, y=.5), PointN(x=1, y=.5)]}, {}, {}, "view-a")
    calibration = await calibrations.confirm("workspace", calibration.id.root, 1, "user")
    first = await apps.revise("workspace", app.id.root, 0, None, tracked())
    published_app = await apps.publish("workspace", app.id.root, 1, first.id.root, calibration)
    second = await apps.revise("workspace", app.id.root, 2, first.id.root, tracked("Changed policy"))
    current = await apps.read("workspace", app.id.root)
    assert current.published_version_id == first.id
    assert current.draft_version_id == second.id
    assert published_app.published_version_id == first.id


@pytest.mark.asyncio
async def test_changed_source_view_invalidates_confirmation_but_same_view_binding_does_not(services: tuple[FakeRepository, AppService, VersionService, CalibrationService]) -> None:
    _, _, _, service = services
    calibration = await service.create("workspace", "clip-1", "camera-a", frame("clip-1"), {}, {}, {"roi": BoxN(x1=.1, y1=.1, x2=.2, y2=.2)}, {}, "view-a")
    confirmed = await service.confirm("workspace", calibration.id.root, 1, "user")
    same = await service.bind_source("workspace", calibration.id.root, 2, "clip-2", frame("clip-2"), "view-a")
    assert same.confirmed_by == confirmed.confirmed_by
    changed = await service.bind_source("workspace", calibration.id.root, 3, "clip-3", frame("clip-3"), "view-b")
    assert changed.confirmed_by is None and changed.confirmed_at is None


@pytest.mark.asyncio
async def test_stale_update_conflicts(services: tuple[FakeRepository, AppService, VersionService, CalibrationService]) -> None:
    _, apps, _, _ = services
    app = await apps.create("workspace", "Traffic")
    first = await apps.revise("workspace", app.id.root, 0, None, tracked())
    with pytest.raises(AppConflict):
        await apps.revise("workspace", app.id.root, 0, None, tracked("stale"))
    with pytest.raises(AppConflict):
        await apps.revise("workspace", app.id.root, 1, "wrong-parent", tracked())
    assert first.parent_id is None


@pytest.mark.asyncio
async def test_create_list_read_immutable_versions_and_readiness(services: tuple[FakeRepository, AppService, VersionService, CalibrationService]) -> None:
    repo, apps, versions, _ = services
    a = await apps.create("workspace", "Tracked")
    await apps.create("workspace", "Semantic")
    listed = await apps.list("workspace")
    assert [item.title for item in listed] == ["Semantic", "Tracked"]
    version = await apps.revise("workspace", a.id.root, 0, None, tracked())
    assert version.validation_report == [] and version.model_manifest
    stored = await versions.read("workspace", version.id.root)
    assert stored == version
    assert (await apps.readiness("workspace", version.id.root)).state == "needs_calibration"
    semantic_app = next(item for item in listed if item.title == "Semantic")
    semantic_version = await apps.revise("workspace", semantic_app.id.root, 0, None, semantic())
    assert (await apps.readiness("workspace", semantic_version.id.root)).state == "publication_ready"
    with pytest.raises(ValidationError):
        version.spec.title = "mutated"  # type: ignore[misc]
    assert repo.values[("app_version", version.id.root)] == version


@pytest.mark.asyncio
async def test_invalid_proposal_is_not_persisted(services: tuple[FakeRepository, AppService, VersionService, CalibrationService]) -> None:
    _, apps, _, _ = services
    app = await apps.create("workspace", "Bad")
    with pytest.raises(InvalidProposal):
        await apps.revise("workspace", app.id.root, 0, None, semantic().model_copy(update={"conditions": [SemanticCondition(condition_id=ResourceId("condition"), prompt="Track each person")] }))


def test_policy_only_cache_reuse_requires_perception_manifest_compatibility() -> None:
    policy_edit = tracked("Renamed")
    original = tracked()
    assert CacheReuseService.can_reuse(original, policy_edit, {"detector.common": "v1"}, {"detector.common": "v1"})
    assert not CacheReuseService.can_reuse(original, policy_edit, {"detector.common": "v1"}, {"detector.common": "v2"})
    assert not CacheReuseService.can_reuse(original, tracked(classes=["truck"]), {"detector.common": "v1"}, {"detector.common": "v1"})
    assert not CacheReuseService.can_reuse(semantic(), semantic("Renamed"), {"reasoner.window": "v1"}, {"reasoner.window": "v1"})
