from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import itertools
import pytest

@dataclass
class FixedClock:
    value: datetime
    def now(self) -> datetime: return self.value

class SequentialIdFactory:
    def __init__(self) -> None: self._counter = itertools.count(1)
    def new(self, prefix: str) -> str: return f"{prefix}-{next(self._counter):04d}"

@pytest.fixture
def clock() -> FixedClock: return FixedClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
@pytest.fixture
def id_factory() -> SequentialIdFactory: return SequentialIdFactory()
@pytest.fixture
def temp_dir(tmp_path: Path) -> Path: return tmp_path
@pytest.fixture
def test_config(temp_dir: Path) -> dict[str, object]: return {"profile": "cpu", "data_dir": temp_dir, "network": "deny"}
