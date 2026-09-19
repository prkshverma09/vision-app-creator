"""System integration test fixtures for the local backend profile."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "synthetic"


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class SequentialIdFactory:
    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def new(self, prefix: str) -> str:
        return f"{prefix}-{next(self._counter):04d}"


@pytest.fixture
def settings(tmp_path: Path) -> dict[str, Any]:
    return {
        "data_dir": tmp_path,
        "clock": FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        "id_factory": SequentialIdFactory(),
        "fixture_annotation": FIXTURES / "annotations" / "red_light_violation.json",
        "fixture_video": FIXTURES / "video" / "red_light_violation.mp4",
        "budget_microusd": 1_000_000,
    }


@pytest.fixture
def app(settings: dict[str, Any]) -> Any:
    from vision_app.bootstrap import create_app

    return create_app("local", settings)


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer token-local"}


@pytest.fixture
def workspace() -> str:
    return "workspace-local"


@pytest.fixture
def small_video_hash() -> str:
    import hashlib

    def _hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return _hash
