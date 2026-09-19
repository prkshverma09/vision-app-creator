"""Polygon validation and point-in-polygon with explicit boundary policy."""
from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from vision_app.contracts.models import PointN

from .segments import point_on_segment


class BoundaryPolicy(StrEnum):
    INSIDE = "inside"
    OUTSIDE = "outside"


def validate_polygon(
    vertices: Sequence[PointN],
    min_area: float = 1e-12,
) -> list[PointN]:
    """Validate that ``vertices`` form a non-degenerate polygon.

    The area check uses the absolute shoelace area; ``min_area`` guards against
    nearly-collinear or tiny polygons.
    """
    polygon = list(vertices)
    if len(polygon) < 3:
        raise ValueError("polygon must have at least three vertices")

    total = 0.0
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        total += polygon[i].x * polygon[j].y - polygon[j].x * polygon[i].y

    if abs(total) <= 2 * min_area:
        raise ValueError("polygon is degenerate (zero or near-zero area)")

    return polygon


def point_in_polygon(
    point: PointN,
    vertices: Sequence[PointN],
    *,
    boundary_policy: BoundaryPolicy = BoundaryPolicy.INSIDE,
) -> bool:
    """Ray-casting point-in-polygon test with an explicit boundary policy.

    Points that lie exactly on an edge follow ``boundary_policy``: ``INSIDE``
    counts them as inside (the P0 default), ``OUTSIDE`` counts them as outside.
    """
    polygon = list(vertices)
    if len(polygon) < 3:
        raise ValueError("polygon must have at least three vertices")

    for i in range(len(polygon)):
        j = (i + 1) % len(polygon)
        if point_on_segment(point, polygon[i], polygon[j]):
            return boundary_policy == BoundaryPolicy.INSIDE

    inside = False
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        xi, yi = polygon[i].x, polygon[i].y
        xj, yj = polygon[j].x, polygon[j].y

        # Standard horizontal ray-to-the-right crossing test.
        if (yi > point.y) != (yj > point.y):
            x_intersect = xi + (point.y - yi) * (xj - xi) / (yj - yi)
            if point.x < x_intersect:
                inside = not inside

    return inside
