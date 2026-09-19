"""RF-DETR-shaped detection adapter and test backend."""
from .adapter import RfDetrDetector
from .config import DetectorConfig
from .errors import CheckpointError, CoordinateError, DetectionError, ShapeError
from .fake_backend import FakeDetectorBackend
from .backend import RawDetection

__all__ = [
    "RfDetrDetector",
    "DetectorConfig",
    "RawDetection",
    "FakeDetectorBackend",
    "DetectionError",
    "ShapeError",
    "CoordinateError",
    "CheckpointError",
]
