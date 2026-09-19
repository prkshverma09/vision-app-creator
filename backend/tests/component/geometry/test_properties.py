"""Property-based invariants for geometry utilities (CT-GEOMETRY)."""
from __future__ import annotations

import math

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.polygons import point_in_polygon
from vision_app.geometry.transforms import (
    display_rect_for_source,
    display_to_source_norm,
    model_input_to_source_norm,
    source_norm_to_display,
    source_norm_to_model_input,
)

hypothesis = pytest.importorskip("hypothesis")
given = hypothesis.given
settings = hypothesis.settings
st = hypothesis.strategies


@settings(max_examples=200, deadline=None)
@given(
    st.integers(min_value=1, max_value=2000),
    st.integers(min_value=1, max_value=2000),
    st.integers(min_value=1, max_value=2000),
    st.integers(min_value=1, max_value=2000),
    st.sampled_from([0, 90, 180, 270]),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_display_coordinate_roundtrip(
    source_w: int,
    source_h: int,
    container_w: int,
    container_h: int,
    rotation: int,
    x: float,
    y: float,
) -> None:
    point = PointN(x=x, y=y)
    rect = display_rect_for_source(source_w, source_h, rotation, container_w, container_h)
    display = source_norm_to_display(point, rect)
    back = display_to_source_norm(display, rect)
    assert math.isclose(back.x, point.x, abs_tol=1e-9)
    assert math.isclose(back.y, point.y, abs_tol=1e-9)


@settings(max_examples=200, deadline=None)
@given(
    st.integers(min_value=10, max_value=1000),
    st.integers(min_value=10, max_value=1000),
    st.integers(min_value=10, max_value=1000),
    st.integers(min_value=10, max_value=1000),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_model_input_letterbox_roundtrip(
    source_w: int,
    source_h: int,
    model_w: int,
    model_h: int,
    x: float,
    y: float,
) -> None:
    point = PointN(x=x, y=y)
    model = source_norm_to_model_input(point, source_w, source_h, model_w, model_h)
    back = model_input_to_source_norm(model, source_w, source_h, model_w, model_h)
    assert math.isclose(back.x, point.x, abs_tol=1e-9)
    assert math.isclose(back.y, point.y, abs_tol=1e-9)


@settings(max_examples=200, deadline=None)
@given(
    st.floats(min_value=0.01, max_value=0.6, allow_nan=False, allow_infinity=False),
)
def test_point_in_polygon_scale_invariance(scale: float) -> None:
    base_poly = [
        PointN(x=0.0, y=0.0),
        PointN(x=1.0, y=0.0),
        PointN(x=1.0, y=1.0),
        PointN(x=0.0, y=1.0),
    ]
    poly = [PointN(x=v.x * scale, y=v.y * scale) for v in base_poly]
    inside = PointN(x=0.3 * scale, y=0.4 * scale)
    outside = PointN(x=1.5 * scale, y=0.5 * scale)
    assert point_in_polygon(inside, poly)
    assert not point_in_polygon(outside, poly)


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 1000), st.integers(0, 1000)), min_size=0, max_size=50))
def test_interval_merge_is_idempotent(raw_intervals: list[tuple[int, int]]) -> None:
    from vision_app.geometry.bands import merge_intervals

    intervals = [(min(a, b), max(a, b)) for a, b in raw_intervals]
    once = merge_intervals(intervals)
    twice = merge_intervals(once)
    assert once == twice
