"""Geometry helpers specific to rule evaluation."""
from __future__ import annotations

from collections.abc import Sequence

from vision_app.contracts.models import PointN
from vision_app.geometry.orientation import signed_distance_to_line


def line_side(
    anchor: PointN,
    segment: Sequence[PointN],
    band_width: float,
) -> int:
    """Return -1/0/+1 side of ``anchor`` relative to the directed segment.

    ``0`` means the anchor is within ``band_width`` of the supporting line
    (the hysteresis dead band). Positive values are to the left of the
    directed segment, negative values to the right.
    """
    seg = list(segment)
    if len(seg) != 2:
        raise ValueError("segment must have exactly two endpoints")
    distance = signed_distance_to_line(anchor, seg[0], seg[1])
    if abs(distance) <= band_width:
        return 0
    return 1 if distance > 0 else -1


def is_valid_crossing(
    pre_side: int,
    post_side: int,
    valid_from: int = -1,
    valid_to: int = 1,
) -> bool:
    """True when the transition follows the configured valid direction."""
    return pre_side == valid_from and post_side == valid_to
