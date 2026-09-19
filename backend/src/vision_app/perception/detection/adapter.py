"""RF-DETR-shaped detector adapter implementing the :class:`Detector` port."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any

from vision_app.contracts.models import (
    BoxN,
    DecodedFrame,
    Detection,
    DetectionBatch,
    ModelInvocationMetadata,
    MoneyMicrousd,
)

from .backend import DetectorBackend, PreprocessedFrame, RawDetection
from .config import DetectorConfig
from .errors import CoordinateError, DetectionError, ShapeError
from .rfdetr_backend import RfDetrBackend

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class _RGBImage:
    width: int
    height: int
    stride: int
    data: bytes


def _bgr_to_rgb(data: bytes) -> bytes:
    """Swap BGR channel order to RGB in pure Python (test-safe)."""
    bgr = bytearray(data)
    for i in range(0, len(bgr), 3):
        bgr[i], bgr[i + 2] = bgr[i + 2], bgr[i]
    return bytes(bgr)


def _resize_nearest(data: bytes, src_w: int, src_h: int, dst_w: int, dst_h: int) -> bytes:
    """Fallback nearest-neighbor resize when PIL/numpy are unavailable.

    Not intended for production quality, but deterministic and dependency-free.
    """
    if src_w == dst_w and src_h == dst_h:
        return data
    out = bytearray(dst_w * dst_h * 3)
    for y in range(dst_h):
        src_y = min(y * src_h // dst_h, src_h - 1)
        for x in range(dst_w):
            src_x = min(x * src_w // dst_w, src_w - 1)
            src_i = (src_y * src_w + src_x) * 3
            dst_i = (y * dst_w + x) * 3
            out[dst_i : dst_i + 3] = data[src_i : src_i + 3]
    return bytes(out)


def _preprocess(frame: DecodedFrame, config: DetectorConfig) -> PreprocessedFrame:
    rgb = frame.rgb
    expected_stride = frame.frame_ref.width * 3
    if frame.stride != expected_stride:
        raise ShapeError(
            f"stride {frame.stride} does not match width*3={expected_stride}"
        )
    expected_len = frame.stride * frame.frame_ref.height
    if len(rgb) != expected_len:
        raise ShapeError(
            f"rgb buffer length {len(rgb)} != stride*height={expected_len}"
        )

    if config.input_format == "bgr":
        rgb = _bgr_to_rgb(rgb)

    width, height = frame.frame_ref.width, frame.frame_ref.height
    if config.input_size is not None:
        dst_w, dst_h = config.input_size
        if dst_w <= 0 or dst_h <= 0:
            raise ShapeError("input_size must be positive when set")
        if dst_w != width or dst_h != height:
            try:
                from PIL import Image

                img = Image.frombytes("RGB", (width, height), rgb)
                resized = img.resize((dst_w, dst_h), Image.Resampling.BILINEAR)
                rgb = resized.tobytes()
            except Exception:
                rgb = _resize_nearest(rgb, width, height, dst_w, dst_h)
            width, height = dst_w, dst_h

    return PreprocessedFrame(
        width=width, height=height, channels=3, stride=width * 3, data=rgb
    )


def _to_detection(raw: RawDetection, config: DetectorConfig) -> Detection:
    x1, y1, x2, y2 = raw.box
    for v in (x1, y1, x2, y2):
        if not isfinite(v):
            raise CoordinateError(f"non-finite box coordinate: {raw.box}")
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    x2 = max(0.0, min(1.0, x2))
    y2 = max(0.0, min(1.0, y2))
    if x1 >= x2 or y1 >= y2:
        raise CoordinateError(
            f"degenerate box after clipping: ({x1}, {y1}, {x2}, {y2})"
        )
    return Detection(
        class_name=config.class_map[raw.class_id],
        box=BoxN(x1=x1, y1=y1, x2=x2, y2=y2),
        score=max(0.0, min(1.0, raw.score)),
        model_ref=config.model_name,
    )


class RfDetrDetector:
    """Detector port adapter shaped for a pinned RF-DETR checkpoint.

    The backend is loaded lazily on the first :meth:`detect` or :meth:`warm`
    call and reused across invocations.  Component tests supply a fake backend
    so real model/torch imports are not required.
    """

    def __init__(
        self,
        config: DetectorConfig,
        backend: DetectorBackend | None = None,
        clock: Any | None = None,
    ) -> None:
        self._config = config
        self._backend = backend or RfDetrBackend(config)
        self._clock = clock or _DefaultClock()
        self._loaded = False
        self._lock = asyncio.Lock()

    def warm(self) -> None:
        if not self._loaded:
            self._backend.load()
            self._loaded = True

    async def detect(self, frame: DecodedFrame) -> DetectionBatch:
        preprocessed = _preprocess(frame, self._config)

        async with self._lock:
            if not self._loaded:
                self._backend.load()
                self._loaded = True

        started_ms = time.monotonic_ns() // 1_000_000
        try:
            # Inference is CPU/GPU-bound; run it in the default executor so the
            # event loop is not blocked by torch internals.
            loop = asyncio.get_running_loop()
            raw_detections = await loop.run_in_executor(
                None, self._backend, preprocessed, self._config
            )
        except DetectionError:
            raise
        except Exception as exc:
            raise DetectionError(f"inference failed: {exc}") from exc
        duration_ms = (time.monotonic_ns() // 1_000_000) - started_ms

        detections: list[Detection] = []
        allowed = self._config.allowed_classes
        for raw in raw_detections:
            class_name = self._config.class_map.get(raw.class_id)
            if class_name is None:
                continue
            if allowed is not None and class_name not in allowed:
                continue
            if self._config.score_threshold > 0 and raw.score < self._config.score_threshold:
                continue
            detections.append(_to_detection(raw, self._config))

        invocation = ModelInvocationMetadata(
            provider=self._config.provider,
            model=self._config.model_name,
            revision=self._config.checkpoint_revision,
            prompt_hash=_preprocessing_hash(preprocessed, self._config),
            input_tokens=0,
            output_tokens=len(detections),
            duration_ms=max(0, duration_ms),
            retry_count=0,
            adapter_mode="image",
            estimated_cost=MoneyMicrousd(0),
        )
        return DetectionBatch(
            frame_ref=frame.frame_ref,
            detections=detections,
            invocation=invocation,
        )


def _preprocessing_hash(preprocessed: PreprocessedFrame, config: DetectorConfig) -> str:
    """Deterministic hash describing the preprocessing config and input shape."""
    import hashlib

    key = f"{config.input_format}:{config.input_size}:{preprocessed.width}x{preprocessed.height}"
    return hashlib.sha256(key.encode()).hexdigest()


class _DefaultClock:
    def now(self) -> datetime:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)
