"""ASGI entry point for the Vision App Creator backend."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from vision_app.api.composition import create_app

DATA_DIR = Path(os.environ.get("VISION_APP_DATA_DIR", "/tmp/vision-app-data"))
FIXTURE_ANNOTATION = Path(
    os.environ.get(
        "VISION_APP_FIXTURE_ANNOTATION",
        "fixtures/synthetic/annotations/red_light_violation.json",
    )
)

app = create_app(
    "local",
    {
        "data_dir": DATA_DIR,
        "analysis_mode": os.environ.get("VISION_APP_ANALYSIS_MODE", "scripted"),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY"),
        "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
        "fixture_annotation": FIXTURE_ANNOTATION,
        "budget_microusd": 1_000_000,
        "test_token": os.environ.get("VISION_APP_TEST_TOKEN", "token-local"),
        "test_workspace_id": os.environ.get(
            "VISION_APP_TEST_WORKSPACE", "workspace-local"
        ),
        "test_user_id": os.environ.get("VISION_APP_TEST_USER", "local-user"),
    },
)


if __name__ == "__main__":
    uvicorn.run(
        "vision_app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )
