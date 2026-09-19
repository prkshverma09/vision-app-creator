"""Rule-specific configuration beyond the C0 TrackedRule contract."""
from __future__ import annotations

from dataclasses import dataclass

from vision_app.contracts.models import PointN

from .anchor import AnchorPolicy


@dataclass(frozen=True, slots=True)
class LineRuleConfig:
    rule_id: str
    capability_id: str
    object_classes: tuple[str, ...]
    line: tuple[PointN, PointN]
    anchor_policy: AnchorPolicy = AnchorPolicy.BOTTOM_LEFT
    band_width: float = 0.01
    max_gap_ms: int = 500
    valid_from_side: int = -1
    valid_to_side: int = 1
    margin_ms: int = 100


@dataclass(frozen=True, slots=True)
class ZoneRuleConfig:
    rule_id: str
    capability_id: str
    object_classes: tuple[str, ...]
    polygon: tuple[PointN, ...]
    max_gap_ms: int = 500
    merge_gap_ms: int = 0
