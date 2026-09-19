"""Test fixtures for the ordered runtime engine."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vision_app.contracts.models import (
    BoxN,
    Calibration,
    ExecutionLimits,
    FrameRef,
    PointN,
    ResourceId,
    SourceTimeMs,
    TrackedRule,
    TrackedRulesSpec,
    UtcTimestamp,
)
from vision_app.contracts.ports import BudgetLedger
from vision_app.jobs.sinks import InMemoryEventSink
from vision_app.operations.ledger import BudgetLedgerService
from vision_app.operations.tracing import InMemoryTraceSink
from vision_app.perception.detection.adapter import RfDetrDetector
from vision_app.perception.detection.backend import RawDetection
from vision_app.perception.detection.config import DetectorConfig
from vision_app.perception.detection.fake_backend import FakeDetectorBackend
from vision_app.perception.tracking.byte_track import ByteTrackFactory
from vision_app.storage.local import FileSystemMediaStore

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "synthetic"


def load_annotation(name: str) -> dict[str, Any]:
    path = FIXTURES / "annotations" / f"{name}.json"
    return json.loads(path.read_text())


def video_path(name: str) -> Path:
    return FIXTURES / "video" / f"{name}.mp4"


async def stage_source(store: FileSystemMediaStore, path: Path, owner_id: str) -> tuple[str, str, int]:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    grant = await store.begin_upload(owner_id, "video/mp4", len(data), declared_sha256=sha, idempotency_key="src-1")
    await store.receive_upload(grant.grant_id, data)
    meta = await store.finalize_upload(grant.grant_id, actual_size=len(data), actual_sha256=sha)
    return meta.resource_id.root, sha, meta.generation


@pytest.fixture
def clock():
    class FixedClock:
        value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        def now(self) -> datetime: return self.value
    return FixedClock()


@pytest.fixture
def id_factory():
    import itertools
    class SequentialIdFactory:
        def __init__(self) -> None: self._counter = itertools.count(1)
        def new(self, prefix: str) -> str: return f"{prefix}-{next(self._counter):04d}"
    return SequentialIdFactory()


@pytest.fixture
def trace_sink() -> InMemoryTraceSink:
    return InMemoryTraceSink()


@pytest.fixture
def event_sink() -> InMemoryEventSink:
    return InMemoryEventSink()


@pytest.fixture
def store(tmp_path: Path, clock: Any) -> FileSystemMediaStore:
    return FileSystemMediaStore(data_dir=tmp_path, max_bytes=250_000_000, clock=clock)


@pytest.fixture
def atomic_repository():
    from copy import deepcopy
    import asyncio

    class AtomicRepository:
        def __init__(self) -> None:
            self.values: dict[tuple[str, str], Any] = {}
            self._lock = asyncio.Lock()

        async def get_owned(self, kind: str, resource_id: str, principal: Any) -> Any:
            del principal
            async with self._lock:
                value = self.values.get((kind, resource_id))
                return deepcopy(value)

        async def compare_and_swap(
            self, kind: str, resource_id: str, revision: int, value: Any
        ) -> bool:
            async with self._lock:
                current = self.values.get((kind, resource_id))
                current_revision = 0 if current is None else current["revision"]
                if current_revision != revision:
                    return False
                self.values[(kind, resource_id)] = deepcopy(value)
                return True

    return AtomicRepository()


@pytest.fixture
def ledger(atomic_repository: Any, id_factory: Any) -> BudgetLedger:
    return BudgetLedgerService(atomic_repository, id_factory, budget_microusd=1_000_000)


def _detection_responses(annotation: dict[str, Any]) -> list[list[RawDetection]]:
    """Build per-frame RawDetection responses matching the fixture annotation."""
    width = annotation["video"]["width"]
    height = annotation["video"]["height"]
    responses: list[list[RawDetection]] = []
    for frame in annotation["frames"]:
        detections: list[RawDetection] = []
        for box in frame.get("boxes", []):
            x1, y1, x2, y2 = box["box_px"]
            detections.append(
                RawDetection(
                    class_id=2,  # car in the default RF-DETR class map
                    score=0.9,
                    box=(x1 / width, y1 / height, x2 / width, y2 / height),
                )
            )
        responses.append(detections)
    return responses


@pytest.fixture
def detector_factory():
    def make(annotation: dict[str, Any]) -> RfDetrDetector:
        backend = FakeDetectorBackend(responses=_detection_responses(annotation))
        config = DetectorConfig(
            provider="rfdetr",
            model_name="rfdetr-small-fake",
            checkpoint_path="/dev/null/checkpoint.pth",
            checkpoint_revision="sha256:abcdef1234567890",
            score_threshold=0.0,
        )
        return RfDetrDetector(config, backend)

    return make


class ScriptedSignalObserver:
    """Deterministic signal observer driven by the fixture annotation."""

    def __init__(self, per_frame_states: dict[int, str], roi_id: str = "signal-1") -> None:
        self._states = per_frame_states
        self._roi_id = roi_id

    def observe(self, frame: Any, roi_id: str) -> Any:
        from vision_app.contracts.models import ObservationQuality, ResourceId, SignalObservation

        state = self._states.get(frame.frame_ref.source_time_ms.root, "unknown")
        return SignalObservation(
            roi_id=ResourceId(roi_id),
            source_time_ms=frame.frame_ref.source_time_ms,
            state=state,  # type: ignore[arg-type]
            quality=ObservationQuality(),
        )


@pytest.fixture
def signal_observer_factory():
    def make(annotation: dict[str, Any]) -> ScriptedSignalObserver:
        states = {f["source_time_ms"]: f["signal_state"] for f in annotation["frames"]}
        return ScriptedSignalObserver(states)

    return make


@pytest.fixture
def tracker_factory() -> ByteTrackFactory:
    return ByteTrackFactory()


@pytest.fixture
def calibration() -> Calibration:
    return Calibration(
        id=ResourceId("cal-1"),
        source_id=ResourceId("source-1"),
        camera_binding="static",
        revision=1,
        reference_frame=FrameRef(
            source_id=ResourceId("source-1"),
            source_hash="a" * 64,
            pts=0,
            time_base_num=1,
            time_base_den=1000,
            source_time_ms=SourceTimeMs(0),
            sequence=0,
            width=320,
            height=240,
            transform_id=ResourceId("tfm-1"),
        ),
        workspace_id=ResourceId("workspace-a"),
        lines={"stop_line": [PointN(x=0.5, y=0.0), PointN(x=0.5, y=1.0)]},
        lanes={},
        rois={"signal-1": BoxN(x1=285 / 320, y1=20 / 240, x2=305 / 320, y2=40 / 240)},
        governing_signals={"stop_line": "signal-1"},
        confirmed_by=ResourceId("user-1"),
        confirmed_at=UtcTimestamp(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        scene_fingerprint="fp",
    )


@pytest.fixture
def rule() -> TrackedRule:
    return TrackedRule(
        rule_id=ResourceId("stop_line"),
        capability_id="tracked.red_phase_crossing",
        object_classes=["car"],
    )


@pytest.fixture
def spec(rule: TrackedRule) -> TrackedRulesSpec:
    return TrackedRulesSpec(
        schema_version="1.0",
        title="Red phase crossing",
        objective="Detect cars crossing on red",
        evidence_policy={"before_ms": 3000, "after_ms": 3000},
        approved_action_refs=[],
        limits=ExecutionLimits(),
        kind="tracked_rules",
        rules=[rule],
    )
