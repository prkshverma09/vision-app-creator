"""Bounded, local-only FFmpeg video probing, decoding, sampling, and extraction."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from collections.abc import Generator
from typing import Any, cast

import cv2
import numpy as np

from vision_app.contracts.models import DecodedFrame, FrameRef, ResourceId, SourceTimeMs

from .errors import (
    DecodeError,
    DecoderUnavailableError,
    DecodeTimeoutError,
    EndOfMediaError,
    InvalidMediaError,
    OversizedMediaError,
    UnsupportedMediaError,
)
from .types import ClipResult, FrameTimestamp, MediaLimits, MediaProbe


class LocalVideoDecoder:
    """Decode staged local files only, with P0 limits and source PTS semantics."""

    def __init__(self, limits: MediaLimits | None = None) -> None:
        self.limits = limits or MediaLimits()
        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")

    def _local_file(self, value: str | os.PathLike[str]) -> Path:
        raw = os.fspath(value)
        if "://" in raw or raw.startswith(("pipe:", "fd:", "concat:")):
            raise InvalidMediaError("only local filesystem video inputs are accepted")
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise InvalidMediaError("media file does not exist or is not a regular file")
        return path

    def _require_tools(self) -> tuple[str, str]:
        if not self._ffmpeg or not self._ffprobe:
            raise DecoderUnavailableError("ffmpeg and ffprobe are required")
        return self._ffmpeg, self._ffprobe

    def _run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise DecodeTimeoutError(f"decoder command exceeded {timeout:g}s") from exc
        except OSError as exc:
            raise DecoderUnavailableError("unable to execute FFmpeg tools") from exc

    def _probe_json(self, path: Path, *, frames: bool = False) -> dict[str, Any]:
        _, ffprobe = self._require_tools()
        entries = ["-show_frames", "-show_entries", "frame=best_effort_timestamp,pkt_duration"] if frames else ["-show_streams", "-show_format"]
        result = self._run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", *entries, "-of", "json", str(path)],
            self.limits.decode_timeout_s if frames else self.limits.probe_timeout_s,
        )
        if result.returncode:
            raise InvalidMediaError(result.stderr.decode("utf-8", "replace").strip() or "ffprobe rejected media")
        try:
            return cast(dict[str, Any], json.loads(result.stdout))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidMediaError("ffprobe returned malformed metadata") from exc

    @staticmethod
    def _fraction(value: str) -> Fraction:
        try:
            fraction = Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise InvalidMediaError(f"invalid rational metadata: {value!r}") from exc
        if fraction <= 0:
            raise InvalidMediaError("media time base must be positive")
        return fraction

    @staticmethod
    def _rotation(stream: dict[str, Any]) -> int:
        rotation = int(stream.get("tags", {}).get("rotate", 0))
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = int(round(float(side_data["rotation"])))
        return rotation % 360

    def probe(self, source: str | os.PathLike[str]) -> MediaProbe:
        path = self._local_file(source)
        byte_size = path.stat().st_size
        if byte_size > self.limits.max_bytes:
            raise OversizedMediaError("media exceeds byte limit")
        data = self._probe_json(path)
        streams = data.get("streams", [])
        if not streams:
            raise InvalidMediaError("media has no video stream")
        stream = streams[0]
        codec = str(stream.get("codec_name", ""))
        container = str(data.get("format", {}).get("format_name", ""))
        if codec not in self.limits.allowed_codecs:
            raise UnsupportedMediaError(f"unsupported video codec: {codec or 'unknown'}")
        if container not in self.limits.allowed_containers:
            raise UnsupportedMediaError(f"unsupported container: {container or 'unknown'}")
        width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
        if width <= 0 or height <= 0:
            raise InvalidMediaError("invalid video dimensions")
        rotation = self._rotation(stream)
        display_width, display_height = ((height, width) if rotation in {90, 270} else (width, height))
        if display_width * display_height > self.limits.max_pixels:
            raise OversizedMediaError("media exceeds decoded pixel limit")
        duration_text = stream.get("duration") or data.get("format", {}).get("duration")
        if duration_text is None:
            raise InvalidMediaError("media duration is unavailable")
        duration_ms = int(round(float(duration_text) * 1000))
        if duration_ms <= 0:
            raise InvalidMediaError("media duration must be positive")
        if duration_ms > self.limits.max_duration_ms:
            raise OversizedMediaError("media exceeds duration limit")
        time_base = self._fraction(str(stream.get("time_base", "")))
        rate_text = str(stream.get("avg_frame_rate", "0/1"))
        rate = float(Fraction(rate_text)) if rate_text != "0/0" else 0.0
        if rate > self.limits.max_source_fps:
            raise UnsupportedMediaError("nominal frame rate exceeds supported limit")
        frame_count_text = stream.get("nb_frames")
        frame_count = int(frame_count_text) if frame_count_text not in (None, "N/A") else None
        if frame_count is not None and frame_count > self.limits.max_frames:
            raise OversizedMediaError("media exceeds frame limit")
        timing = self._timestamps(path, time_base, enforce_probe=False)
        if not timing:
            raise DecodeError("video contains no decodable frame timestamps")
        return MediaProbe(
            codec=codec, container=container, coded_width=width, coded_height=height,
            display_width=display_width, display_height=display_height, duration_ms=duration_ms,
            time_base_num=time_base.numerator, time_base_den=time_base.denominator,
            rotation_degrees=rotation, frame_count=frame_count, nominal_fps=rate or None,
            byte_size=byte_size, sha256=self._sha256(path), pts_origin=timing[0].pts,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _timestamps(self, path: Path, time_base: Fraction, *, enforce_probe: bool = True) -> list[FrameTimestamp]:
        if enforce_probe:
            self.probe(path)
        frames = self._probe_json(path, frames=True).get("frames", [])
        if len(frames) > self.limits.max_frames:
            raise OversizedMediaError("decoded frame metadata exceeds frame limit")
        pts_values: list[int] = []
        for frame in frames:
            value = frame.get("best_effort_timestamp")
            if value not in (None, "N/A"):
                pts_values.append(int(value))
        if not pts_values:
            return []
        origin = pts_values[0]
        result = []
        previous = -1
        for pts in pts_values:
            delta = (pts - origin) * time_base
            source_ms = (delta.numerator * 1000 + delta.denominator // 2) // delta.denominator
            if source_ms < previous:
                raise DecodeError("non-monotonic source timestamps")
            previous = source_ms
            result.append(FrameTimestamp(pts, time_base.numerator, time_base.denominator, source_ms))
        return result

    @staticmethod
    def _rotate(rgb: np.ndarray[Any, Any], degrees: int) -> np.ndarray[Any, Any]:
        if degrees == 90:
            return cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE)
        if degrees == 180:
            return cv2.rotate(rgb, cv2.ROTATE_180)
        if degrees == 270:
            return cv2.rotate(rgb, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return rgb

    def decode(self, source: str | os.PathLike[str]) -> Generator[DecodedFrame, None, None]:
        """Yield one frame at a time so decoded image memory stays bounded."""
        path = self._local_file(source)
        probe = self.probe(path)
        timestamps = self._timestamps(path, Fraction(probe.time_base_num, probe.time_base_den), enforce_probe=False)
        ffmpeg, _ = self._require_tools()
        command = [ffmpeg, "-v", "error", "-noautorotate", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise DecoderUnavailableError("unable to execute ffmpeg") from exc
        frame_size = probe.coded_width * probe.coded_height * 3
        started = time.monotonic()
        try:
            assert process.stdout is not None
            for sequence, timestamp in enumerate(timestamps):
                if time.monotonic() - started > self.limits.decode_timeout_s:
                    raise DecodeTimeoutError("video decode exceeded deadline")
                raw = process.stdout.read(frame_size)
                if len(raw) != frame_size:
                    raise DecodeError("unexpected EOF while decoding video")
                image = np.frombuffer(raw, dtype=np.uint8).reshape((probe.coded_height, probe.coded_width, 3))
                image = np.ascontiguousarray(self._rotate(image, probe.rotation_degrees))
                ref = FrameRef(
                    source_id=ResourceId(root=path.name), source_hash=probe.sha256,
                    pts=timestamp.pts, time_base_num=timestamp.time_base_num,
                    time_base_den=timestamp.time_base_den, source_time_ms=SourceTimeMs(root=timestamp.source_time_ms),
                    sequence=sequence, width=probe.display_width, height=probe.display_height,
                    transform_id=ResourceId(root=f"rotation-{probe.rotation_degrees}"),
                )
                yield DecodedFrame(frame_ref=ref, rgb=image.tobytes(), stride=probe.display_width * 3)
            process.stdout.close()
            return_code = process.wait(timeout=max(0.001, self.limits.decode_timeout_s - (time.monotonic() - started)))
            if return_code:
                raise DecodeError("ffmpeg failed while decoding video")
        except subprocess.TimeoutExpired as exc:
            raise DecodeTimeoutError("video decode exceeded deadline") from exc
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def sample(self, source: str | os.PathLike[str], times_ms: list[int]) -> list[DecodedFrame]:
        if len(times_ms) > self.limits.max_samples:
            raise OversizedMediaError("sample request exceeds sample limit")
        if any(value < 0 for value in times_ms):
            raise InvalidMediaError("sample times must be nonnegative")
        probe = self.probe(source)
        if any(value >= probe.duration_ms for value in times_ms):
            raise EndOfMediaError("sample time is at or past end of media")
        ordered = sorted(enumerate(times_ms), key=lambda item: item[1])
        selected: list[DecodedFrame | None] = [None] * len(times_ms)
        frames = self.decode(source)
        try:
            last_frame: DecodedFrame | None = None
            for original_index, target in ordered:
                match: DecodedFrame | None = None
                for frame in frames:
                    last_frame = frame
                    if frame.frame_ref.source_time_ms.root >= target:
                        match = frame
                        break
                if match is None:
                    # The target is inside the media duration but beyond the
                    # last decodable frame's PTS; clamp to the final frame.
                    match = last_frame
                if match is None:
                    raise EndOfMediaError("no decoded frame exists at requested source time")
                selected[original_index] = match
        finally:
            frames.close()
        return [frame for frame in selected if frame is not None]

    def scene_samples(self, source: str | os.PathLike[str], *, count: int = 5) -> list[DecodedFrame]:
        if count <= 0 or count > self.limits.max_samples:
            raise OversizedMediaError("scene sample count is outside bounds")
        duration = self.probe(source).duration_ms
        times = [((index + 1) * duration) // (count + 1) for index in range(count)]
        return self.sample(source, times)

    def extract_clip(self, source: str | os.PathLike[str], start_ms: int, end_ms: int) -> ClipResult:
        path = self._local_file(source)
        if start_ms >= end_ms:
            raise InvalidMediaError("clip range must have positive duration")
        probe = self.probe(path)
        actual_start, actual_end = max(0, start_ms), min(probe.duration_ms, end_ms)
        if actual_start >= probe.duration_ms or actual_end <= 0 or actual_start >= actual_end:
            raise EndOfMediaError("clip range lies outside media")
        ffmpeg, _ = self._require_tools()
        result = self._run([
            ffmpeg, "-v", "error", "-i", str(path), "-ss", f"{actual_start / 1000:.6f}",
            "-t", f"{(actual_end - actual_start) / 1000:.6f}", "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-map_metadata", "-1",
            "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1",
        ], self.limits.extract_timeout_s)
        if result.returncode or not result.stdout:
            raise DecodeError(result.stderr.decode("utf-8", "replace").strip() or "clip extraction failed")
        if len(result.stdout) > self.limits.max_bytes:
            raise OversizedMediaError("extracted clip exceeds byte limit")
        return ClipResult(
            data=result.stdout, requested_start_ms=start_ms, requested_end_ms=end_ms,
            actual_start_ms=actual_start, actual_end_ms=actual_end,
            clipped_start=start_ms < 0, clipped_end=end_ms > probe.duration_ms, method="reencode",
        )
