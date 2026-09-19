"""CT-GEOMETRY: finite line-segment crossing for trajectories."""
from __future__ import annotations

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.segments import (
    crossing_segment_indices,
    orientation,
    point_on_segment,
    segment_intersection_point,
    segments_intersect,
    trajectory_crosses_segment,
)


def test_segments_intersect_when_crossing() -> None:
    a1 = PointN(x=0.0, y=0.0)
    a2 = PointN(x=1.0, y=1.0)
    b1 = PointN(x=0.0, y=1.0)
    b2 = PointN(x=1.0, y=0.0)
    assert segments_intersect(a1, a2, b1, b2)


def test_segments_do_not_intersect_when_parallel() -> None:
    a1 = PointN(x=0.0, y=0.0)
    a2 = PointN(x=1.0, y=0.0)
    b1 = PointN(x=0.0, y=1.0)
    b2 = PointN(x=1.0, y=1.0)
    assert not segments_intersect(a1, a2, b1, b2)


def test_segments_intersect_at_shared_endpoint() -> None:
    a1 = PointN(x=0.0, y=0.0)
    a2 = PointN(x=1.0, y=0.0)
    b1 = PointN(x=1.0, y=0.0)
    b2 = PointN(x=1.0, y=1.0)
    assert segments_intersect(a1, a2, b1, b2)


def test_orientation_collinear_returns_zero() -> None:
    p = PointN(x=0.0, y=0.0)
    q = PointN(x=0.5, y=0.5)
    r = PointN(x=1.0, y=1.0)
    assert orientation(p, q, r) == 0


def test_orientation_counter_clockwise_is_positive() -> None:
    p = PointN(x=0.0, y=0.0)
    q = PointN(x=1.0, y=0.0)
    r = PointN(x=0.5, y=1.0)
    assert orientation(p, q, r) == 1


def test_orientation_clockwise_is_negative() -> None:
    p = PointN(x=0.2, y=0.2)
    q = PointN(x=0.8, y=0.2)
    r = PointN(x=0.5, y=0.0)
    assert orientation(p, q, r) == -1


def test_point_on_segment_detects_interior_and_endpoints() -> None:
    a = PointN(x=0.0, y=0.0)
    b = PointN(x=0.5, y=0.5)
    assert point_on_segment(PointN(x=0.25, y=0.25), a, b)
    assert point_on_segment(PointN(x=0.0, y=0.0), a, b)
    assert not point_on_segment(PointN(x=0.6, y=0.6), a, b)


def test_trajectory_crosses_finite_segment() -> None:
    segment = [PointN(x=0.0, y=0.5), PointN(x=1.0, y=0.5)]
    trajectory = [PointN(x=0.3, y=0.3), PointN(x=0.3, y=0.7)]
    assert trajectory_crosses_segment(trajectory, segment)
    assert crossing_segment_indices(trajectory, segment) == [(0, 1)]


def test_infinite_extension_crossing_but_not_finite_segment_is_no_crossing() -> None:
    """A trajectory crossing the line y=0.3 at x=0.2, but the finite segment only
    covers x in [0.7, 0.9], must not register a crossing."""
    finite_segment = [PointN(x=0.7, y=0.3), PointN(x=0.9, y=0.3)]
    trajectory = [PointN(x=0.2, y=0.2), PointN(x=0.2, y=0.5)]
    assert not trajectory_crosses_segment(trajectory, segment=finite_segment)
    assert crossing_segment_indices(trajectory, finite_segment) == []


def test_trajectory_crosses_in_reverse_direction() -> None:
    segment = [PointN(x=0.2, y=0.5), PointN(x=0.8, y=0.5)]
    forward = [PointN(x=0.5, y=0.3), PointN(x=0.5, y=0.7)]
    reverse = [PointN(x=0.5, y=0.7), PointN(x=0.5, y=0.3)]
    assert trajectory_crosses_segment(forward, segment)
    assert trajectory_crosses_segment(reverse, segment)


def test_segment_intersection_point_for_crossing() -> None:
    a1 = PointN(x=0.0, y=0.0)
    a2 = PointN(x=1.0, y=1.0)
    b1 = PointN(x=0.0, y=1.0)
    b2 = PointN(x=1.0, y=0.0)
    pt = segment_intersection_point(a1, a2, b1, b2)
    assert pt is not None
    assert pytest.approx(pt.x, abs=1e-9) == 0.5
    assert pytest.approx(pt.y, abs=1e-9) == 0.5


def test_segment_intersection_point_for_non_crossing_returns_none() -> None:
    a1 = PointN(x=0.0, y=0.0)
    a2 = PointN(x=1.0, y=0.0)
    b1 = PointN(x=0.0, y=1.0)
    b2 = PointN(x=1.0, y=1.0)
    assert segment_intersection_point(a1, a2, b1, b2) is None


def test_degenerate_segment_raises() -> None:
    with pytest.raises(ValueError):
        trajectory_crosses_segment(
            [PointN(x=0.0, y=0.0), PointN(x=1.0, y=1.0)],
            [PointN(x=0.0, y=0.0), PointN(x=0.0, y=0.0)],
        )
