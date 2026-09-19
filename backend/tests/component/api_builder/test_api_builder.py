"""Component tests for the builder HTTP API (task A02)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from vision_app.contracts.models import ResourceId, SourceTimeMs
from vision_app.security.authorization.boundary import ResourceFamily, ResourceOwnership


AUTH_A = {"Authorization": "Bearer token-a"}
AUTH_B = {"Authorization": "Bearer token-b"}


def frame_ref(source: str = "source-1") -> dict[str, Any]:
    return {
        "source_id": source,
        "source_hash": "a" * 64,
        "pts": 0,
        "time_base_num": 1,
        "time_base_den": 1000,
        "source_time_ms": 0,
        "sequence": 0,
        "width": 1920,
        "height": 1080,
        "transform_id": "transform-1",
    }


def tracked_spec(title: str = "Traffic") -> dict[str, Any]:
    return {
        "kind": "tracked_rules",
        "schema_version": "1.0",
        "title": title,
        "objective": "Count crossings",
        "rules": [
            {
                "rule_id": "rule-1",
                "capability_id": "tracked.line_crossing",
                "object_classes": ["car"],
            }
        ],
    }


def invalid_spec() -> dict[str, Any]:
    return {
        "kind": "tracked_rules",
        "schema_version": "1.0",
        "title": "Bad",
        "objective": "Track spaceships",
        "rules": [
            {
                "rule_id": "rule-1",
                "capability_id": "tracked.line_crossing",
                "object_classes": ["spaceship"],
            }
        ],
    }


@pytest.mark.asyncio
async def test_unauthenticated_requests_return_401(client: TestClient) -> None:
    response = client.post("/workspaces/workspace-a/apps", json={"title": "Traffic"})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "invalid_identity"

    response = client.get("/workspaces/workspace-a/apps")
    assert response.status_code == 401

    response = client.get("/workspaces/workspace-a/apps/app-1")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(client: TestClient) -> None:
    response = client.post("/workspaces/workspace-a/apps", json={"title": "Traffic"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-a/apps",
        json={"title": "Traffic"},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_user_without_workspace_membership_gets_404(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-a/apps",
        json={"title": "Traffic"},
        headers=AUTH_B,
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"


@pytest.mark.asyncio
async def test_create_list_and_get_app_with_pointers(client: TestClient, deps: Any) -> None:
    # Create an app
    response = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Traffic"}, headers=AUTH_A
    )
    assert response.status_code == 201
    body = response.json()
    app_id = body["id"]
    assert body["title"] == "Traffic"
    assert body["draft_version_id"] is None
    assert body["published_version_id"] is None
    assert body["revision"] == 0

    # List apps
    response = client.get("/workspaces/workspace-a/apps", headers=AUTH_A)
    assert response.status_code == 200
    listed = response.json()
    assert any(item["id"] == app_id for item in listed)

    # Get app
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))
    response = client.get(f"/workspaces/workspace-a/apps/{app_id}", headers=AUTH_A)
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["id"] == app_id
    assert fetched["draft_version_id"] is None
    assert fetched["published_version_id"] is None

    # User B cannot access the app
    response = client.get(f"/workspaces/workspace-a/apps/{app_id}", headers=AUTH_B)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_version_and_stale_revision_conflict(client: TestClient, deps: Any) -> None:
    create_resp = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Traffic"}, headers=AUTH_A
    )
    app_id = create_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))

    # First version succeeds
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions",
        json={"expected_revision": 0, "base_version_id": None, "spec": tracked_spec()},
        headers=AUTH_A,
    )
    assert response.status_code == 201
    version_id = response.json()["id"]

    # Stale revision conflicts
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions",
        json={"expected_revision": 0, "base_version_id": None, "spec": tracked_spec("Stale")},
        headers=AUTH_A,
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"

    # Wrong base version id conflicts
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions",
        json={
            "expected_revision": 1,
            "base_version_id": "wrong-parent",
            "spec": tracked_spec("Wrong parent"),
        },
        headers=AUTH_A,
    )
    assert response.status_code == 409

    # Fetch version
    deps.resolver.register(ResourceOwnership(ResourceFamily.VERSION, version_id, "workspace-a"))
    response = client.get(
        f"/workspaces/workspace-a/apps/{app_id}/versions/{version_id}", headers=AUTH_A
    )
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["id"] == version_id
    assert fetched["app_id"] == app_id
    assert fetched["spec"]["title"] == "Traffic"


@pytest.mark.asyncio
async def test_invalid_spec_rejected(client: TestClient, deps: Any) -> None:
    create_resp = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Bad"}, headers=AUTH_A
    )
    app_id = create_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))

    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions",
        json={"expected_revision": 0, "base_version_id": None, "spec": invalid_spec()},
        headers=AUTH_A,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_spec"


@pytest.mark.asyncio
async def test_calibration_view_change_invalidates_confirmation(client: TestClient, deps: Any) -> None:
    # Seed an owned source asset so the calibration route can authorize it
    from vision_app.contracts.models import SourceAsset

    asset_id = "source-1"
    asset = SourceAsset(
        id=ResourceId(asset_id),
        workspace_id=ResourceId("workspace-a"),
        byte_size=1024,
        codec="h264",
        width=1920,
        height=1080,
        duration_ms=SourceTimeMs(30000),
        storage_ref=ResourceId("storage-1"),
        sha256="a" * 64,
        state="ready",
        generation=1,
    )
    deps.repo.values[("asset", asset_id)] = asset
    deps.resolver.register(ResourceOwnership(ResourceFamily.ASSET, asset_id, "workspace-a"))

    create_resp = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Traffic"}, headers=AUTH_A
    )
    app_id = create_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))

    calibration_payload = {
        "source_id": asset_id,
        "camera_binding": "camera-a",
        "reference_frame": frame_ref(asset_id),
        "lanes": {"lane": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
        "lines": {"stop": [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}]},
        "rois": {"signal": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}},
        "governing_signals": {"lane": "signal"},
        "scene_fingerprint": "view-a",
    }

    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations",
        json=calibration_payload,
        headers=AUTH_A,
    )
    assert response.status_code == 201
    calibration_id = response.json()["id"]
    deps.resolver.register(
        ResourceOwnership(ResourceFamily.CALIBRATION, calibration_id, "workspace-a")
    )

    # Confirm the calibration
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations/{calibration_id}/confirm",
        json={"expected_revision": 1, "confirmed_by": "user-a"},
        headers=AUTH_A,
    )
    assert response.status_code == 200
    assert response.json()["confirmed_by"] == "user-a"

    # Re-bind to a different source view clears confirmation
    updated_payload = {
        **calibration_payload,
        "calibration_id": calibration_id,
        "expected_revision": 2,
        "scene_fingerprint": "view-b",
    }
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations",
        json=updated_payload,
        headers=AUTH_A,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_by"] is None
    assert body["confirmed_at"] is None

    # GET returns the updated calibration
    response = client.get(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations/{calibration_id}",
        headers=AUTH_A,
    )
    assert response.status_code == 200
    assert response.json()["confirmed_by"] is None


@pytest.mark.asyncio
async def test_builder_turn_submit_and_get(client: TestClient, deps: Any) -> None:
    create_resp = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Chat"}, headers=AUTH_A
    )
    app_id = create_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))

    response = client.post(
        f"/workspaces/workspace-a/builds/{app_id}/turns",
        json={
            "instruction": "Count cars",
            "base_revision": 0,
            "base_version_id": None,
            "source_id": "source-1",
            "preview": False,
        },
        headers=AUTH_A,
    )
    assert response.status_code == 202
    body = response.json()
    turn_id = body["id"]
    assert body["status"] == "proposed"

    deps.resolver.register(ResourceOwnership(ResourceFamily.BUILD_TURN, turn_id, "workspace-a"))
    response = client.get(
        f"/workspaces/workspace-a/builds/{app_id}/turns/{turn_id}", headers=AUTH_A
    )
    assert response.status_code == 200
    assert response.json()["id"] == turn_id

    response = client.get(
        f"/workspaces/workspace-a/builds/{app_id}/turns/{turn_id}", headers=AUTH_B
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_publish_tracked_version_requires_confirmed_calibration(
    client: TestClient, deps: Any
) -> None:
    from vision_app.contracts.models import SourceAsset

    asset_id = "source-1"
    deps.repo.values[("asset", asset_id)] = SourceAsset(
        id=ResourceId(asset_id),
        workspace_id=ResourceId("workspace-a"),
        byte_size=1024,
        codec="h264",
        width=1920,
        height=1080,
        duration_ms=SourceTimeMs(30000),
        storage_ref=ResourceId("storage-1"),
        sha256="a" * 64,
        state="ready",
        generation=1,
    )
    deps.resolver.register(ResourceOwnership(ResourceFamily.ASSET, asset_id, "workspace-a"))

    create_resp = client.post(
        "/workspaces/workspace-a/apps", json={"title": "Traffic"}, headers=AUTH_A
    )
    app_id = create_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.APP, app_id, "workspace-a"))

    version_resp = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions",
        json={"expected_revision": 0, "base_version_id": None, "spec": tracked_spec()},
        headers=AUTH_A,
    )
    version_id = version_resp.json()["id"]
    deps.resolver.register(ResourceOwnership(ResourceFamily.VERSION, version_id, "workspace-a"))

    calibration_resp = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations",
        json={
            "source_id": asset_id,
            "camera_binding": "camera-a",
            "reference_frame": frame_ref(asset_id),
            "lanes": {"lane": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
            "lines": {"stop": [{"x": 0, "y": 0.5}, {"x": 1, "y": 0.5}]},
            "rois": {"signal": {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}},
            "governing_signals": {"lane": "signal"},
            "scene_fingerprint": "view-a",
        },
        headers=AUTH_A,
    )
    calibration_id = calibration_resp.json()["id"]
    deps.resolver.register(
        ResourceOwnership(ResourceFamily.CALIBRATION, calibration_id, "workspace-a")
    )

    # Unconfirmed calibration blocks publication
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions/{version_id}/publish",
        json={"expected_revision": 1, "calibration_id": calibration_id, "approved_action_refs": []},
        headers=AUTH_A,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "not_publication_ready"

    # Confirm and publish
    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/calibrations/{calibration_id}/confirm",
        json={"expected_revision": 1, "confirmed_by": "user-a"},
        headers=AUTH_A,
    )
    assert response.status_code == 200

    response = client.post(
        f"/workspaces/workspace-a/apps/{app_id}/versions/{version_id}/publish",
        json={"expected_revision": 1, "calibration_id": calibration_id, "approved_action_refs": []},
        headers=AUTH_A,
    )
    assert response.status_code == 200
    app_body = response.json()
    assert app_body["published_version_id"] == version_id
