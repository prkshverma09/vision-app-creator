"""System integration test: full local red-light pipeline without cloud or real models.

Exercises chat -> app creation -> fixture upload -> calibration -> publish -> run ->
events -> review -> action preview using local file storage, in-memory repository, and
scripted detector/signal adapters.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.integration


def _wait_for_run(
    client: TestClient,
    workspace: str,
    run_id: str,
    auth_headers: dict[str, str],
    timeout: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(
            f"/workspaces/{workspace}/runs/{run_id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        if body["state"] in ("completed", "partial", "failed", "cancelled"):
            return body
        time.sleep(0.1)
    raise TimeoutError(f"run {run_id} did not finish within {timeout}s")


def test_full_local_red_light_pipeline(
    client: TestClient,
    auth_headers: dict[str, str],
    workspace: str,
    settings: dict[str, Any],
) -> None:
    fixture_video: Path = settings["fixture_video"]
    video_bytes = fixture_video.read_bytes()
    video_hash = hashlib.sha256(video_bytes).hexdigest()

    # 1. Chat / create app via builder
    response = client.post(
        f"/workspaces/{workspace}/apps",
        json={"title": "Red light violation"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    app_body = response.json()
    app_id = app_body["id"]
    assert app_body["title"] == "Red light violation"

    # 2. Build app: submit a chat turn (local compiler returns a proposed spec).
    turn_response = client.post(
        f"/workspaces/{workspace}/builds/{app_id}/turns",
        json={
            "instruction": "Detect cars crossing the stop line on a red signal",
            "base_revision": 0,
            "base_version_id": None,
            "source_id": None,
            "preview": False,
            "timeout_seconds": 5.0,
        },
        headers=auth_headers,
    )
    assert turn_response.status_code == 202, turn_response.text
    turn_body = turn_response.json()
    assert turn_body["status"] == "proposed"
    assert turn_body["tool_progress"]

    # Create the concrete version directly using the builder version endpoint.
    spec: dict[str, Any] = {
        "kind": "tracked_rules",
        "schema_version": "1.0",
        "title": "Red light violation",
        "objective": "Detect cars crossing on red",
        "evidence_policy": {"before_ms": 3000, "after_ms": 3000},
        "approved_action_refs": [],
        "limits": {"max_duration_ms": 300000, "max_model_calls": 100},
        "rules": [
            {
                "rule_id": "stop_line",
                "capability_id": "tracked.red_phase_crossing",
                "object_classes": ["car"],
            }
        ],
    }
    version_response = client.post(
        f"/workspaces/{workspace}/apps/{app_id}/versions",
        json={"expected_revision": 0, "base_version_id": None, "spec": spec},
        headers=auth_headers,
    )
    assert version_response.status_code == 201, version_response.text
    version_id = version_response.json()["id"]

    # 3. Upload fixture video
    initiate_response = client.post(
        f"/workspaces/{workspace}/uploads/initiate",
        json={
            "file_size": len(video_bytes),
            "content_type": "video/mp4",
            "sha256": video_hash,
        },
        headers=auth_headers,
    )
    assert initiate_response.status_code == 201, initiate_response.text
    grant = initiate_response.json()
    upload_id = grant["grant_id"]

    response = client.post(
        f"/workspaces/{workspace}/uploads/{upload_id}/bytes",
        content=video_bytes,
        headers={**auth_headers, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 204, response.text

    finalize_response = client.post(
        f"/workspaces/{workspace}/uploads/{upload_id}/finalize",
        json={
            "actual_size": len(video_bytes),
            "actual_sha256": video_hash,
        },
        headers=auth_headers,
    )
    assert finalize_response.status_code == 201, finalize_response.text
    asset = finalize_response.json()
    asset_id = asset["id"]
    assert asset["state"] == "ready"

    preview_url = f"/api/v1/media/{asset_id}/preview.webm"
    preview = client.get(preview_url)
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "video/webm"
    import av
    import io
    with av.open(io.BytesIO(preview.content)) as container:
        assert container.streams.video[0].codec_context.name == "vp8"
        frames = list(container.decode(video=0))
        assert len(frames) == 50
        assert (frames[0].width, frames[0].height) == (320, 240)
    ranged = client.get(preview_url, headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert ranged.content == preview.content[:100]
    assert ranged.headers["accept-ranges"] == "bytes"
    assert client.get("/api/v1/media/missing/preview.webm").status_code == 404
    original = client.get(f"/api/v1/media/{asset_id}")
    assert hashlib.sha256(original.content).hexdigest() == video_hash

    # 4. Calibrate using the uploaded source.
    reference_frame = {
        "source_id": asset_id,
        "source_hash": asset["sha256"],
        "pts": 0,
        "time_base_num": 1,
        "time_base_den": 1000,
        "source_time_ms": 0,
        "sequence": 0,
        "width": asset["width"],
        "height": asset["height"],
        "transform_id": "transform-local",
    }
    calibration_payload = {
        "source_id": asset_id,
        "camera_binding": "camera-a",
        "reference_frame": reference_frame,
        "lanes": {},
        "lines": {
            "stop_line": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}]
        },
        "rois": {
            "signal-1": {"x1": 0.89, "y1": 0.08, "x2": 0.95, "y2": 0.17}
        },
        "governing_signals": {"stop_line": "signal-1"},
        "scene_fingerprint": "local-fixture-view",
    }
    calibration_response = client.post(
        f"/workspaces/{workspace}/apps/{app_id}/calibrations",
        json=calibration_payload,
        headers=auth_headers,
    )
    assert calibration_response.status_code == 201, calibration_response.text
    calibration = calibration_response.json()
    calibration_id = calibration["id"]
    assert calibration["confirmed_by"] is None

    # 5. Confirm calibration
    confirm_response = client.post(
        f"/workspaces/{workspace}/apps/{app_id}/calibrations/{calibration_id}/confirm",
        json={"expected_revision": 1, "confirmed_by": "user-local"},
        headers=auth_headers,
    )
    assert confirm_response.status_code == 200, confirm_response.text
    confirmed = confirm_response.json()
    assert confirmed["confirmed_by"] == "user-local"

    # 6. Publish version
    publish_response = client.post(
        f"/workspaces/{workspace}/apps/{app_id}/versions/{version_id}/publish",
        json={
            "expected_revision": 1,
            "calibration_id": calibration_id,
            "approved_action_refs": [],
        },
        headers=auth_headers,
    )
    assert publish_response.status_code == 200, publish_response.text
    published_app = publish_response.json()
    assert published_app["published_version_id"] == version_id

    # 7. Create and run the red-light fixture.
    run_response = client.post(
        f"/workspaces/{workspace}/runs",
        headers={**auth_headers, "Idempotency-Key": "run-1"},
        json={
            "version_id": version_id,
            "asset_id": asset_id,
            "calibration_id": calibration_id,
        },
    )
    assert run_response.status_code == 202, run_response.text
    run = run_response.json()
    run_id = run["id"]

    # 8. Wait for completion and fetch one supported event.
    final = _wait_for_run(client, workspace, run_id, auth_headers)
    assert final["state"] == "completed", final

    events_response = client.get(
        f"/workspaces/{workspace}/runs/{run_id}/events", headers=auth_headers
    )
    assert events_response.status_code == 200, events_response.text
    events = events_response.json()["items"]
    assert len(events) >= 1, events
    event = next(e for e in events if e["machine_decision"] == "supported")
    assert event["human_review"] == "unreviewed"
    event_id = event["id"]
    thumbnail = client.get(f"/api/v1/media/{event['evidence']['thumbnail_ref']}")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert thumbnail.content.startswith(b"\xff\xd8")

    # 9. Review the event
    review_response = client.post(
        f"/workspaces/{workspace}/runs/{run_id}/events/{event_id}/review",
        json={"decision": "confirmed_by_user", "expected_revision": 0},
        headers=auth_headers,
    )
    assert review_response.status_code == 200, review_response.text
    review_body = review_response.json()
    assert review_body["decision"] == "confirmed_by_user"

    # 10. Enable an action and preview it.
    action_id = "action.webhook_dispatch"
    enable_response = client.post(
        f"/workspaces/{workspace}/apps/{app_id}/actions/{action_id}/enable",
        headers={**auth_headers, "Idempotency-Key": "enable-1"},
        json={
            "destination_url": "https://example.com/webhook",
            "confirm_external_delivery": True,
        },
    )
    assert enable_response.status_code == 200, enable_response.text

    preview_response = client.post(
        f"/workspaces/{workspace}/runs/{run_id}/events/{event_id}/actions/preview",
        headers=auth_headers,
    )
    assert preview_response.status_code == 200, preview_response.text
    preview_body = preview_response.json()
    assert preview_body["event_id"] == event_id
    assert preview_body["dry_run"] is True
