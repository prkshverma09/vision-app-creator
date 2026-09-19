"""Operator-approved R01 live cloud smoke tests.

These tests make paid network calls and mutate isolated staging resources. They skip
unless each test's explicit environment contract is present. No fake adapter,
default credential, or implied data-rights fallback is provided.
"""
from __future__ import annotations

import base64
import importlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from _pytest.mark.structures import Mark

# Construct marks without requiring a root-manifest edit (R01 does not own pyproject.toml).
# The names remain selectable with ``-m live`` / ``-m cloud`` under strict marker mode.
pytestmark = [Mark("live", (), {}, _ispytest=True), Mark("cloud", (), {}, _ispytest=True)]


class _Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _Ids:
    def new(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"


def _require_env(*names: str) -> dict[str, str]:
    """Return required values or skip without guessing credentials/configuration."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip("R01 live gate missing explicit environment: " + ", ".join(missing))
    return {name: os.environ[name] for name in names}


def _require_module(name: str, install_hint: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        pytest.skip(f"R01 live gate requires {name}; {install_hint}")


def _assert_rights() -> Path:
    env = _require_env("R01_DATA_RIGHTS_CONFIRMED", "R01_SAMPLE_FRAME")
    if env["R01_DATA_RIGHTS_CONFIRMED"].lower() != "yes":
        pytest.skip("R01_DATA_RIGHTS_CONFIRMED must explicitly equal 'yes'")
    frame = Path(env["R01_SAMPLE_FRAME"])
    if not frame.is_file():
        pytest.skip("R01_SAMPLE_FRAME must name an existing authorized sample image")
    return frame


@pytest.mark.asyncio
async def test_gemini_compile_real_adapter_contract() -> None:
    """A real compile returns typed output and records non-scripted Gemini provenance."""
    env = _require_env("GEMINI_API_KEY")
    from vision_app.providers.gemini.compiler import GeminiCompilerModel
    from vision_app.providers.gemini.config import GeminiConfig

    config = GeminiConfig(
        api_key=env["GEMINI_API_KEY"],
        model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        revision=os.getenv("GEMINI_MODEL_REVISION", "live"),
        profile="production",
    )
    result = await GeminiCompilerModel(config, _Clock(), _Ids()).compile(
        "Count people crossing a user-confirmed line; ask for missing scene geometry.",
        {"workspace_id": "r01-live-smoke"},
    )

    assert result.usage.provider == "gemini"
    assert result.usage.model == config.model
    assert result.usage.adapter_mode == "structured"
    assert result.outcome.kind in {"needs_input", "proposed_version", "unsupported_request"}
    if result.outcome.kind == "unsupported_request":
        pytest.fail(f"real Gemini compile did not satisfy the contract: {result.outcome.code}")


def test_rfdetr_detection_on_modal_contract() -> None:
    """An authorized frame sent to the deployed RF-DETR function yields valid boxes."""
    _require_env("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
    frame = _assert_rights()
    modal = _require_module("modal", "install the coordinator-approved Modal dependency")

    app_name = os.getenv("R01_MODAL_APP", "vision-app-creator")
    function_name = os.getenv("R01_MODAL_RFDETR_FUNCTION", "detect_frame")
    function = modal.Function.from_name(app_name, function_name)
    result = function.remote(
        {
            "content_type": os.getenv("R01_SAMPLE_FRAME_CONTENT_TYPE", "image/jpeg"),
            "image_base64": base64.b64encode(frame.read_bytes()).decode("ascii"),
        }
    )

    assert isinstance(result, dict)
    assert result.get("provider") == "rfdetr"
    assert isinstance(result.get("model_revision"), str) and result["model_revision"]
    detections = result.get("detections")
    assert isinstance(detections, list)
    for detection in detections:
        assert isinstance(detection.get("class_name"), str)
        assert 0.0 <= float(detection["score"]) <= 1.0
        x1, y1, x2, y2 = detection["box"]
        assert 0.0 <= x1 < x2 <= 1.0
        assert 0.0 <= y1 < y2 <= 1.0


@pytest.mark.asyncio
async def test_gcs_upload_download_real_adapter_contract() -> None:
    """The GCS adapter round-trips exact bytes in the dedicated staging bucket."""
    env = _require_env("GOOGLE_CLOUD_PROJECT", "GCS_BUCKET")
    _require_module("google.cloud.storage", "install the cloud optional dependency group")
    from vision_app.storage.gcs import GCSMediaStore

    payload = f"r01-gcs-smoke:{uuid.uuid4().hex}".encode()
    store = GCSMediaStore(
        bucket_name=env["GCS_BUCKET"],
        project=env["GOOGLE_CLOUD_PROJECT"],
        max_bytes=1024,
        clock=_Clock(),
    )
    resource_id = await store.put_artifact("r01-live-smoke", payload, "text/plain")
    try:
        grant = await store.issue_read_grant("r01-live-smoke", resource_id, ttl_seconds=60)
        assert await store.read(grant.grant_id) == payload
    finally:
        await store.delete_artifact(resource_id)


def test_firestore_read_write_contract() -> None:
    """Firestore persists and reads an isolated document, then removes it."""
    env = _require_env("GOOGLE_CLOUD_PROJECT", "FIRESTORE_DATABASE")
    firestore = _require_module(
        "google.cloud.firestore", "install the coordinator-approved Firestore dependency"
    )
    client = firestore.Client(
        project=env["GOOGLE_CLOUD_PROJECT"], database=env["FIRESTORE_DATABASE"]
    )
    nonce = uuid.uuid4().hex
    ref = client.collection("r01_live_smoke").document(nonce)
    value = {"nonce": nonce, "purpose": "R01 ephemeral acceptance smoke"}
    try:
        ref.set(value)
        snapshot = ref.get()
        assert snapshot.exists
        assert snapshot.to_dict() == value
    finally:
        ref.delete()
