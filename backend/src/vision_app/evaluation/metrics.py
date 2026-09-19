"""Pure, deterministic metrics for comparing run events with ground truth."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import ceil

from vision_app.contracts.models import BoxN, Event, MoneyMicrousd, TimeRange

NONE_LABEL = "__none__"


@dataclass(frozen=True, slots=True)
class GroundTruthAnnotation:
    """Minimal evaluator annotation independent of any dataset file format."""

    id: str
    source_range: TimeRange
    class_label: str


@dataclass(frozen=True, slots=True)
class EventMatch:
    event_id: str
    annotation_id: str
    predicted_class: str
    actual_class: str
    iou: float


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    true_positives: int
    predicted: int
    actual: int
    precision: float
    recall: float
    accuracy: float


@dataclass(frozen=True, slots=True)
class ConfusionMatrix:
    """Rows are actual labels and columns are predicted labels."""

    labels: tuple[str, ...]
    values: tuple[tuple[int, ...], ...]

    def count(self, actual: str, predicted: str) -> int:
        return self.values[self.labels.index(actual)][self.labels.index(predicted)]


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    matches: tuple[EventMatch, ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    false_positives_per_hour: float
    confusion: ConfusionMatrix
    per_class: Mapping[str, ClassMetrics]


@dataclass(frozen=True, slots=True)
class LatencySummary:
    count: int
    minimum_ms: int
    maximum_ms: int
    mean_ms: float
    p50_ms: int
    p95_ms: int
    p99_ms: int


@dataclass(frozen=True, slots=True)
class CostSummary:
    total_microusd: int
    processed_duration_ms: int
    cost_per_video_minute_microusd: float


def event_iou(left: TimeRange, right: TimeRange) -> float:
    """Intersection-over-union for half-open source-time intervals."""
    intersection = max(
        0,
        min(left.end_ms.root, right.end_ms.root) - max(left.start_ms.root, right.start_ms.root),
    )
    union = (
        left.end_ms.root
        - left.start_ms.root
        + right.end_ms.root
        - right.start_ms.root
        - intersection
    )
    return intersection / union


def box_iou(left: BoxN, right: BoxN) -> float:
    """IoU for normalized calibration boxes."""
    intersection_width = max(0.0, min(left.x2, right.x2) - max(left.x1, right.x1))
    intersection_height = max(0.0, min(left.y2, right.y2) - max(left.y1, right.y1))
    intersection = intersection_width * intersection_height
    left_area = (left.x2 - left.x1) * (left.y2 - left.y1)
    right_area = (right.x2 - right.x1) * (right.y2 - right.y1)
    return intersection / (left_area + right_area - intersection)


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_events(
    events: Sequence[Event],
    annotations: Sequence[GroundTruthAnnotation],
    *,
    iou_threshold: float,
    duration_ms: int,
) -> EvaluationResult:
    """One-to-one IoU matching; unmatched duplicates and abstentions are penalized."""
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError("IoU threshold must be between zero and one")
    if duration_ms <= 0:
        raise ValueError("evaluation duration must be positive")

    candidates = [
        (event_iou(event.source_range, truth.source_range), event_index, truth_index)
        for event_index, event in enumerate(events)
        for truth_index, truth in enumerate(annotations)
    ]
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_events: set[int] = set()
    used_truth: set[int] = set()
    matches: list[EventMatch] = []
    for iou, event_index, truth_index in candidates:
        if iou < iou_threshold:
            break
        if event_index in used_events or truth_index in used_truth:
            continue
        used_events.add(event_index)
        used_truth.add(truth_index)
        event = events[event_index]
        truth = annotations[truth_index]
        matches.append(
            EventMatch(
                event_id=event.id.root,
                annotation_id=truth.id,
                predicted_class=event.rule_id.root,
                actual_class=truth.class_label,
                iou=iou,
            )
        )

    event_labels = {event.rule_id.root for event in events}
    truth_labels = {truth.class_label for truth in annotations}
    labels = tuple(sorted(event_labels | truth_labels) + [NONE_LABEL])
    indices = {label: index for index, label in enumerate(labels)}
    values = [[0 for _ in labels] for _ in labels]
    for match in matches:
        values[indices[match.actual_class]][indices[match.predicted_class]] += 1
    for index, event in enumerate(events):
        if index not in used_events:
            values[indices[NONE_LABEL]][indices[event.rule_id.root]] += 1
    for index, truth in enumerate(annotations):
        if index not in used_truth:
            values[indices[truth.class_label]][indices[NONE_LABEL]] += 1

    correct_matches = sum(match.actual_class == match.predicted_class for match in matches)
    false_positives = len(events) - correct_matches
    false_negatives = len(annotations) - correct_matches
    per_class: dict[str, ClassMetrics] = {}
    for label in labels[:-1]:
        label_index = indices[label]
        predicted = sum(row[label_index] for row in values)
        actual = sum(values[label_index])
        true_positives = values[label_index][label_index]
        true_negatives = sum(
            values[row][column]
            for row in range(len(labels))
            for column in range(len(labels))
            if row != label_index and column != label_index
        )
        total = sum(sum(row) for row in values)
        per_class[label] = ClassMetrics(
            true_positives=true_positives,
            predicted=predicted,
            actual=actual,
            precision=_safe_ratio(true_positives, predicted),
            recall=_safe_ratio(true_positives, actual),
            accuracy=_safe_ratio(true_positives + true_negatives, total),
        )

    return EvaluationResult(
        matches=tuple(matches),
        true_positives=correct_matches,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=_safe_ratio(correct_matches, len(events)),
        recall=_safe_ratio(correct_matches, len(annotations)),
        false_positives_per_hour=false_positives * 3_600_000 / duration_ms,
        confusion=ConfusionMatrix(labels, tuple(tuple(row) for row in values)),
        per_class=per_class,
    )


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    return values[max(0, ceil(percentile * len(values)) - 1)]


def aggregate_latency(durations_ms: Iterable[int]) -> LatencySummary:
    values = sorted(durations_ms)
    if not values:
        raise ValueError("at least one latency is required")
    if values[0] < 0:
        raise ValueError("latency cannot be negative")
    return LatencySummary(
        count=len(values),
        minimum_ms=values[0],
        maximum_ms=values[-1],
        mean_ms=sum(values) / len(values),
        p50_ms=_nearest_rank(values, 0.50),
        p95_ms=_nearest_rank(values, 0.95),
        p99_ms=_nearest_rank(values, 0.99),
    )


def aggregate_cost(costs: Iterable[MoneyMicrousd], *, processed_duration_ms: int) -> CostSummary:
    if processed_duration_ms <= 0:
        raise ValueError("processed duration must be positive")
    total = sum(cost.root for cost in costs)
    return CostSummary(
        total_microusd=total,
        processed_duration_ms=processed_duration_ms,
        cost_per_video_minute_microusd=total * 60_000 / processed_duration_ms,
    )
