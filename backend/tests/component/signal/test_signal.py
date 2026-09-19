from __future__ import annotations

import numpy as np
import pytest
from vision_app.contracts.models import (
    BoxN,
    DecodedFrame,
    FrameRef,
    QualityFlag,
    ResourceId,
    SourceTimeMs,
)
from vision_app.perception.signal import (
    ConfirmedSignalIntervals,
    HsvRange,
    LampRoiCalibration,
    RoiSignalObserver,
)


def calibration(*, stability_ms: int = 200, roi: BoxN | None = None) -> LampRoiCalibration:
    return LampRoiCalibration(
        roi=roi or BoxN(x1=0.0, y1=0.0, x2=1.0, y2=1.0),
        color_ranges={
            "red": (HsvRange(170, 179, 120, 255, 100, 255), HsvRange(0, 10, 120, 255, 100, 255)),
            "amber": (HsvRange(11, 30, 120, 255, 100, 255),),
            "green": (HsvRange(40, 90, 120, 255, 100, 255),),
        },
        minimum_color_fraction=0.60,
        winner_margin=0.20,
        minimum_roi_pixels=64,
        maximum_glare_fraction=0.25,
        maximum_occluded_fraction=0.70,
        stability_ms=stability_ms,
    )


def frame(rgb: np.ndarray, time_ms: int = 0) -> DecodedFrame:
    height, width, _ = rgb.shape
    contiguous = np.ascontiguousarray(rgb, dtype=np.uint8)
    return DecodedFrame(
        frame_ref=FrameRef(
            source_id=ResourceId("source"),
            source_hash="0123456789abcdef",
            pts=time_ms,
            time_base_num=1,
            time_base_den=1000,
            source_time_ms=SourceTimeMs(time_ms),
            sequence=time_ms,
            width=width,
            height=height,
            transform_id=ResourceId("identity"),
        ),
        rgb=contiguous.tobytes(),
        stride=int(contiguous.strides[0]),
    )


def solid(color: tuple[int, int, int], size: int = 16) -> np.ndarray:
    return np.full((size, size, 3), color, dtype=np.uint8)


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 0, 0), "red"),
        ((255, 191, 0), "amber"),
        ((0, 255, 0), "green"),
        ((0, 0, 255), "unknown"),
    ],
)
def test_synthetic_color_classification(rgb: tuple[int, int, int], expected: str) -> None:
    observer = RoiSignalObserver({"lamp": calibration()})
    assert observer.observe(frame(solid(rgb)), "lamp").state == expected


def test_glare_is_unknown_and_identified() -> None:
    observation = RoiSignalObserver({"lamp": calibration()}).observe(
        frame(solid((255, 255, 255))), "lamp"
    )
    assert observation.state == "unknown"
    assert "glare" in observation.quality.reasons


def test_occlusion_is_unknown_and_flagged() -> None:
    observation = RoiSignalObserver({"lamp": calibration()}).observe(
        frame(solid((0, 0, 0))), "lamp"
    )
    assert observation.state == "unknown"
    assert QualityFlag.OCCLUDED in observation.quality.flags


def test_tiny_roi_is_unknown_and_flagged() -> None:
    cfg = calibration(roi=BoxN(x1=0.0, y1=0.0, x2=0.1, y2=0.1))
    observation = RoiSignalObserver({"lamp": cfg}).observe(frame(solid((255, 0, 0))), "lamp")
    assert observation.state == "unknown"
    assert QualityFlag.TINY_ROI in observation.quality.flags


def observation(state: str, time_ms: int):
    rgb = {"red": (255, 0, 0), "green": (0, 255, 0), "unknown": (0, 0, 255)}[state]
    return RoiSignalObserver({"lamp": calibration()}).observe(frame(solid(rgb), time_ms), "lamp")


def test_stability_exact_boundary_and_no_backdating() -> None:
    tracker = ConfirmedSignalIntervals(stability_ms=200)
    assert tracker.update(observation("red", 1000)).confirmed_state is None
    assert tracker.update(observation("red", 1199)).confirmed_state is None
    update = tracker.update(observation("red", 1200))
    assert update.confirmed_state == "red"
    assert update.confirmed_since_ms == 1200


def test_unknown_breaks_interval_and_red_is_not_merged() -> None:
    tracker = ConfirmedSignalIntervals(stability_ms=100)
    for state, time_ms in [("red", 0), ("red", 100), ("red", 200)]:
        tracker.update(observation(state, time_ms))
    broken = tracker.update(observation("unknown", 250))
    assert len(broken.completed_intervals) == 1
    first = broken.completed_intervals[0]
    assert first.confirmed_range.start_ms.root == 100
    assert first.confirmed_range.end_ms.root == 250
    assert tracker.update(observation("red", 300)).confirmed_state is None
    assert tracker.update(observation("red", 400)).confirmed_since_ms == 400
    done = tracker.update(observation("green", 500))
    assert len(done.completed_intervals) == 2
    starts = [interval.confirmed_range.start_ms.root for interval in done.completed_intervals]
    assert starts == [100, 400]


def test_transition_uncertainty_uses_observation_brackets() -> None:
    tracker = ConfirmedSignalIntervals(stability_ms=100)
    tracker.update(observation("green", 0))
    tracker.update(observation("green", 100))
    tracker.update(observation("green", 200))
    tracker.update(observation("red", 250))
    done = tracker.update(observation("red", 350))
    green = done.completed_intervals[0]
    assert green.end_uncertainty is not None
    uncertainty = (
        green.end_uncertainty.last_pre_ms.root,
        green.end_uncertainty.first_post_ms.root,
    )
    assert uncertainty == (200, 250)
    assert done.confirmed_since_ms == 350


def test_out_of_order_source_time_is_rejected() -> None:
    tracker = ConfirmedSignalIntervals(stability_ms=100)
    tracker.update(observation("red", 100))
    with pytest.raises(ValueError, match="source time"):
        tracker.update(observation("red", 99))
