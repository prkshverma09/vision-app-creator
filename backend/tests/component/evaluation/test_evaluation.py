"""CT-EVAL: deterministic event matching, geometry, latency, and cost metrics."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from vision_app.contracts.models import (
    BoxN,
    Event,
    EvidenceManifest,
    MoneyMicrousd,
    ResourceId,
    SourceTimeMs,
    TimeRange,
)
from vision_app.evaluation.metrics import (
    GroundTruthAnnotation,
    aggregate_cost,
    aggregate_latency,
    box_iou,
    evaluate_events,
    event_iou,
)

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures" / "synthetic" / "annotations"


def time_range(start_ms: int, end_ms: int) -> TimeRange:
    return TimeRange(start_ms=SourceTimeMs(start_ms), end_ms=SourceTimeMs(end_ms))


def event(event_id: str, start_ms: int, end_ms: int, label: str) -> Event:
    source_range = time_range(start_ms, end_ms)
    return Event(
        id=ResourceId(event_id),
        run_id=ResourceId("run-1"),
        attempt_id=ResourceId("attempt-1"),
        spec_version_id=ResourceId("version-1"),
        calibration_id=None,
        source_range=source_range,
        rule_id=ResourceId(label),
        track_refs=[],
        facts={},
        evidence=EvidenceManifest(requested_range=source_range, actual_range=None, state="pending"),
        machine_decision="supported",
        human_review="unreviewed",
        revision=0,
    )


def annotation(annotation_id: str, start_ms: int, end_ms: int, label: str) -> GroundTruthAnnotation:
    return GroundTruthAnnotation(annotation_id, time_range(start_ms, end_ms), label)


def test_event_iou_uses_half_open_source_intervals() -> None:
    assert event_iou(time_range(1000, 3000), time_range(2000, 4000)) == pytest.approx(1 / 3)
    assert event_iou(time_range(0, 1000), time_range(1000, 2000)) == 0.0


def test_evaluator_penalizes_duplicates_misses_wrong_intervals_and_abstentions() -> None:
    truth = [
        annotation("a1", 1000, 2000, "crossing"),
        annotation("a2", 4000, 5000, "crossing"),
        annotation("a3", 7000, 8000, "zone"),
    ]
    predictions = [
        event("e1", 1000, 2000, "crossing"),
        event("duplicate", 1100, 1900, "crossing"),
        event("wrong-interval", 5200, 6200, "crossing"),
    ]

    result = evaluate_events(predictions, truth, iou_threshold=0.5, duration_ms=3_600_000)

    assert (result.true_positives, result.false_positives, result.false_negatives) == (1, 2, 2)
    assert result.precision == pytest.approx(1 / 3)
    assert result.recall == pytest.approx(1 / 3)
    assert result.false_positives_per_hour == 2.0
    assert result.confusion.labels == ("crossing", "zone", "__none__")
    assert result.confusion.count("crossing", "crossing") == 1
    assert result.confusion.count("crossing", "__none__") == 1
    assert result.confusion.count("zone", "__none__") == 1
    assert result.confusion.count("__none__", "crossing") == 2


def test_wrong_class_is_one_false_positive_and_one_missed_class() -> None:
    result = evaluate_events(
        [event("e1", 1000, 2000, "zone")],
        [annotation("a1", 1000, 2000, "crossing")],
        iou_threshold=0.5,
        duration_ms=10_000,
    )
    assert (result.true_positives, result.false_positives, result.false_negatives) == (0, 1, 1)
    assert result.confusion.count("crossing", "zone") == 1
    assert result.per_class["crossing"].recall == 0.0
    assert result.per_class["zone"].precision == 0.0


def test_existing_synthetic_fixture_provides_deterministic_ground_truth() -> None:
    payload = json.loads((FIXTURES / "red_light_violation.json").read_text())
    expected = payload["expected_events"][0]
    start_ms, end_ms = expected["crossing_bracket_ms"]
    truth = [annotation("fixture-event", start_ms, end_ms, expected["type"])]
    prediction = event("run-event", start_ms, end_ms, expected["type"])

    result = evaluate_events(
        [prediction],
        truth,
        iou_threshold=0.5,
        duration_ms=payload["video"]["duration_ms"],
    )

    assert result.precision == result.recall == 1.0
    assert result.matches[0].iou == 1.0


def test_box_iou_measures_calibration_geometry_quality() -> None:
    expected = BoxN(x1=0.0, y1=0.0, x2=0.5, y2=0.5)
    predicted = BoxN(x1=0.25, y1=0.25, x2=0.75, y2=0.75)
    assert box_iou(predicted, expected) == pytest.approx(1 / 7)


def test_latency_percentiles_use_deterministic_nearest_rank() -> None:
    summary = aggregate_latency([10, 20, 30, 40, 100])
    assert (summary.count, summary.minimum_ms, summary.maximum_ms) == (5, 10, 100)
    assert (summary.p50_ms, summary.p95_ms, summary.p99_ms) == (30, 100, 100)
    assert summary.mean_ms == 40.0


def test_cost_aggregation_reports_cost_per_video_minute() -> None:
    summary = aggregate_cost(
        [MoneyMicrousd(250_000), MoneyMicrousd(750_000)],
        processed_duration_ms=120_000,
    )
    assert summary.total_microusd == 1_000_000
    assert summary.cost_per_video_minute_microusd == 500_000


def test_aggregations_reject_empty_latency_and_zero_duration() -> None:
    with pytest.raises(ValueError, match="latency"):
        aggregate_latency([])
    with pytest.raises(ValueError, match="duration"):
        aggregate_cost([], processed_duration_ms=0)
