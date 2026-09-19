"""Shared test fixtures and helpers for the rules component suite."""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from vision_app.contracts.models import (
    BoxN,
    FrameRef,
    ObservationQuality,
    PointN,
    QualityFlag,
    ResourceId,
    SignalInterval,
    SourceTimeMs,
    TimeRange,
    TrackObservation,
)


def frame_ref(time_ms: int, sequence: int) -> FrameRef:
    return FrameRef(
        source_id=ResourceId("source-1"),
        source_hash="a" * 64,
        pts=time_ms,
        time_base_num=1,
        time_base_den=1000,
        source_time_ms=SourceTimeMs(time_ms),
        sequence=sequence,
        width=320,
        height=240,
        transform_id=ResourceId("tfm-1"),
    )


def box_from_px(box_px: Sequence[int], width: int = 320, height: int = 240) -> BoxN:
    x1, y1, x2, y2 = box_px
    return BoxN(
        x1=x1 / width,
        y1=y1 / height,
        x2=x2 / width,
        y2=y2 / height,
    )


def red_interval(start_ms: int, end_ms: int) -> SignalInterval:
    return SignalInterval(
        state="red",
        confirmed_range=TimeRange(
            start_ms=SourceTimeMs(start_ms), end_ms=SourceTimeMs(end_ms)
        ),
        start_uncertainty=None,
        end_uncertainty=None,
        gaps=[],
    )


def track_observation(
    track_id: str,
    time_ms: int,
    sequence: int,
    box_px: Sequence[int],
    observed: bool = True,
    predicted_only: bool = False,
) -> TrackObservation:
    flags: set[QualityFlag] = set()
    if predicted_only:
        flags.add(QualityFlag.PREDICTED_ONLY)
    return TrackObservation(
        frame_ref=frame_ref(time_ms, sequence),
        attempt_id=ResourceId("attempt-1"),
        track_id=track_id,
        observed=observed,
        box=box_from_px(box_px),
        anchor=PointN(
            x=(box_px[0] + box_px[2]) / 2 / 320,
            y=box_px[3] / 240,
        ),
        last_observed_ms=SourceTimeMs(time_ms),
        quality=ObservationQuality(flags=flags, reasons=[]),
    )


def signal_observations_from_annotation(
    annotation: dict[str, Any],
) -> list[tuple[int, str]]:
    return [(f["source_time_ms"], f["signal_state"]) for f in annotation["frames"]]


def build_red_intervals(
    per_frame: Sequence[tuple[int, str]],
) -> list[SignalInterval]:
    """Convert per-frame signal states into confirmed red intervals."""
    intervals: list[tuple[int, int]] = []
    start: int | None = None
    for time_ms, state in per_frame:
        if state == "red" and start is None:
            start = time_ms
        if state != "red" and start is not None:
            intervals.append((start, time_ms))
            start = None
    if start is not None:
        intervals.append((start, per_frame[-1][0] + 100))
    return [
        SignalInterval(
            state="red",
            confirmed_range=TimeRange(
                start_ms=SourceTimeMs(s), end_ms=SourceTimeMs(e)
            ),
            start_uncertainty=None,
            end_uncertainty=None,
            gaps=[],
        )
        for s, e in intervals
    ]


def load_annotation(name: str) -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[4]
        / "fixtures"
        / "synthetic"
        / "annotations"
        / f"{name}.json"
    )
    return json.loads(path.read_text())


def observations_from_annotation(annotation: dict[str, Any]) -> list[TrackObservation]:
    obs: list[TrackObservation] = []
    for frame in annotation["frames"]:
        for box in frame.get("boxes", []):
            obs.append(
                track_observation(
                    track_id=box["track_id"],
                    time_ms=frame["source_time_ms"],
                    sequence=frame["frame"],
                    box_px=box["box_px"],
                )
            )
    return sorted(obs, key=lambda o: o.frame_ref.source_time_ms.root)
