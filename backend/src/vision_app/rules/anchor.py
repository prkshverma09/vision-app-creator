"""Anchor-point selection for boxes."""
from __future__ import annotations

from enum import StrEnum

from vision_app.contracts.models import BoxN, PointN


class AnchorPolicy(StrEnum):
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_LEFT = "bottom_left"
    CENTER = "center"


def box_anchor(box: BoxN, policy: AnchorPolicy = AnchorPolicy.BOTTOM_CENTER) -> PointN:
    """Return a normalized anchor point inside ``box`` according to ``policy``."""
    if policy == AnchorPolicy.BOTTOM_CENTER:
        return PointN(x=(box.x1 + box.x2) / 2.0, y=box.y2)
    if policy == AnchorPolicy.BOTTOM_LEFT:
        return PointN(x=box.x1, y=box.y2)
    if policy == AnchorPolicy.CENTER:
        return PointN(x=(box.x1 + box.x2) / 2.0, y=(box.y1 + box.y2) / 2.0)
    raise ValueError(f"unknown anchor policy: {policy}")
