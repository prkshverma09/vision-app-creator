"""Media probe/extraction value types and P0 resource limits."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MediaLimits:
    """P0 guardrails from DESIGN.md: reject rather than silently transform."""

    max_bytes: int = 250_000_000
    max_duration_ms: int = 300_000
    max_pixels: int = 2_073_600  # displayed pixels per frame (1920x1080)
    max_source_fps: float = 60.0
    allowed_codecs: frozenset[str] = frozenset({"h264", "mpeg4"})
    allowed_containers: frozenset[str] = field(
        default_factory=lambda: frozenset({"mov,mp4,m4a,3gp,3g2,mj2", "mp4"})
    )
    max_frames: int = 18_000  # decode frame budget (300 s at 60 fps)
    max_samples: int = 256  # bounded sampling request budget
    probe_timeout_s: float = 10.0
    decode_timeout_s: float = 60.0
    extract_timeout_s: float = 60.0


@dataclass(frozen=True)
class FrameTimestamp:
    """One decoded frame's native timing, before normalization."""

    pts: int
    time_base_num: int
    time_base_den: int
    source_time_ms: int  # normalized so the first decoded frame is 0


@dataclass(frozen=True)
class MediaProbe:
    """Container/codec metadata gathered before any frame decode."""

    codec: str
    container: str
    coded_width: int
    coded_height: int
    display_width: int
    display_height: int
    duration_ms: int
    time_base_num: int
    time_base_den: int
    rotation_degrees: int  # display rotation applied to coded frames
    frame_count: int | None
    nominal_fps: float | None
    byte_size: int
    sha256: str
    pts_origin: int  # native PTS of the first decoded frame


@dataclass(frozen=True)
class ClipResult:
    """Result of bounded clip extraction with honest seek metadata."""

    data: bytes
    requested_start_ms: int
    requested_end_ms: int
    actual_start_ms: int
    actual_end_ms: int
    clipped_start: bool  # requested start preceded the media origin
    clipped_end: bool  # requested end exceeded the media duration
    method: str  # "reencode" — approximate keyframe seeking is never claimed
