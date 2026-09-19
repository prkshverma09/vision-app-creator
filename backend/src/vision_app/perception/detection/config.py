"""Detector configuration shaped for a pinned RF-DETR checkpoint."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping


@dataclass(frozen=True)
class DetectorConfig:
    """RF-DETR-shaped detector settings.

    The defaults match the COCO class IDs produced by RF-DETR and the common
    object vocabulary required by the tracked-rules capabilities.  The adapter
    itself does not depend on the real RF-DETR/torch packages; those are only
    needed by the concrete backend selected at composition time.
    """

    provider: Literal["rfdetr"] = "rfdetr"
    model_name: str = "rfdetr-small"
    checkpoint_path: str | None = None
    checkpoint_revision: str = "pin-not-set"
    device: Literal["cpu", "cuda"] = "cpu"
    input_format: Literal["rgb", "bgr"] = "rgb"
    input_size: tuple[int, int] | None = None
    score_threshold: float = 0.0
    strict_boxes: bool = True
    class_map: Mapping[int, str] = field(
        default_factory=lambda: {
            1: "person",
            2: "car",
            3: "motorcycle",
            4: "bus",
            6: "truck",
        }
    )
    allowed_classes: frozenset[str] | None = None
