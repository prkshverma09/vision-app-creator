"""CT-RUNTIME: ordered engine composes perception, rules, evidence and operations."""
from __future__ import annotations

from typing import Any

import pytest

from vision_app.contracts.models import ResourceId
from vision_app.evidence.extractor import EvidenceExtractor
from vision_app.media.decoder import LocalVideoDecoder
from vision_app.reasoning import (
    ReasoningBudget,
    ScriptedVisualReasoner,
    SemanticReasoningService,
)
from vision_app.runtime.engine import RunContext, RunEngine

from .conftest import load_annotation, stage_source, video_path


FFMPEG = __import__("shutil").which("ffmpeg")
FFPROBE = __import__("shutil").which("ffprobe")
pytestmark = [
    pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg is required for CT-RUNTIME"),
    pytest.mark.asyncio,
]


def _engine(
    store,
    detector_factory,
    signal_observer_factory,
    tracker_factory,
    event_sink,
    ledger,
    trace_sink,
    id_factory,
    annotation_name: str,
    reasoner=None,
    use_evidence: bool = True,
):
    annotation = load_annotation(annotation_name)
    detector = detector_factory(annotation)
    signal_observer = signal_observer_factory(annotation)
    decoder = LocalVideoDecoder()
    extractor = EvidenceExtractor(decoder, store) if use_evidence else None
    return RunEngine(
        decoder=decoder,
        detector=detector,
        tracker_factory=tracker_factory,
        signal_observer=signal_observer,
        reasoner=reasoner,
        evidence_extractor=extractor,
        ledger=ledger,
        event_sink=event_sink,
        trace_sink=trace_sink,
        id_factory=id_factory,
    )


async def _context(
    store,
    spec,
    calibration,
    name: str = "red_light_violation",
    review_prompt: str | None = None,
    review_budget=None,
) -> RunContext:
    path = video_path(name)
    storage_ref, sha, generation = await stage_source(store, path, "owner-1")
    return RunContext(
        run_id=ResourceId("run-1"),
        attempt_id=ResourceId("attempt-1"),
        workspace_id=ResourceId("ws-1"),
        owner_id="owner-1",
        source_id=ResourceId("source-1"),
        source_path=str(path),
        storage_ref=storage_ref,
        source_generation=generation,
        source_sha256=sha,
        spec_version_id=ResourceId("version-1"),
        spec=spec,
        calibration=calibration,
        review_prompt=review_prompt,
        review_budget=review_budget,
    )


async def test_red_phase_pipeline_produces_one_supported_event(
    store: Any,
    detector_factory: Any,
    signal_observer_factory: Any,
    tracker_factory: Any,
    event_sink: Any,
    ledger: Any,
    trace_sink: Any,
    id_factory: Any,
    spec: Any,
    calibration: Any,
) -> None:
    reasoner = SemanticReasoningService(
        ScriptedVisualReasoner(
            reviews=[{"agreement": "agree", "reason": "clear red crossing"}]
        ),
        ReasoningBudget(max_calls=10, timeout_ms=5000),
    )
    engine = _engine(
        store,
        detector_factory,
        signal_observer_factory,
        tracker_factory,
        event_sink,
        ledger,
        trace_sink,
        id_factory,
        "red_light_violation",
        reasoner=reasoner,
    )
    ctx = await _context(
        store,
        spec,
        calibration,
        review_prompt="Does the vehicle clearly cross on red?",
        review_budget=ReasoningBudget(max_calls=10, timeout_ms=5000),
    )

    result = await engine.run(ctx, fence=1)

    supported = [e for e in event_sink.events.values() if e.machine_decision == "supported"]
    assert len(supported) == 1, f"expected one supported event, got {event_sink.events}"
    event = supported[0]
    assert event.source_range.start_ms.root == 2900
    assert event.source_range.end_ms.root == 3100
    assert event.evidence.state in ("available", "degraded")
    assert event.evidence.thumbnail_ref is not None
    assert event.evidence.clip_ref is not None
    assert result.phase == "completed"


async def test_no_event_when_vehicle_crosses_before_red(
    store: Any,
    detector_factory: Any,
    signal_observer_factory: Any,
    tracker_factory: Any,
    event_sink: Any,
    ledger: Any,
    trace_sink: Any,
    id_factory: Any,
    spec: Any,
    calibration: Any,
) -> None:
    annotation = load_annotation("red_light_violation")
    for frame in annotation["frames"]:
        frame["signal_state"] = "green"
    engine = _engine(
        store,
        detector_factory,
        signal_observer_factory,
        tracker_factory,
        event_sink,
        ledger,
        trace_sink,
        id_factory,
        "red_light_violation",
    )
    # Override signal observer with the modified annotation.
    engine._signal_observer = signal_observer_factory(annotation)
    ctx = await _context(store, spec, calibration)

    result = await engine.run(ctx, fence=1)

    assert len(event_sink.events) == 0
    assert result.phase == "completed"


async def test_cancellation_mid_run_produces_partial_progress(
    store: Any,
    detector_factory: Any,
    signal_observer_factory: Any,
    tracker_factory: Any,
    event_sink: Any,
    ledger: Any,
    trace_sink: Any,
    id_factory: Any,
    spec: Any,
    calibration: Any,
) -> None:
    engine = _engine(
        store,
        detector_factory,
        signal_observer_factory,
        tracker_factory,
        event_sink,
        ledger,
        trace_sink,
        id_factory,
        "red_light_violation",
        use_evidence=False,
    )
    ctx = await _context(store, spec, calibration)

    cancel_after = {"frames": 15}

    def cancel_check() -> bool:
        cancel_after["frames"] -= 1
        return cancel_after["frames"] <= 0

    result = await engine.run(ctx, fence=1, is_cancelled=cancel_check)

    assert result.phase == "cancelled"
    assert result.progress.processed_samples < 50
    assert result.progress.cancel_requested is True


async def test_delayed_review_is_handled_without_blocking_pipeline(
    store: Any,
    detector_factory: Any,
    signal_observer_factory: Any,
    tracker_factory: Any,
    event_sink: Any,
    ledger: Any,
    trace_sink: Any,
    id_factory: Any,
    spec: Any,
    calibration: Any,
) -> None:
    delayed_reasoner = SemanticReasoningService(
        ScriptedVisualReasoner(
            reviews=[{"agreement": "agree", "reason": "clear red crossing"}],
            delay_ms=50,
        ),
        ReasoningBudget(max_calls=10, timeout_ms=5000),
    )
    engine = _engine(
        store,
        detector_factory,
        signal_observer_factory,
        tracker_factory,
        event_sink,
        ledger,
        trace_sink,
        id_factory,
        "red_light_violation",
        reasoner=delayed_reasoner,
    )
    ctx = await _context(
        store,
        spec,
        calibration,
        review_prompt="Does the vehicle clearly cross on red?",
        review_budget=ReasoningBudget(max_calls=10, timeout_ms=5000),
    )

    result = await engine.run(ctx, fence=1)

    supported = [e for e in event_sink.events.values() if e.machine_decision == "supported"]
    assert len(supported) == 1
    assert delayed_reasoner._reasoner.review_calls == 1
    assert result.phase == "completed"
