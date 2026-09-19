"""CT-GEOMETRY: explicit source/model/display coordinate transforms."""
from __future__ import annotations

import math

import pytest
from vision_app.contracts.models import PointN
from vision_app.geometry.transforms import (
    DisplayRect,
    display_rect_for_source,
    display_to_source_norm,
    model_input_rect_for_source,
    model_input_to_source_norm,
    rotate_norm,
    source_norm_to_display,
    source_norm_to_model_input,
)


def test_portrait_letterbox_display_rect() -> None:
    # 1080x1920 portrait source inside a 400x400 square container.
    rect = display_rect_for_source(1080, 1920, 0, 400, 400)
    assert rect.width == pytest.approx(225.0, abs=1e-9)
    assert rect.height == pytest.approx(400.0, abs=1e-9)
    assert rect.left == pytest.approx(87.5, abs=1e-9)
    assert rect.top == 0.0


def test_source_norm_to_display_roundtrip() -> None:
    rect = display_rect_for_source(320, 240, 0, 640, 480)
    for point in [PointN(x=0.0, y=0.0), PointN(x=0.5, y=0.5), PointN(x=1.0, y=1.0)]:
        display = source_norm_to_display(point, rect)
        back = display_to_source_norm(display, rect)
        assert back == point


def test_display_roundtrip_with_portrait_letterbox() -> None:
    rect = display_rect_for_source(1080, 1920, 0, 400, 400)
    point = PointN(x=0.3, y=0.7)
    display = source_norm_to_display(point, rect)
    back = display_to_source_norm(display, rect)
    assert math.isclose(back.x, point.x, abs_tol=1e-9)
    assert math.isclose(back.y, point.y, abs_tol=1e-9)


def test_rotation_90_swaps_displayed_dimensions() -> None:
    # Raw landscape 1920x1080 rotated 90° should display as portrait 1080x1920.
    rect = display_rect_for_source(1920, 1080, 90, 400, 400)
    rect0 = display_rect_for_source(1080, 1920, 0, 400, 400)
    assert rect.width == pytest.approx(rect0.width, abs=1e-9)
    assert rect.height == pytest.approx(rect0.height, abs=1e-9)


def test_invalid_rotation_raises() -> None:
    with pytest.raises(ValueError):
        display_rect_for_source(320, 240, 45, 640, 480)


def test_model_input_letterbox_roundtrip() -> None:
    # Portrait source scaled into a square 400x400 model input.
    source_w, source_h = 1080, 1920
    model_w, model_h = 400, 400
    for point in [PointN(x=0.0, y=0.0), PointN(x=0.5, y=0.5), PointN(x=1.0, y=1.0)]:
        model = source_norm_to_model_input(
            point, source_w, source_h, model_w, model_h, rotation_degrees=0
        )
        back = model_input_to_source_norm(
            model, source_w, source_h, model_w, model_h, rotation_degrees=0
        )
        assert math.isclose(back.x, point.x, abs_tol=1e-9)
        assert math.isclose(back.y, point.y, abs_tol=1e-9)


def test_model_input_rect_for_portrait_is_letterboxed() -> None:
    rect = model_input_rect_for_source(1080, 1920, 0, 400, 400)
    assert rect.width == pytest.approx(225.0, abs=1e-9)
    assert rect.height == pytest.approx(400.0, abs=1e-9)
    assert rect.left == pytest.approx(87.5, abs=1e-9)
    assert rect.top == 0.0


def test_rotate_norm_roundtrip_for_cardinal_rotations() -> None:
    # 1920x1080 raw landscape rotated 90° then unrotated 270° should recover point.
    raw = PointN(x=0.25, y=0.5)
    rotated = rotate_norm(raw, 1920, 1080, 90)
    unrotated = rotate_norm(rotated, 1080, 1920, 270)
    assert math.isclose(unrotated.x, raw.x, abs_tol=1e-9)
    assert math.isclose(unrotated.y, raw.y, abs_tol=1e-9)


def test_source_norm_outside_normalized_bounds_raises() -> None:
    with pytest.raises(ValueError):
        source_norm_to_display(PointN(x=1.1, y=0.5), DisplayRect(0, 0, 100, 100))
