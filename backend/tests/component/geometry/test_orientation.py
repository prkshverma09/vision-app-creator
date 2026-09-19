"""CT-GEOMETRY: direction/orientation from sequential points."""
from __future__ import annotations

import math

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.orientation import (
    direction_from_points,
    heading,
    polygon_is_clockwise,
    signed_area,
    signed_distance_to_line,
)


def test_signed_area_counter_clockwise_is_positive() -> None:
    poly = [
        PointN(x=0.0, y=0.0),
        PointN(x=1.0, y=0.0),
        PointN(x=1.0, y=1.0),
        PointN(x=0.0, y=1.0),
    ]
    assert signed_area(poly) == pytest.approx(1.0, abs=1e-9)


def test_signed_area_clockwise_is_negative() -> None:
    poly = [
        PointN(x=0.0, y=0.0),
        PointN(x=0.0, y=1.0),
        PointN(x=1.0, y=1.0),
        PointN(x=1.0, y=0.0),
    ]
    assert signed_area(poly) == pytest.approx(-1.0, abs=1e-9)


def test_polygon_is_clockwise() -> None:
    ccw = [
        PointN(x=0.0, y=0.0),
        PointN(x=1.0, y=0.0),
        PointN(x=1.0, y=1.0),
    ]
    cw = [
        PointN(x=0.0, y=0.0),
        PointN(x=0.0, y=1.0),
        PointN(x=1.0, y=1.0),
    ]
    assert not polygon_is_clockwise(ccw)
    assert polygon_is_clockwise(cw)


def test_heading_for_cardinal_directions() -> None:
    origin = PointN(x=0.5, y=0.5)
    assert heading(origin, PointN(x=1.0, y=0.5)) == pytest.approx(0.0, abs=1e-9)
    assert heading(origin, PointN(x=0.5, y=1.0)) == pytest.approx(math.pi / 2, abs=1e-9)
    assert heading(origin, PointN(x=0.0, y=0.5)) == pytest.approx(math.pi, abs=1e-9)


def test_direction_from_points_returns_unit_vector() -> None:
    points = [
        PointN(x=0.0, y=0.0),
        PointN(x=0.0, y=0.0),
        PointN(x=0.6, y=0.8),
    ]
    dx, dy = direction_from_points(points)
    assert dx == pytest.approx(0.6, abs=1e-9)
    assert dy == pytest.approx(0.8, abs=1e-9)


def test_direction_from_points_rejects_single_point() -> None:
    with pytest.raises(ValueError):
        direction_from_points([PointN(x=0.5, y=0.5)])


def test_signed_distance_to_line() -> None:
    a = PointN(x=0.2, y=0.5)
    b = PointN(x=0.8, y=0.5)
    assert signed_distance_to_line(PointN(x=0.5, y=0.7), a, b) == pytest.approx(0.2, abs=1e-9)
    assert signed_distance_to_line(PointN(x=0.5, y=0.3), a, b) == pytest.approx(-0.2, abs=1e-9)
