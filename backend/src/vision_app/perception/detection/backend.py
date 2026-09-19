"""Backend port for a concrete detector inference implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import DetectorConfig


@dataclass(frozen=True)
class RawDetection:
    """One backend-agnostic detection before class mapping and clipping."""

    class_id: int
    score: float
    box: tuple[float, float, float, float]
    """x1, y1, x2, y2 in source-normalized [0,1] coordinates."""


@dataclass(frozen=True)
class PreprocessedFrame:
    """RGB buffer plus canonical shape metadata passed to the backend."""

    width: int
    height: int
    channels: int
    stride: int
    data: bytes


@runtime_checkable
class DetectorBackend(Protocol):
    """Pluggable inference backend used by :class:`RfDetrDetector`."""

    def load(self) -> None: ...
    def __call__(self, frame: PreprocessedFrame, config: DetectorConfig) -> list[RawDetection]: ...
