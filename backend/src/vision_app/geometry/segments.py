"""Finite line-segment intersection and trajectory crossing detection."""
from __future__ import annotations

from collections.abc import Sequence

from vision_app.contracts.models import PointN

_TOLERANCE = 1e-9


def orientation(p: PointN, q: PointN, r: PointN, tolerance: float = _TOLERANCE) -> int:
    """Orientation of ordered triplet ``(p, q, r)``.

    Returns ``1`` for counter-clockwise, ``-1`` for clockwise, and ``0`` for
    collinear (within ``tolerance``).
    """
    value = (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)
    if abs(value) <= tolerance:
        return 0
    return 1 if value > 0 else -1


def point_on_segment(
    p: PointN, a: PointN, b: PointN, tolerance: float = _TOLERANCE
) -> bool:
    """Whether collinear ``p`` lies on the closed segment ``a-b``."""
    if orientation(p, a, b, tolerance=tolerance) != 0:
        return False
    return (
        min(a.x, b.x) - tolerance <= p.x <= max(a.x, b.x) + tolerance
        and min(a.y, b.y) - tolerance <= p.y <= max(a.y, b.y) + tolerance
    )


def segments_intersect(
    a1: PointN, a2: PointN, b1: PointN, b2: PointN, tolerance: float = _TOLERANCE
) -> bool:
    """True iff the closed finite segments ``a1-a2`` and ``b1-b2`` intersect."""
    o1 = orientation(a1, a2, b1, tolerance=tolerance)
    o2 = orientation(a1, a2, b2, tolerance=tolerance)
    o3 = orientation(b1, b2, a1, tolerance=tolerance)
    o4 = orientation(b1, b2, a2, tolerance=tolerance)

    if o1 * o2 < 0 and o3 * o4 < 0:
        return True

    if o1 == 0 and point_on_segment(b1, a1, a2, tolerance=tolerance):
        return True
    if o2 == 0 and point_on_segment(b2, a1, a2, tolerance=tolerance):
        return True
    if o3 == 0 and point_on_segment(a1, b1, b2, tolerance=tolerance):
        return True
    if o4 == 0 and point_on_segment(a2, b1, b2, tolerance=tolerance):
        return True

    return False


def segment_intersection_point(
    a1: PointN, a2: PointN, b1: PointN, b2: PointN, tolerance: float = _TOLERANCE
) -> PointN | None:
    """Intersection point of two finite segments, or ``None``.

    Returns ``None`` when the segments are parallel, collinear-overlapping, or
    do not intersect.
    """
    if not segments_intersect(a1, a2, b1, b2, tolerance=tolerance):
        return None

    x1, y1 = a1.x, a1.y
    x2, y2 = a2.x, a2.y
    x3, y3 = b1.x, b1.y
    x4, y4 = b2.x, b2.y

    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) <= tolerance:
        # Parallel (collinear) overlap has no unique point.
        return None

    px = (
        (x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)
    ) / denominator
    py = (
        (x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)
    ) / denominator
    return PointN(x=px, y=py)


def _validate_segment(segment: Sequence[PointN]) -> tuple[PointN, PointN]:
    points = list(segment)
    if len(points) != 2:
        raise ValueError("segment must contain exactly two endpoints")
    start, end = points
    if start.x == end.x and start.y == end.y:
        raise ValueError("segment endpoints must be distinct")
    return start, end


def trajectory_crosses_segment(
    trajectory: Sequence[PointN],
    segment: Sequence[PointN],
) -> bool:
    """True iff any consecutive pair in ``trajectory`` crosses the finite segment."""
    seg_start, seg_end = _validate_segment(segment)
    trajectory_points = list(trajectory)
    if len(trajectory_points) < 2:
        return False
    for i in range(len(trajectory_points) - 1):
        if segments_intersect(trajectory_points[i], trajectory_points[i + 1], seg_start, seg_end):
            return True
    return False


def crossing_segment_indices(
    trajectory: Sequence[PointN],
    segment: Sequence[PointN],
) -> list[tuple[int, int]]:
    """Return every trajectory edge index ``(i, i+1)`` that intersects the segment."""
    seg_start, seg_end = _validate_segment(segment)
    trajectory_points = list(trajectory)
    result: list[tuple[int, int]] = []
    for i in range(len(trajectory_points) - 1):
        if segments_intersect(trajectory_points[i], trajectory_points[i + 1], seg_start, seg_end):
            result.append((i, i + 1))
    return result
