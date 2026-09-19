"""Hysteresis bands and interval arithmetic helpers for temporal geometry."""
from __future__ import annotations

from collections.abc import Sequence
from math import copysign
from typing import TypeVar

from vision_app.contracts.models import PointN

from .orientation import signed_distance_to_line

T = TypeVar("T", int, float)


def signed_distance_to_segment(
    point: PointN,
    segment_start: PointN,
    segment_end: PointN,
) -> float:
    """Signed perpendicular distance from ``point`` to the supporting line of
    the finite ``segment_start -> segment_end``.

    The sign follows the orientation of the directed segment (left is positive).
    """
    if segment_start.x == segment_end.x and segment_start.y == segment_end.y:
        raise ValueError("segment endpoints must be distinct")
    return signed_distance_to_line(point, segment_start, segment_end)


def side_of_oriented_line(
    point: PointN,
    line_start: PointN,
    line_end: PointN,
    band_width: float,
) -> int:
    """Return ``1``/``-1`` for left/right of the directed line, or ``0`` when the
    point is within ``band_width`` of the line (the hysteresis dead band).
    """
    distance = signed_distance_to_line(point, line_start, line_end)
    if abs(distance) <= band_width:
        return 0
    return int(copysign(1.0, distance))


def clamp(value: T, lower: T, upper: T) -> T:
    """Clamp ``value`` to the inclusive ``[lower, upper]`` range."""
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def intervals_overlap(a: tuple[T, T], b: tuple[T, T]) -> bool:
    """Whether two half-open intervals ``[a0, a1)`` and ``[b0, b1)`` overlap."""
    return a[0] < b[1] and b[0] < a[1]


def merge_intervals(intervals: Sequence[tuple[T, T]]) -> list[tuple[T, T]]:
    """Merge a sequence of half-open intervals into a sorted, non-overlapping list.

    Adjacent but non-overlapping intervals (e.g. ``[0, 10)`` and ``[10, 15)``) are
    kept separate so the result still reveals the gap between them.
    """
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item[0])
    merged: list[tuple[T, T]] = [ordered[0]]
    for current in ordered[1:]:
        last_start, last_end = merged[-1]
        current_start, current_end = current
        if current_start < last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged


def gaps_between(
    intervals: Sequence[tuple[T, T]],
    bounds: tuple[T, T] | None = None,
) -> list[tuple[T, T]]:
    """Return uncovered half-open intervals within ``bounds`` (or between intervals
    when no bounds are supplied).
    """
    if not intervals:
        if bounds is None:
            return []
        lower, upper = bounds
        if upper <= lower:
            raise ValueError("bounds must satisfy lower < upper")
        return [(lower, upper)]

    ordered = sorted(intervals, key=lambda item: item[0])
    gaps: list[tuple[T, T]] = []

    if bounds is not None:
        lower, upper = bounds
        if upper <= lower:
            raise ValueError("bounds must satisfy lower < upper")
        cursor = lower
        for start, end in ordered:
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < upper:
            gaps.append((cursor, upper))
    else:
        cursor: T = ordered[0][1]  # type: ignore[no-redef]
        for start, end in ordered[1:]:
            if start > cursor:
                gaps.append((cursor, start))
            cursor = max(cursor, end)

    return gaps
