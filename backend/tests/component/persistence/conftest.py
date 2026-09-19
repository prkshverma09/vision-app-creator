"""Shared fixtures for component persistence tests."""
from datetime import datetime, timezone

import pytest

from vision_app.contracts.models import (
    AppVersion,
    EvidencePolicy,
    ExecutionLimits,
    ResourceId,
    TrackedRule,
    TrackedRulesSpec,
    UtcTimestamp,
    VisionApp,
)
from vision_app.persistence.memory import InMemoryRepository
from vision_app.security.identity.models import Principal


@pytest.fixture
def workspace_id() -> str:
    return "ws-001"


@pytest.fixture
def principal() -> Principal:
    return Principal(
        user_id="user-001",
        email=None,
        workspace_ids=frozenset({"ws-001"}),
    )


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def vision_app(principal: Principal) -> VisionApp:
    return VisionApp(
        id=ResourceId("app-001"),
        workspace_id=ResourceId("ws-001"),
        title="Test app",
        draft_version_id=None,
        published_version_id=None,
        revision=1,
    )


@pytest.fixture
def app_version(principal: Principal, now: datetime, vision_app: VisionApp) -> AppVersion:
    spec = TrackedRulesSpec(
        title="test",
        objective="test objective",
        kind="tracked_rules",
        rules=[TrackedRule(rule_id=ResourceId("rule-001"), capability_id="tracked.line_crossing", object_classes=["person"])],
        limits=ExecutionLimits(),
        evidence_policy=EvidencePolicy(),
    )
    return AppVersion(
        id=ResourceId("version-001"),
        app_id=vision_app.id,
        workspace_id=vision_app.workspace_id,
        spec=spec,
        capability_manifest={"capability": "tracked.line_crossing"},
        model_manifest={"detector": "rf-detr-small"},
        validation_report=["ok"],
        created_by=ResourceId("user-001"),
        created_at=UtcTimestamp(now),
    )
