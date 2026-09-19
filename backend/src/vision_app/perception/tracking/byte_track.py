"""ByteTrack tracker adapter behind the C0 ``TrackerFactory`` / ``TrackerSession`` ports.

Uses ``supervision.ByteTrack`` for data association.  The adapter maintains per-attempt
state so that track IDs and class histories are independent between runs.  Source time is
treated as authoritative: out-of-order frames are rejected and gaps larger than
``max_gap_ms`` trigger a scene reset.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from warnings import catch_warnings, simplefilter

import numpy as np
import numpy.typing as npt

from vision_app.contracts.models import (
    BoxN,
    Detection,
    DetectionBatch,
    ObservationQuality,
    PointN,
    QualityFlag,
    ResourceId,
    SourceTimeMs,
    TrackObservation,
)

from .config import ByteTrackAdapterConfig

try:
    import supervision as sv
except ModuleNotFoundError:  # pragma: no cover
    sv = None  # type: ignore[assignment]

@dataclass
class _ClassHistory:
    """Per-track class history used to keep the emitted label stable."""

    counts: Counter[str] = field(default_factory=Counter)

    def update(self, class_name: str) -> None:
        self.counts[class_name] += 1

    def mode(self) -> str:
        return self.counts.most_common(1)[0][0]


class ByteTrackSession:
    """One independent ByteTrack session tied to a single run attempt."""

    def __init__(self, attempt_id: str, config: ByteTrackAdapterConfig) -> None:
        if sv is None:  # pragma: no cover
            raise RuntimeError(
                "supervision is required for ByteTrack tracking but is not installed"
            )

        self._attempt_id = ResourceId(attempt_id)
        self._config = config
        with catch_warnings():
            simplefilter("ignore", FutureWarning)
            self._tracker = sv.ByteTrack(
                track_activation_threshold=config.track_activation_threshold,
                minimum_matching_threshold=config.minimum_matching_threshold,
                frame_rate=config.frame_rate,
                lost_track_buffer=config.lost_track_buffer,
                minimum_consecutive_frames=config.minimum_consecutive_frames,
            )
        self._last_source_time_ms: int | None = None
        self._class_history: dict[int, _ClassHistory] = {}
        self._closed = False

    def update(self, batch: DetectionBatch) -> list[TrackObservation]:
        """Advance the tracker with a new ``DetectionBatch`` in source-time order.

        Returns observed ``TrackObservation`` objects, one per activated track.  All
        returned observations have ``observed=True`` because ByteTrack only emits
        detections that were matched to an input observation.
        """
        if self._closed:
            raise RuntimeError("cannot update a closed tracker session")

        current_ms = batch.frame_ref.source_time_ms.root
        self._validate_source_time(current_ms)

        width = batch.frame_ref.width
        height = batch.frame_ref.height
        if width <= 0 or height <= 0:
            raise ValueError(f"frame dimensions must be positive: {width}x{height}")

        detections = batch.detections
        if not detections:
            # ByteTrack returns empty for empty input; no predicted-only observations.
            self._last_source_time_ms = current_ms
            return []

        sv_detections = _detections_to_sv(detections, width, height)
        tracked = self._tracker.update_with_detections(sv_detections)
        self._last_source_time_ms = current_ms
        return self._to_observations(tracked, detections, batch, width, height)

    def _validate_source_time(self, current_ms: int) -> None:
        if self._last_source_time_ms is None:
            return
        if current_ms < self._last_source_time_ms:
            raise ValueError(
                f"source time is out of order: {current_ms} < {self._last_source_time_ms}"
            )
        gap_ms = current_ms - self._last_source_time_ms
        if gap_ms > self._config.max_gap_ms:
            self.reset()

    def _to_observations(
        self,
        tracked: "sv.Detections",
        source_detections: list[Detection],
        batch: DetectionBatch,
        width: int,
        height: int,
    ) -> list[TrackObservation]:
        observations: list[TrackObservation] = []
        assert tracked.tracker_id is not None
        for i in range(len(tracked)):
            tracker_id = int(tracked.tracker_id[i])
            source_detection = source_detections[i]
            history = self._class_history.setdefault(tracker_id, _ClassHistory())
            history.update(source_detection.class_name)
            emitted_class = history.mode()

            reasons: list[str] = []
            if len(history.counts) > 1:
                history_classes = ", ".join(sorted(history.counts))
                reasons.append(
                    f"class_fluctuation: emitted {emitted_class}, "
                    f"detected {source_detection.class_name}, "
                    f"history includes ({history_classes})"
                )

            box_norm = _box_from_pixels(tracked.xyxy[i], width, height)
            anchor = PointN(
                x=(box_norm.x1 + box_norm.x2) / 2.0,
                y=box_norm.y2,
            )

            flags: set[QualityFlag] = set()
            area = (box_norm.x2 - box_norm.x1) * (box_norm.y2 - box_norm.y1)
            if area < self._config.min_box_area:
                flags.add(QualityFlag.TINY_ROI)
                reasons.append(f"tiny_roi: area {area:.6f}")

            observations.append(
                TrackObservation(
                    frame_ref=batch.frame_ref,
                    attempt_id=self._attempt_id,
                    track_id=str(tracker_id),
                    observed=True,
                    box=box_norm,
                    anchor=anchor,
                    last_observed_ms=SourceTimeMs(batch.frame_ref.source_time_ms.root),
                    quality=ObservationQuality(flags=flags, reasons=reasons),
                )
            )
        return observations

    def reset(self) -> None:
        """Reset the tracker and all per-attempt state."""
        self._tracker.reset()
        self._last_source_time_ms = None
        self._class_history.clear()

    def close(self) -> None:
        """Release the tracker and mark the session closed."""
        if not self._closed:
            self.reset()
            self._closed = True


class ByteTrackFactory:
    """Factory producing independent :class:`ByteTrackSession` instances per attempt."""

    def __init__(self, config: ByteTrackAdapterConfig | None = None) -> None:
        self._config = config or ByteTrackAdapterConfig()

    def create(self, attempt_id: str) -> ByteTrackSession:
        return ByteTrackSession(attempt_id=attempt_id, config=self._config)


def _detections_to_sv(
    detections: list[Detection],
    width: int,
    height: int,
) -> "sv.Detections":
    """Convert C0 ``Detection`` objects to supervision ``Detections``.

    All detections are fed with ``class_id=0`` so that ByteTrack matches by geometry
    only; the adapter maintains its own class history per track.
    """
    count = len(detections)
    xyxy = np.zeros((count, 4), dtype=np.float32)
    confidence = np.zeros(count, dtype=np.float32)
    class_id = np.zeros(count, dtype=np.int64)

    for i, det in enumerate(detections):
        b = det.box
        xyxy[i] = [
            b.x1 * width,
            b.y1 * height,
            b.x2 * width,
            b.y2 * height,
        ]
        confidence[i] = det.score
        # class_id is intentionally uniform; class stability is handled by the adapter.
        class_id[i] = 0

    return sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)


def _box_from_pixels(
    xyxy: npt.NDArray[np.float32],
    width: int,
    height: int,
) -> BoxN:
    """Convert pixel-space ``[x1, y1, x2, y2]`` back to normalized ``BoxN``."""
    x1, y1, x2, y2 = xyxy
    return BoxN(
        x1=_clip_coord(float(x1) / width),
        y1=_clip_coord(float(y1) / height),
        x2=_clip_coord(float(x2) / width),
        y2=_clip_coord(float(y2) / height),
    )


def _clip_coord(value: float) -> float:
    return max(0.0, min(1.0, value))
