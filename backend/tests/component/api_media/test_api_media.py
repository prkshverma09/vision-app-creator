"""CT-API-MEDIA: media upload/read/sample/delete HTTP routes."""
from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vision_app.storage.local import FileSystemMediaStore


pytestmark = pytest.mark.asyncio


def _small_video() -> tuple[bytes, str]:
    data = b"fake video bytes for testing"
    return data, hashlib.sha256(data).hexdigest()


AUTH_A = {"Authorization": "Bearer token-a"}


async def upload_and_finalize(
    client: TestClient, store: FileSystemMediaStore, content_type: str = "video/mp4"
) -> tuple[dict[str, Any], str]:
    data, sha256 = _small_video()
    init = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        json={"file_size": len(data), "content_type": content_type, "sha256": sha256},
        headers=AUTH_A,
    )
    assert init.status_code == 201
    grant_id = init.json()["grant_id"]
    await store.receive_upload(grant_id, data)
    final = client.post(
        f"/workspaces/workspace-a/uploads/{grant_id}/finalize",
        json={"actual_size": len(data), "actual_sha256": sha256},
        headers=AUTH_A,
    )
    assert final.status_code == 201, final.text
    return final.json(), grant_id


async def test_unauthenticated_access_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        json={"file_size": 100, "content_type": "video/mp4"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_identity"


async def test_missing_authorization_header_returns_401(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        json={"file_size": 100, "content_type": "video/mp4"},
    )
    assert response.status_code == 401


async def test_unauthorized_workspace_membership_is_safe_404(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-b/uploads/initiate",
        json={"file_size": 100, "content_type": "video/mp4"},
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"


async def test_oversized_upload_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        json={"file_size": 200_000, "content_type": "video/mp4"},
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["code"] == "oversized_media"


async def test_finalize_and_get_asset_metadata(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, _ = await upload_and_finalize(client, store)
    assert asset["state"] == "ready"
    assert asset["workspace_id"] == "workspace-a"
    assert asset["codec"] == "h264"
    assert asset["width"] == 320
    assert asset["height"] == 240
    assert asset["duration_ms"] == 5000

    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["id"] == asset["id"]
    assert fetched["sha256"] == asset["sha256"]


async def test_duplicate_finalize_is_idempotent_and_does_not_create_duplicate_asset(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, grant_id = await upload_and_finalize(client, store)
    # Re-finalize the same grant with identical values.
    response = client.post(
        f"/workspaces/workspace-a/uploads/{grant_id}/finalize",
        json={"actual_size": len(_small_video()[0]), "actual_sha256": _small_video()[1]},
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 201
    duplicate = response.json()
    assert duplicate["id"] == asset["id"]
    assert duplicate["generation"] == asset["generation"]


async def test_finalize_rejects_wrong_hash(client: TestClient, store: FileSystemMediaStore) -> None:
    data, _ = _small_video()
    init = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        json={"file_size": len(data), "content_type": "video/mp4", "sha256": hashlib.sha256(data).hexdigest()},
        headers={"Authorization": "Bearer token-a"},
    )
    assert init.status_code == 201
    grant_id = init.json()["grant_id"]
    await store.receive_upload(grant_id, data)

    response = client.post(
        f"/workspaces/workspace-a/uploads/{grant_id}/finalize",
        json={"actual_size": len(data), "actual_sha256": "a" * 64},
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_media"


async def test_missing_asset_returns_404(client: TestClient) -> None:
    response = client.get(
        "/workspaces/workspace-a/assets/does-not-exist",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"


async def test_read_media_streams_bytes_and_content_type(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, _ = await upload_and_finalize(client, store)
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}/media",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == b"fake video bytes for testing"


async def test_samples_returns_expected_frame_refs(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, _ = await upload_and_finalize(client, store)
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}/samples?count=2",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    samples = response.json()
    assert len(samples) == 2
    assert [sample["source_time_ms"] for sample in samples] == [1000, 2500]


async def test_samples_rejects_out_of_bounds_count(client: TestClient, store: FileSystemMediaStore) -> None:
    asset, _ = await upload_and_finalize(client, store)
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}/samples?count=0",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 422

    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}/samples?count=33",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 422


async def test_delete_asset_soft_deletes_and_blocks_media_read(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, _ = await upload_and_finalize(client, store)
    response = client.delete(
        f"/workspaces/workspace-a/assets/{asset['id']}",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["state"] in ("pending", "complete")

    # Metadata now reflects deletion.
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 200
    fetched = response.json()
    assert fetched["state"] == "deleted"

    # Reading the media is no longer permitted.
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}/media",
        headers={"Authorization": "Bearer token-a"},
    )
    assert response.status_code == 404


async def test_unauthorized_asset_access_is_safe_404(
    client: TestClient, store: FileSystemMediaStore
) -> None:
    asset, _ = await upload_and_finalize(client, store)
    response = client.get(
        f"/workspaces/workspace-a/assets/{asset['id']}",
        headers={"Authorization": "Bearer token-b"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
