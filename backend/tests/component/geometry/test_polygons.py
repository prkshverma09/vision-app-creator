"""CT-GEOMETRY: polygon validation and point-in-polygon boundary policy."""
from __future__ import annotations

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.polygons import (
    BoundaryPolicy,
    point_in_polygon,
    validate_polygon,
)


def square() -> list[PointN]:
    return [
        PointN(x=0.0, y=0.0),
        PointN(x=1.0, y=0.0),
        PointN(x=1.0, y=1.0),
        PointN(x=0.0, y=1.0),
    ]


def test_validate_polygon_accepts_simple_polygon() -> None:
    poly = square()
    assert validate_polygon(poly) == poly


def test_validate_polygon_rejects_too_few_vertices() -> None:
    with pytest.raises(ValueError):
        validate_polygon([PointN(x=0.0, y=0.0), PointN(x=1.0, y=1.0)])


def test_validate_polygon_rejects_collinear_vertices() -> None:
    collinear = [
        PointN(x=0.0, y=0.0),
        PointN(x=0.5, y=0.5),
        PointN(x=1.0, y=1.0),
    ]
    with pytest.raises(ValueError):
        validate_polygon(collinear)


def test_validate_polygon_rejects_degenerate_area() -> None:
    tiny = [
        PointN(x=0.0, y=0.0),
        PointN(x=1e-13, y=0.0),
        PointN(x=0.0, y=1e-13),
    ]
    with pytest.raises(ValueError):
        validate_polygon(tiny)


def test_point_in_polygon_inside_and_outside() -> None:
    poly = [
        PointN(x=0.3, y=0.1),
        PointN(x=0.7, y=0.1),
        PointN(x=0.5, y=0.6),
    ]
    assert point_in_polygon(PointN(x=0.5, y=0.3), poly)
    assert not point_in_polygon(PointN(x=0.1, y=0.1), poly)


def test_point_in_polygon_boundary_default_is_inside() -> None:
    poly = square()
    assert point_in_polygon(PointN(x=0.0, y=0.5), poly)
    assert point_in_polygon(PointN(x=0.5, y=1.0), poly)


def test_point_in_polygon_boundary_respects_policy() -> None:
    poly = square()
    boundary = PointN(x=0.5, y=1.0)
    assert point_in_polygon(boundary, poly, boundary_policy=BoundaryPolicy.INSIDE)
    assert not point_in_polygon(boundary, poly, boundary_policy=BoundaryPolicy.OUTSIDE)
