"""CT-API-ACTIONS: authorization, reviews, safe enablement, delivery, and deletion."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vision_app.api.actions import (
    ActionApiDependencies,
    ActionEvent,
    InMemoryActionApiService,
    InMemoryActionRepository,
    InMemoryPrivacyApiService,
    create_actions_router,
)
from vision_app.security.authorization.boundary import (
    AuthorizationBoundary,
    InMemoryOwnershipResolver,
    ResourceFamily,
    ResourceOwnership,
)
from vision_app.security.identity.testing import FakeIdentityVerifier, TestIdentity


@pytest.fixture
def harness() -> tuple[TestClient, InMemoryActionRepository, InMemoryActionApiService, InMemoryPrivacyApiService]:
    ownership = [
        ResourceOwnership(ResourceFamily.RUN, "run-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.EVENT, "event-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.APP, "app-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.ACTION_DESTINATION, "action-a", "workspace-a"),
        ResourceOwnership(ResourceFamily.DELETION_JOB, "deletion-a", "workspace-a"),
    ]
    boundary = AuthorizationBoundary(InMemoryOwnershipResolver(ownership))
    identity = FakeIdentityVerifier({
        "token-a": TestIdentity("user-a", None, frozenset({"workspace-a"})),
        "token-b": TestIdentity("user-b", None, frozenset({"workspace-b"})),
    }, profile="test")
    repository = InMemoryActionRepository([ActionEvent(
        id="event-a", workspace_id="workspace-a", run_id="run-a", revision=3,
        machine_decision="supported", human_review="unreviewed", selected_finalized=True,
    )])
    actions = InMemoryActionApiService()
    privacy = InMemoryPrivacyApiService({("asset", "asset-a"): 2}, fixed_id="deletion-a")
    app = FastAPI()
    app.include_router(create_actions_router(ActionApiDependencies(identity, boundary, repository, actions, privacy)))
    return TestClient(app), repository, actions, privacy


def auth(token: str = "token-a") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_unauthorized_review_is_hidden(harness: tuple[object, ...]) -> None:
    client = harness[0]
    response = client.post("/workspaces/workspace-a/runs/run-a/events/event-a/review", headers=auth("token-b"), json={"decision": "confirmed_by_user", "expected_revision": 3})
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"


def test_stale_review_conflicts_and_current_review_is_readable(harness: tuple[object, ...]) -> None:
    client = harness[0]
    stale = client.post("/workspaces/workspace-a/runs/run-a/events/event-a/review", headers=auth(), json={"decision": "confirmed_by_user", "expected_revision": 2})
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"
    accepted = client.post("/workspaces/workspace-a/runs/run-a/events/event-a/review", headers=auth(), json={"decision": "confirmed_by_user", "expected_revision": 3})
    assert accepted.status_code == 200
    status = client.get("/workspaces/workspace-a/runs/run-a/events/event-a/review", headers=auth())
    assert status.json() == {"event_id": "event-a", "event_revision": 4, "decision": "confirmed_by_user", "reviewed_revision": 4, "reviewed_by": "user-a"}


def test_unreviewed_event_cannot_deliver(harness: tuple[object, ...]) -> None:
    client = harness[0]
    client.post("/workspaces/workspace-a/apps/app-a/actions/action-a/enable", headers={**auth(), "Idempotency-Key": "enable-1"}, json={"destination_url": "https://hooks.example.test/action", "confirm_external_delivery": True})
    response = client.post("/workspaces/workspace-a/runs/run-a/events/event-a/deliveries", headers={**auth(), "Idempotency-Key": "delivery-1"}, json={"action_id": "action-a", "expected_revision": 3})
    assert response.status_code == 409
    assert response.json()["code"] == "action_not_eligible"


def test_unsafe_destination_rejected_without_external_call(harness: tuple[object, ...]) -> None:
    client, _, actions, _ = harness
    response = client.post("/workspaces/workspace-a/apps/app-a/actions/action-a/enable", headers={**auth(), "Idempotency-Key": "unsafe"}, json={"destination_url": "http://127.0.0.1/hook", "confirm_external_delivery": True})
    assert response.status_code == 422
    assert response.json()["code"] == "unsafe_destination"
    assert actions.external_calls == 0


def test_approved_event_creates_idempotent_delivery_and_gets_status(harness: tuple[object, ...]) -> None:
    client = harness[0]
    enabled = client.post("/workspaces/workspace-a/apps/app-a/actions/action-a/enable", headers={**auth(), "Idempotency-Key": "enable-1"}, json={"destination_url": "https://hooks.example.test/action", "confirm_external_delivery": True})
    assert enabled.status_code == 200
    client.post("/workspaces/workspace-a/runs/run-a/events/event-a/review", headers=auth(), json={"decision": "confirmed_by_user", "expected_revision": 3})
    path = "/workspaces/workspace-a/runs/run-a/events/event-a/deliveries"
    first = client.post(path, headers={**auth(), "Idempotency-Key": "deliver-1"}, json={"action_id": "action-a", "expected_revision": 4})
    duplicate = client.post(path, headers={**auth(), "Idempotency-Key": "deliver-1"}, json={"action_id": "action-a", "expected_revision": 4})
    assert first.status_code == 202
    assert first.json()["id"] == duplicate.json()["id"]
    detail = client.get(f"{path}/{first.json()['id']}", headers=auth())
    assert detail.status_code == 200
    assert detail.json()["state"] == "pending"


def test_deletion_generation_mismatch_and_status(harness: tuple[object, ...]) -> None:
    client = harness[0]
    mismatch = client.post("/workspaces/workspace-a/deletions/deletion-a", headers={**auth(), "Idempotency-Key": "delete-1"}, json={"resource_kind": "asset", "resource_id": "asset-a", "expected_generation": 1})
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "generation_mismatch"
    accepted = client.post("/workspaces/workspace-a/deletions/deletion-a", headers={**auth(), "Idempotency-Key": "delete-2"}, json={"resource_kind": "asset", "resource_id": "asset-a", "expected_generation": 2})
    assert accepted.status_code == 202
    assert accepted.json()["state"] == "pending"
    status = client.get("/workspaces/workspace-a/deletions/deletion-a", headers=auth())
    assert status.status_code == 200
    assert status.json()["irreversible"] is False
