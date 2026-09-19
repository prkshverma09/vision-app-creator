"""CT-GEOMETRY: hysteresis band and interval arithmetic helpers."""
from __future__ import annotations

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.bands import (
    clamp,
    gaps_between,
    intervals_overlap,
    merge_intervals,
    side_of_oriented_line,
    signed_distance_to_segment,
)


def test_signed_distance_to_segment() -> None:
    a = PointN(x=0.2, y=0.5)
    b = PointN(x=0.8, y=0.5)
    assert signed_distance_to_segment(PointN(x=0.5, y=0.7), a, b) == pytest.approx(0.2, abs=1e-9)
    assert signed_distance_to_segment(PointN(x=0.5, y=0.3), a, b) == pytest.approx(-0.2, abs=1e-9)
    assert signed_distance_to_segment(PointN(x=0.9, y=0.7), a, b) == pytest.approx(0.2, abs=1e-9)


def test_side_of_oriented_line_inside_band_is_zero() -> None:
    a = PointN(x=0.2, y=0.5)
    b = PointN(x=0.8, y=0.5)
    assert side_of_oriented_line(PointN(x=0.5, y=0.55), a, b, band_width=0.1) == 0
    assert side_of_oriented_line(PointN(x=0.5, y=0.5), a, b, band_width=0.1) == 0
    assert side_of_oriented_line(PointN(x=0.5, y=0.45), a, b, band_width=0.1) == 0


def test_side_of_oriented_line_outside_band_has_sign() -> None:
    a = PointN(x=0.2, y=0.5)
    b = PointN(x=0.8, y=0.5)
    assert side_of_oriented_line(PointN(x=0.5, y=0.7), a, b, band_width=0.1) == 1
    assert side_of_oriented_line(PointN(x=0.5, y=0.3), a, b, band_width=0.1) == -1


def test_clamp() -> None:
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(15, 0, 10) == 10
    assert clamp(2.5, 1.0, 3.0) == 2.5


def test_intervals_overlap() -> None:
    assert intervals_overlap((0, 10), (5, 15))
    assert intervals_overlap((0, 10), (9, 15))
    assert not intervals_overlap((0, 10), (10, 15))
    assert not intervals_overlap((0, 10), (11, 15))


def test_merge_intervals_sorts_and_merges() -> None:
    merged = merge_intervals([(5, 9), (1, 3), (2, 6), (10, 12)])
    assert merged == [(1, 9), (10, 12)]


def test_merge_intervals_returns_empty_for_empty_input() -> None:
    assert merge_intervals([]) == []


def test_gaps_between_computes_complementary_ranges() -> None:
    merged = [(1, 9), (10, 12)]
    assert gaps_between(merged, bounds=(0, 15)) == [(0, 1), (9, 10), (12, 15)]


def test_gaps_between_no_bounds_returns_gaps_between_intervals() -> None:
    merged = [(1, 3), (5, 7)]
    assert gaps_between(merged) == [(3, 5)]
