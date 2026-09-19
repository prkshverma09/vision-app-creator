"""CT-DETECT: RF-DETR-shaped detector adapter with fake inference backend.

These tests exercise the adapter plumbing only; they do not require real
RF-DETR, torch, or a GPU.  Real checkpoint inference belongs to the R01
live/vision gate.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from vision_app.contracts.models import BoxN, DecodedFrame, DetectionBatch, FrameRef
from vision_app.perception.detection.adapter import RfDetrDetector
from vision_app.perception.detection.backend import RawDetection
from vision_app.perception.detection.config import DetectorConfig
from vision_app.perception.detection.errors import DetectionError, ShapeError
from vision_app.perception.detection.fake_backend import FakeDetectorBackend


UTC = timezone.utc


def _frame_ref(width: int = 320, height: int = 240) -> FrameRef:
    return FrameRef(
        source_id="source-0001",
        source_hash="a" * 64,
        pts=0,
        time_base_num=1,
        time_base_den=1000,
        source_time_ms=0,
        sequence=0,
        width=width,
        height=height,
        transform_id="transform-0001",
    )


def _rgb_bytes(width: int = 320, height: int = 240) -> bytes:
    return bytes(width * height * 3)


def _frame(width: int = 320, height: int = 240) -> DecodedFrame:
    return DecodedFrame(
        frame_ref=_frame_ref(width=width, height=height),
        rgb=_rgb_bytes(width=width, height=height),
        stride=width * 3,
    )


def _config(**overrides: object) -> DetectorConfig:
    defaults: dict[str, object] = {
        "provider": "rfdetr",
        "model_name": "rfdetr-small-fake",
        "checkpoint_path": "/dev/null/checkpoint.pth",
        "checkpoint_revision": "sha256:abcdef1234567890",
    }
    defaults.update(overrides)
    return DetectorConfig(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def clock():
    class Clock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    return Clock()


class TestInputContract:
    """RGB/channel and shape contract enforcement."""

    @pytest.mark.asyncio
    async def test_rejects_mismatched_rgb_shape(self, clock) -> None:
        backend = FakeDetectorBackend()
        detector = RfDetrDetector(_config(), backend, clock)
        frame = DecodedFrame(
            frame_ref=_frame_ref(),
            rgb=_rgb_bytes(width=100, height=100),
            stride=320 * 3,
        )
        with pytest.raises(ShapeError):
            await detector.detect(frame)

    @pytest.mark.asyncio
    async def test_rejects_short_buffer(self, clock) -> None:
        backend = FakeDetectorBackend()
        detector = RfDetrDetector(_config(), backend, clock)
        frame = DecodedFrame(
            frame_ref=_frame_ref(width=320, height=240),
            rgb=bytes(100),
            stride=320 * 3,
        )
        with pytest.raises(ShapeError):
            await detector.detect(frame)

    @pytest.mark.asyncio
    async def test_rejects_zero_dimension(self, clock) -> None:
        # The C0 FrameRef/DecodedFrame contract itself rejects zero dimensions.
        with pytest.raises(ValidationError):
            DecodedFrame(
                frame_ref=_frame_ref(width=0, height=240),
                rgb=b"",
                stride=0,
            )

    @pytest.mark.asyncio
    async def test_bgr_input_is_converted_to_rgb_when_configured(self, clock) -> None:
        width, height = 4, 3
        # A pure blue pixel in BGR order is (255, 0, 0) as RGB bytes,
        # which should become (0, 0, 255) after BGR->RGB conversion.
        bgr = bytearray(width * height * 3)
        for i in range(width * height):
            bgr[i * 3] = 255  # B
            bgr[i * 3 + 1] = 0  # G
            bgr[i * 3 + 2] = 0  # R
        captured: list[bytes] = []
        backend = FakeDetectorBackend(record_inputs=captured)
        detector = RfDetrDetector(
            _config(input_format="bgr", input_size=(width, height)),
            backend,
            clock,
        )
        frame = DecodedFrame(
            frame_ref=_frame_ref(width=width, height=height),
            rgb=bytes(bgr),
            stride=width * 3,
        )
        await detector.detect(frame)
        assert len(captured) == 1
        first_pixel = captured[0][:3]
        assert first_pixel == b"\x00\x00\xff"

    @pytest.mark.asyncio
    async def test_rgb_input_is_not_reordered(self, clock) -> None:
        width, height = 4, 3
        rgb = bytes([255, 0, 0] * (width * height))
        captured: list[bytes] = []
        backend = FakeDetectorBackend(record_inputs=captured)
        detector = RfDetrDetector(
            _config(input_format="rgb", input_size=(width, height)),
            backend,
            clock,
        )
        frame = DecodedFrame(
            frame_ref=_frame_ref(width=width, height=height),
            rgb=rgb,
            stride=width * 3,
        )
        await detector.detect(frame)
        assert captured[0][:3] == b"\xff\x00\x00"


class TestCoordinateConversion:
    """Class mapping and box conversion from model to source-normalized space."""

    @pytest.mark.asyncio
    async def test_converts_normalized_boxes_to_source_normalized(self, clock) -> None:
        raw = [
            RawDetection(class_id=2, score=0.9, box=(0.1, 0.2, 0.5, 0.7)),
        ]
        backend = FakeDetectorBackend(responses=[raw])
        detector = RfDetrDetector(_config(), backend, clock)
        batch = await detector.detect(_frame(width=320, height=240))
        assert len(batch.detections) == 1
        det = batch.detections[0]
        assert det.class_name == "car"
        assert det.box == BoxN(x1=0.1, y1=0.2, x2=0.5, y2=0.7)
        assert det.score == pytest.approx(0.9)
        assert det.model_ref == "rfdetr-small-fake"

    @pytest.mark.asyncio
    async def test_maps_class_ids_to_names(self, clock) -> None:
        raw = [
            RawDetection(class_id=1, score=0.5, box=(0.0, 0.0, 0.1, 0.1)),
            RawDetection(class_id=4, score=0.6, box=(0.1, 0.1, 0.2, 0.2)),
            RawDetection(class_id=99, score=0.7, box=(0.2, 0.2, 0.3, 0.3)),
        ]
        backend = FakeDetectorBackend(responses=[raw])
        detector = RfDetrDetector(_config(), backend, clock)
        batch = await detector.detect(_frame())
        names = {d.class_name for d in batch.detections}
        assert names == {"person", "bus"}

    @pytest.mark.asyncio
    async def test_filters_unknown_classes(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[RawDetection(class_id=99, score=0.8, box=(0.1, 0.1, 0.2, 0.2))]])
        detector = RfDetrDetector(_config(), backend, clock)
        batch = await detector.detect(_frame())
        assert batch.detections == []

    @pytest.mark.asyncio
    async def test_clips_out_of_bounds_boxes(self, clock) -> None:
        raw = [RawDetection(class_id=1, score=0.8, box=(-0.1, -0.2, 1.1, 1.05))]
        backend = FakeDetectorBackend(responses=[raw])
        detector = RfDetrDetector(_config(), backend, clock)
        batch = await detector.detect(_frame())
        assert batch.detections[0].box == BoxN(x1=0.0, y1=0.0, x2=1.0, y2=1.0)

    @pytest.mark.asyncio
    async def test_rejects_non_finite_boxes(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[RawDetection(class_id=1, score=0.8, box=(float("nan"), 0.0, 0.5, 0.5))]])
        detector = RfDetrDetector(_config(), backend, clock)
        with pytest.raises(DetectionError):
            await detector.detect(_frame())

    @pytest.mark.asyncio
    async def test_rejects_zero_area_boxes(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[RawDetection(class_id=1, score=0.8, box=(0.5, 0.5, 0.5, 0.9))]])
        detector = RfDetrDetector(_config(), backend, clock)
        with pytest.raises(DetectionError):
            await detector.detect(_frame())


class TestThresholdAndEmpty:
    """Low-confidence policy, empty detections, and inference failure separation."""

    @pytest.mark.asyncio
    async def test_keeps_low_confidence_for_tracker(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[RawDetection(class_id=2, score=0.05, box=(0.1, 0.1, 0.2, 0.2))]])
        detector = RfDetrDetector(_config(score_threshold=0.0), backend, clock)
        batch = await detector.detect(_frame())
        assert len(batch.detections) == 1
        assert batch.detections[0].score == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_empty_detection_batch_is_valid(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[]])
        detector = RfDetrDetector(_config(), backend, clock)
        batch = await detector.detect(_frame())
        assert isinstance(batch, DetectionBatch)
        assert batch.detections == []
        assert str(batch.frame_ref.source_id.root) == "source-0001"

    @pytest.mark.asyncio
    async def test_inference_failure_is_distinct_from_empty(self, clock) -> None:
        backend = FakeDetectorBackend(raises=DetectionError("simulated failure"))
        detector = RfDetrDetector(_config(), backend, clock)
        with pytest.raises(DetectionError, match="simulated failure"):
            await detector.detect(_frame())


class TestInvocationMetadata:
    """Invocation metadata and warm-reuse/load-once behavior."""

    @pytest.mark.asyncio
    async def test_records_invocation_metadata(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[RawDetection(class_id=2, score=0.9, box=(0.1, 0.2, 0.5, 0.7))]])
        detector = RfDetrDetector(_config(model_name="rfdetr-small", checkpoint_revision="rev-1"), backend, clock)
        batch = await detector.detect(_frame())
        assert batch.invocation is not None
        assert batch.invocation.provider == "rfdetr"
        assert batch.invocation.model == "rfdetr-small"
        assert batch.invocation.revision == "rev-1"
        assert batch.invocation.adapter_mode == "image"
        assert batch.invocation.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_loads_backend_only_once(self, clock) -> None:
        backend = FakeDetectorBackend(responses=[[], [RawDetection(class_id=1, score=0.5, box=(0.1, 0.1, 0.2, 0.2))]])
        detector = RfDetrDetector(_config(), backend, clock)
        await detector.detect(_frame())
        await detector.detect(_frame())
        assert backend.load_count == 1

    @pytest.mark.asyncio
    async def test_warm_reuse_calls_load_once(self, clock) -> None:
        backend = FakeDetectorBackend()
        detector = RfDetrDetector(_config(), backend, clock)
        detector.warm()
        detector.warm()
        assert backend.load_count == 1


class TestAllowedClasses:
    """Class filtering configured by the app spec / calibration."""

    @pytest.mark.asyncio
    async def test_allowed_classes_restricts_output(self, clock) -> None:
        raw = [
            RawDetection(class_id=2, score=0.9, box=(0.1, 0.1, 0.2, 0.2)),  # car
            RawDetection(class_id=4, score=0.8, box=(0.3, 0.3, 0.4, 0.4)),  # bus
        ]
        backend = FakeDetectorBackend(responses=[raw])
        detector = RfDetrDetector(_config(allowed_classes=frozenset({"car"})), backend, clock)
        batch = await detector.detect(_frame())
        assert [d.class_name for d in batch.detections] == ["car"]
