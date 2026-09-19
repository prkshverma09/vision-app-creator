"""Direction, orientation, and signed-distance helpers for sequential points."""
from __future__ import annotations

from collections.abc import Sequence
from math import atan2, sqrt

from vision_app.contracts.models import PointN


def signed_area(polygon: Sequence[PointN]) -> float:
    """Shoelace signed area. Positive for counter-clockwise vertices."""
    vertices = list(polygon)
    if len(vertices) < 3:
        raise ValueError("polygon must have at least three vertices")
    total = 0.0
    n = len(vertices)
    for i in range(n):
        j = (i + 1) % n
        total += vertices[i].x * vertices[j].y - vertices[j].x * vertices[i].y
    return total / 2.0


def polygon_is_clockwise(polygon: Sequence[PointN]) -> bool:
    """True if the polygon vertices are ordered clockwise."""
    return signed_area(polygon) < 0


def heading(p1: PointN, p2: PointN) -> float:
    """Angle of the vector ``p2 - p1`` in radians, measured from the x-axis."""
    return atan2(p2.y - p1.y, p2.x - p1.x)


def direction_from_points(points: Sequence[PointN]) -> tuple[float, float]:
    """Unit direction vector from the first to the last point in ``points``."""
    sequence = list(points)
    if len(sequence) < 2:
        raise ValueError("need at least two points to determine direction")
    dx = sequence[-1].x - sequence[0].x
    dy = sequence[-1].y - sequence[0].y
    norm = sqrt(dx * dx + dy * dy)
    if norm == 0:
        raise ValueError("first and last points are identical")
    return (dx / norm, dy / norm)


def signed_distance_to_line(
    point: PointN,
    line_p1: PointN,
    line_p2: PointN,
) -> float:
    """Signed perpendicular distance from ``point`` to the infinite line through
    ``line_p1`` and ``line_p2``. Positive when the point is to the left of the
    directed line ``line_p1 -> line_p2``.
    """
    dx = line_p2.x - line_p1.x
    dy = line_p2.y - line_p1.y
    cross = dx * (point.y - line_p1.y) - dy * (point.x - line_p1.x)
    length = sqrt(dx * dx + dy * dy)
    if length == 0:
        raise ValueError("line endpoints must be distinct")
    return cross / length
