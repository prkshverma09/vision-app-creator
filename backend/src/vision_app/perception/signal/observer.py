"""Calibrated, conservative classification for a single visible signal lamp ROI.

The supported style is a fixed-camera ROI whose illuminated pixels themselves encode
red, amber, or green.  Every scene supplies its own HSV and quality thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from vision_app.contracts.models import (
    BoxN,
    DecodedFrame,
    ObservationQuality,
    QualityFlag,
    ResourceId,
    SignalObservation,
)

type SignalState = Literal["red", "amber", "green", "unknown"]
type ColorState = Literal["red", "amber", "green"]


@dataclass(frozen=True, slots=True)
class HsvRange:
    """Inclusive OpenCV HSV bounds (H: 0..179, S/V: 0..255)."""

    hue_min: int
    hue_max: int
    saturation_min: int
    saturation_max: int
    value_min: int
    value_max: int

    def __post_init__(self) -> None:
        bounds = (
            (self.hue_min, self.hue_max, 179, "hue"),
            (self.saturation_min, self.saturation_max, 255, "saturation"),
            (self.value_min, self.value_max, 255, "value"),
        )
        for lower, upper, maximum, name in bounds:
            if not 0 <= lower <= upper <= maximum:
                raise ValueError(f"invalid {name} range")


@dataclass(frozen=True, slots=True)
class LampRoiCalibration:
    """All scene-dependent thresholds needed to observe one confirmed ROI."""

    roi: BoxN
    color_ranges: dict[ColorState, tuple[HsvRange, ...]]
    minimum_color_fraction: float
    winner_margin: float
    minimum_roi_pixels: int
    maximum_glare_fraction: float
    maximum_occluded_fraction: float
    stability_ms: int
    glare_value_min: int = 245
    glare_saturation_max: int = 30
    occluded_value_max: int = 30

    def __post_init__(self) -> None:
        if set(self.color_ranges) != {"red", "amber", "green"}:
            raise ValueError("color_ranges must configure red, amber, and green")
        if any(not ranges for ranges in self.color_ranges.values()):
            raise ValueError("each signal color needs at least one HSV range")
        for name in (
            "minimum_color_fraction",
            "winner_margin",
            "maximum_glare_fraction",
            "maximum_occluded_fraction",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.minimum_roi_pixels <= 0 or self.stability_ms < 0:
            raise ValueError("pixel minimum must be positive and stability_ms nonnegative")
        if not 0 <= self.glare_value_min <= 255 or not 0 <= self.glare_saturation_max <= 255:
            raise ValueError("invalid glare thresholds")
        if not 0 <= self.occluded_value_max <= 255:
            raise ValueError("invalid occlusion threshold")


class RoiSignalObserver:
    """SignalObserver adapter backed only by NumPy/OpenCV pixel features."""

    def __init__(self, calibrations: dict[str, LampRoiCalibration]) -> None:
        if not calibrations:
            raise ValueError("at least one ROI calibration is required")
        self._calibrations = dict(calibrations)

    def observe(self, frame: DecodedFrame, roi_id: str) -> SignalObservation:
        try:
            calibration = self._calibrations[roi_id]
        except KeyError as error:
            raise KeyError(f"unconfigured signal ROI: {roi_id}") from error
        crop = self._crop(frame, calibration.roi)
        state, quality = self._classify(crop, calibration)
        return SignalObservation(
            roi_id=ResourceId(roi_id),
            source_time_ms=frame.frame_ref.source_time_ms,
            state=state,
            quality=quality,
        )

    @staticmethod
    def _crop(frame: DecodedFrame, roi: BoxN) -> NDArray[np.uint8]:
        width, height = frame.frame_ref.width, frame.frame_ref.height
        required_row_bytes = width * 3
        if frame.stride < required_row_bytes or len(frame.rgb) < frame.stride * height:
            raise ValueError("RGB frame buffer is smaller than its declared shape/stride")
        rows = np.frombuffer(frame.rgb, dtype=np.uint8, count=frame.stride * height).reshape(
            height, frame.stride
        )
        image = rows[:, :required_row_bytes].reshape(height, width, 3)
        x1 = int(np.floor(roi.x1 * width))
        y1 = int(np.floor(roi.y1 * height))
        x2 = int(np.ceil(roi.x2 * width))
        y2 = int(np.ceil(roi.y2 * height))
        return image[y1:y2, x1:x2]

    @staticmethod
    def _classify(
        crop: NDArray[np.uint8], calibration: LampRoiCalibration
    ) -> tuple[SignalState, ObservationQuality]:
        pixel_count = int(crop.shape[0] * crop.shape[1])
        if pixel_count < calibration.minimum_roi_pixels:
            return "unknown", ObservationQuality(
                flags={QualityFlag.TINY_ROI}, reasons=["tiny_roi"]
            )

        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        glare_fraction = float(
            np.mean(
                (hsv[:, :, 2] >= calibration.glare_value_min)
                & (hsv[:, :, 1] <= calibration.glare_saturation_max)
            )
        )
        if glare_fraction >= calibration.maximum_glare_fraction:
            return "unknown", ObservationQuality(reasons=["glare"])

        occluded_fraction = float(np.mean(hsv[:, :, 2] <= calibration.occluded_value_max))
        if occluded_fraction >= calibration.maximum_occluded_fraction:
            return "unknown", ObservationQuality(
                flags={QualityFlag.OCCLUDED}, reasons=["occluded"]
            )

        fractions: dict[ColorState, float] = {}
        for state, ranges in calibration.color_ranges.items():
            matched = np.zeros(hsv.shape[:2], dtype=np.bool_)
            for hsv_range in ranges:
                lower = np.array(
                    [hsv_range.hue_min, hsv_range.saturation_min, hsv_range.value_min],
                    dtype=np.uint8,
                )
                upper = np.array(
                    [hsv_range.hue_max, hsv_range.saturation_max, hsv_range.value_max],
                    dtype=np.uint8,
                )
                matched |= cv2.inRange(hsv, lower, upper).astype(bool)
            fractions[state] = float(np.mean(matched))

        ranked = sorted(fractions.items(), key=lambda item: item[1], reverse=True)
        (winner, winner_fraction), (_, runner_up_fraction) = ranked[:2]
        if (
            winner_fraction < calibration.minimum_color_fraction
            or winner_fraction - runner_up_fraction < calibration.winner_margin
        ):
            return "unknown", ObservationQuality(reasons=["ambiguous_color"])
        return winner, ObservationQuality()
