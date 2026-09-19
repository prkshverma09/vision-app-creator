"""CT-GEOMETRY: PointN/BoxN normalized validation and operations."""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError
from vision_app.contracts.models import BoxN, PointN
from vision_app.geometry.primitives import (
    box_area,
    box_contains,
    box_intersection,
    box_union,
    point_from_array,
    point_to_array,
)


def test_pointn_contract_rejects_non_finite_and_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        PointN(x=float("nan"), y=0.5)
    with pytest.raises(ValidationError):
        PointN(x=float("inf"), y=0.5)
    with pytest.raises(ValidationError):
        PointN(x=-0.01, y=0.5)
    with pytest.raises(ValidationError):
        PointN(x=0.5, y=1.01)


def test_boxn_contract_rejects_degenerate_and_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        BoxN(x1=0.5, y1=0.5, x2=0.5, y2=0.7)
    with pytest.raises(ValidationError):
        BoxN(x1=0.3, y1=0.6, x2=0.5, y2=0.5)
    with pytest.raises(ValidationError):
        BoxN(x1=0.0, y1=0.0, x2=1.0, y2=float("nan"))
    with pytest.raises(ValidationError):
        BoxN(x1=-0.1, y1=0.0, x2=0.5, y2=0.5)


def test_point_to_array_roundtrip() -> None:
    p = PointN(x=0.25, y=0.75)
    arr = point_to_array(p)
    assert arr == (0.25, 0.75)
    assert point_from_array(arr) == p


def test_box_area() -> None:
    assert math.isclose(box_area(BoxN(x1=0.1, y1=0.2, x2=0.4, y2=0.6)), 0.12, rel_tol=1e-9)


def test_box_contains_point() -> None:
    box = BoxN(x1=0.2, y1=0.3, x2=0.8, y2=0.7)
    assert box_contains(box, PointN(x=0.5, y=0.5))
    assert box_contains(box, PointN(x=0.2, y=0.3))
    assert not box_contains(box, PointN(x=0.1, y=0.5))
    assert not box_contains(box, PointN(x=0.5, y=0.71))


def test_box_intersection() -> None:
    a = BoxN(x1=0.1, y1=0.1, x2=0.5, y2=0.5)
    b = BoxN(x1=0.3, y1=0.3, x2=0.7, y2=0.7)
    inter = box_intersection(a, b)
    assert inter is not None
    assert math.isclose(inter.x1, 0.3, abs_tol=1e-9)
    assert math.isclose(inter.y1, 0.3, abs_tol=1e-9)
    assert math.isclose(inter.x2, 0.5, abs_tol=1e-9)
    assert math.isclose(inter.y2, 0.5, abs_tol=1e-9)

    c = BoxN(x1=0.6, y1=0.1, x2=0.9, y2=0.9)
    assert box_intersection(a, c) is None


def test_box_union() -> None:
    a = BoxN(x1=0.1, y1=0.2, x2=0.5, y2=0.6)
    b = BoxN(x1=0.3, y1=0.1, x2=0.8, y2=0.7)
    union = box_union(a, b)
    assert math.isclose(union.x1, 0.1, abs_tol=1e-9)
    assert math.isclose(union.y1, 0.1, abs_tol=1e-9)
    assert math.isclose(union.x2, 0.8, abs_tol=1e-9)
    assert math.isclose(union.y2, 0.7, abs_tol=1e-9)
