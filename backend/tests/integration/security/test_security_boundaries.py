"""I04 security integration checks against the composed local backend.

The suite deliberately uses only the local app factory and deterministic in-memory or
filesystem adapters.  No destination is contacted: SSRF checks stop in the safe
transport before its in-memory sink can be invoked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vision_app.actions import (
    Destination,
    DestinationSafetyError,
    InMemoryWebhookSink,
    SafeWebhookTransport,
    StaticResolver,
)
from vision_app.bootstrap import create_app

pytestmark = pytest.mark.integration


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        "local",
        {
            "data_dir": tmp_path,
            "clock": _Clock(),
            "test_workspace_id": "workspace-a",
            "test_user_id": "user-a",
            "test_token": "token-a",
        },
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": "Bearer token-a"}


def test_cross_tenant_id_substitution_is_always_a_safe_404(
    client: TestClient, headers: dict[str, str]
) -> None:
    created = client.post(
        "/workspaces/workspace-a/apps", json={"title": "private"}, headers=headers
    )
    assert created.status_code == 201
    app_id = created.json()["id"]

    # App, run, event, and asset routes all fail at the authenticated workspace
    # boundary before revealing whether the substituted identifier exists.
    paths = (
        f"/workspaces/workspace-b/apps/{app_id}",
        "/workspaces/workspace-b/runs/run-from-b",
        "/workspaces/workspace-b/runs/run-from-b/events",
        "/workspaces/workspace-b/runs/run-from-b/events/event-from-b",
        "/workspaces/workspace-b/assets/asset-from-b",
        "/workspaces/workspace-b/assets/asset-from-b/media",
    )
    responses = [client.get(path, headers=headers) for path in paths]
    assert {response.status_code for response in responses} == {404}
    for response in responses:
        body = response.json()
        assert body["code"] == "resource_not_found"
        assert "workspace-b" not in response.text


def test_hostile_title_and_prompt_remain_json_data_not_markup(
    client: TestClient, headers: dict[str, str]
) -> None:
    hostile = '<img src=x onerror="fetch(`https://attacker.invalid`)\">&<script>alert(1)</script>'
    created = client.post(
        "/workspaces/workspace-a/apps", json={"title": hostile}, headers=headers
    )
    assert created.status_code == 201
    assert created.headers["content-type"].startswith("application/json")
    assert created.json()["title"] == hostile

    app_id = created.json()["id"]
    turn = client.post(
        f"/workspaces/workspace-a/builds/{app_id}/turns",
        headers=headers,
        json={"instruction": hostile, "base_revision": 0, "preview": False},
    )
    assert turn.status_code == 202
    assert turn.headers["content-type"].startswith("application/json")
    # JSON encoding must not turn attacker-controlled text into an HTML response.
    assert "text/html" not in turn.headers["content-type"]


def test_oversized_media_is_rejected_before_an_upload_grant(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post(
        "/workspaces/workspace-a/uploads/initiate",
        headers=headers,
        json={"file_size": 250_000_001, "content_type": "video/mp4"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "oversized_media"


@pytest.mark.parametrize(
    "path",
    [
        "/workspaces/workspace-a/apps",
        "/workspaces/workspace-a/uploads/initiate",
        "/workspaces/workspace-a/runs",
    ],
)
def test_invalid_json_has_a_bounded_validation_response(
    client: TestClient, headers: dict[str, str], path: str
) -> None:
    response = client.post(
        path,
        headers={**headers, "Content-Type": "application/json", "Idempotency-Key": "bad-json"},
        content=b'{"unterminated":',
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert len(response.content) < 16_384
    assert "Traceback" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("http://hooks.example.test/action", ["93.184.216.34"]),
        ("https://localhost/action", ["127.0.0.1"]),
        ("https://hooks.example.test/action", ["127.0.0.1"]),
        ("https://hooks.example.test/action", ["::1"]),
        ("https://hooks.example.test/action", ["169.254.169.254"]),
        ("https://hooks.example.test/action", ["93.184.216.34", "10.0.0.1"]),
    ],
)
async def test_webhook_destination_requires_public_https_without_network(
    url: str, addresses: list[str]
) -> None:
    sink = InMemoryWebhookSink()
    if url.startswith("http://"):
        with pytest.raises(ValueError):
            Destination("destination", url)
        assert sink.requests == []
        return

    host = url.split("/", 3)[2]
    transport = SafeWebhookTransport(
        {"destination": Destination("destination", url)},
        StaticResolver({host: addresses}),
        sink,
    )
    with pytest.raises(DestinationSafetyError):
        await transport.send("destination", b"{}", "sha256=test")
    assert sink.requests == []
