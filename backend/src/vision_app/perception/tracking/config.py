"""Configuration for the ByteTrack tracking adapter."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ByteTrackAdapterConfig:
    """Adapter-level knobs for ByteTrack plus source-time continuity policy.

    The underlying tracker still operates in frame counts; this adapter converts
    source-time gaps into explicit resets so that variable cadence does not silently
    fabricate continuity.
    """

    track_activation_threshold: float = 0.25
    minimum_matching_threshold: float = 0.8
    frame_rate: float = 30.0
    lost_track_buffer: int = 30
    minimum_consecutive_frames: int = 1
    max_gap_ms: float = 2000.0
    min_box_area: float = 0.0001
