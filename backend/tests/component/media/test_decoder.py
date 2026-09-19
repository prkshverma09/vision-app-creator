from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vision_app.media.decoder import LocalVideoDecoder
from vision_app.media.errors import (
    DecodeTimeoutError,
    EndOfMediaError,
    InvalidMediaError,
    OversizedMediaError,
    UnsupportedMediaError,
)
from vision_app.media.types import MediaLimits


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg is required for CT-MEDIA")


def _ffmpeg(target: Path, *args: str) -> None:
    subprocess.run(
        [FFMPEG or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(target)],
        check=True,
        timeout=15,
    )


@pytest.fixture
def cfr_video() -> Path:
    return Path(__file__).parents[4] / "fixtures/synthetic/video/moving_dot.mp4"


@pytest.fixture
def vfr_video(tmp_path: Path) -> Path:
    target = tmp_path / "vfr.mp4"
    _ffmpeg(
        target,
        "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=0.8",
        "-vf", "select='eq(n,0)+eq(n,1)+eq(n,3)+eq(n,6)'",
        "-fps_mode", "vfr", "-an", "-c:v", "mpeg4", "-q:v", "3",
    )
    return target


def test_vfr_decode_uses_normalized_native_pts_not_frame_index_fps(vfr_video: Path) -> None:
    decoder = LocalVideoDecoder()
    probe = decoder.probe(vfr_video)
    frames = list(decoder.decode(vfr_video))

    assert [frame.frame_ref.source_time_ms.root for frame in frames] == [0, 100, 300, 600]
    assert [frame.frame_ref.pts for frame in frames] == [0, 1024, 3072, 6144]
    assert {(frame.frame_ref.time_base_num, frame.frame_ref.time_base_den) for frame in frames} == {
        (probe.time_base_num, probe.time_base_den)
    }


def test_probe_hash_dimensions_and_bounded_source_time_samples(cfr_video: Path) -> None:
    decoder = LocalVideoDecoder()
    probe = decoder.probe(cfr_video)
    samples = decoder.sample(cfr_video, [0, 255, 4900])
    scene = decoder.scene_samples(cfr_video, count=3)

    assert probe.codec == "h264"
    assert probe.sha256 == "e8e35eec95ad44d33f601049c5350130e7152bed1b54b76f638b8d1c15000a25"
    assert (probe.display_width, probe.display_height) == (320, 240)
    assert [sample.frame_ref.source_time_ms.root for sample in samples] == [0, 300, 4900]
    assert len(scene) == 3
    assert all(len(frame.rgb) == frame.frame_ref.width * frame.frame_ref.height * 3 for frame in scene)


def test_rotation_metadata_is_applied_to_decoded_rgb(tmp_path: Path) -> None:
    base = tmp_path / "base.mp4"
    rotated = tmp_path / "rotated.mp4"
    _ffmpeg(base, "-f", "lavfi", "-i", "testsrc=size=64x48:rate=2:duration=0.5", "-c:v", "mpeg4")
    _ffmpeg(rotated, "-display_rotation", "90", "-i", str(base), "-c", "copy")

    decoder = LocalVideoDecoder()
    probe = decoder.probe(rotated)
    frames = decoder.decode(rotated)
    try:
        frame = next(frames)
    finally:
        frames.close()

    assert probe.rotation_degrees == 90
    assert (probe.display_width, probe.display_height) == (48, 64)
    assert (frame.frame_ref.width, frame.frame_ref.height, frame.stride) == (48, 64, 144)


def test_rejects_non_local_input_and_invalid_codec(tmp_path: Path) -> None:
    decoder = LocalVideoDecoder()
    with pytest.raises(InvalidMediaError):
        decoder.probe("https://example.invalid/video.mp4")

    unsupported = tmp_path / "unsupported.webm"
    _ffmpeg(unsupported, "-f", "lavfi", "-i", "color=s=32x32:d=0.2", "-c:v", "libvpx-vp9")
    with pytest.raises(UnsupportedMediaError):
        decoder.probe(unsupported)


def test_explicit_oversize_timeout_and_eof_errors(cfr_video: Path) -> None:
    with pytest.raises(OversizedMediaError):
        LocalVideoDecoder(MediaLimits(max_bytes=10)).probe(cfr_video)
    with pytest.raises(DecodeTimeoutError):
        LocalVideoDecoder(MediaLimits(probe_timeout_s=0.000001)).probe(cfr_video)
    with pytest.raises(EndOfMediaError):
        LocalVideoDecoder().sample(cfr_video, [5001])


def test_extract_clip_truncates_at_source_boundaries(cfr_video: Path, tmp_path: Path) -> None:
    result = LocalVideoDecoder().extract_clip(cfr_video, -1000, 6000)
    extracted = tmp_path / "clip.mp4"
    extracted.write_bytes(result.data)
    clip_probe = LocalVideoDecoder().probe(extracted)

    assert (result.requested_start_ms, result.requested_end_ms) == (-1000, 6000)
    assert (result.actual_start_ms, result.actual_end_ms) == (0, 5000)
    assert result.clipped_start is True
    assert result.clipped_end is True
    assert result.method == "reencode"
    assert 4900 <= clip_probe.duration_ms <= 5100
