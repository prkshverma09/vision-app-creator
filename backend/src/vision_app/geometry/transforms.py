"""Explicit source/model/display coordinate transforms, including rotation and letterbox."""
from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

from vision_app.contracts.models import PointN


class DisplayRect(NamedTuple):
    left: float
    top: float
    width: float
    height: float


def _validate_rotation(rotation_degrees: int) -> None:
    if rotation_degrees not in (0, 90, 180, 270):
        raise ValueError("rotation must be one of 0, 90, 180, 270 degrees")


def rotated_size(
    source_width: int,
    source_height: int,
    rotation_degrees: int,
) -> tuple[int, int]:
    """Return the displayed width/height after applying a cardinal rotation."""
    _validate_rotation(rotation_degrees)
    if rotation_degrees in (90, 270):
        return (source_height, source_width)
    return (source_width, source_height)


def _letterbox_rect(
    content_width: int,
    content_height: int,
    container_width: int,
    container_height: int,
) -> DisplayRect:
    scale = min(
        container_width / content_width,
        container_height / content_height,
    )
    width = content_width * scale
    height = content_height * scale
    left = (container_width - width) / 2.0
    top = (container_height - height) / 2.0
    return DisplayRect(left=left, top=top, width=width, height=height)


def display_rect_for_source(
    source_width: int,
    source_height: int,
    rotation_degrees: int,
    container_width: int,
    container_height: int,
) -> DisplayRect:
    """Compute the video rectangle inside a display container, handling rotation
    and letterboxing/pillarboxing with uniform scaling.
    """
    _validate_rotation(rotation_degrees)
    displayed_width, displayed_height = rotated_size(
        source_width, source_height, rotation_degrees
    )
    return _letterbox_rect(
        displayed_width, displayed_height, container_width, container_height
    )


def _validate_normalized(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("normalized coordinate must be in [0, 1]")


def source_norm_to_display(
    point: PointN,
    display_rect: DisplayRect,
) -> tuple[float, float]:
    """Map a rotation-normalized source point into display/container pixels."""
    _validate_normalized(point.x)
    _validate_normalized(point.y)
    return (
        display_rect.left + point.x * display_rect.width,
        display_rect.top + point.y * display_rect.height,
    )


def display_to_source_norm(
    display_point: tuple[float, float],
    display_rect: DisplayRect,
) -> PointN:
    """Invert ``source_norm_to_display``. Points outside the video rectangle are
    clamped to the nearest normalized source coordinate.
    """
    x, y = display_point
    if display_rect.width == 0 or display_rect.height == 0:
        raise ValueError("display rectangle has zero size")
    nx = (x - display_rect.left) / display_rect.width
    ny = (y - display_rect.top) / display_rect.height
    return PointN(x=max(0.0, min(1.0, nx)), y=max(0.0, min(1.0, ny)))


def model_input_rect_for_source(
    source_width: int,
    source_height: int,
    rotation_degrees: int,
    model_input_width: int,
    model_input_height: int,
) -> DisplayRect:
    """Letterbox the (possibly rotated) source into the model input tensor size."""
    _validate_rotation(rotation_degrees)
    displayed_width, displayed_height = rotated_size(
        source_width, source_height, rotation_degrees
    )
    return _letterbox_rect(
        displayed_width,
        displayed_height,
        model_input_width,
        model_input_height,
    )


def source_norm_to_model_input(
    point: PointN,
    source_width: int,
    source_height: int,
    model_input_width: int,
    model_input_height: int,
    rotation_degrees: int = 0,
) -> PointN:
    """Map a rotation-normalized source point into model-input normalized space.

    The model input is treated as a container and the source is uniformly scaled
    and letterboxed inside it. The ``rotation_degrees`` parameter is used only
    to determine the source's displayed aspect ratio; ``point`` must already be
    in rotation-normalized coordinates.
    """
    _validate_normalized(point.x)
    _validate_normalized(point.y)
    rect = model_input_rect_for_source(
        source_width, source_height, rotation_degrees,
        model_input_width, model_input_height,
    )
    return PointN(
        x=max(0.0, min(1.0, (rect.left + point.x * rect.width) / model_input_width)),
        y=max(0.0, min(1.0, (rect.top + point.y * rect.height) / model_input_height)),
    )


def model_input_to_source_norm(
    point: PointN,
    source_width: int,
    source_height: int,
    model_input_width: int,
    model_input_height: int,
    rotation_degrees: int = 0,
) -> PointN:
    """Invert ``source_norm_to_model_input``."""
    rect = model_input_rect_for_source(
        source_width, source_height, rotation_degrees,
        model_input_width, model_input_height,
    )
    if rect.width == 0 or rect.height == 0:
        raise ValueError("model input rectangle has zero size")
    nx = (point.x * model_input_width - rect.left) / rect.width
    ny = (point.y * model_input_height - rect.top) / rect.height
    return PointN(x=max(0.0, min(1.0, nx)), y=max(0.0, min(1.0, ny)))


def rotate_norm(
    point: PointN,
    source_width: int,
    source_height: int,
    rotation_degrees: int,
) -> PointN:
    """Rotate a raw normalized source point by a cardinal angle.

    The result is normalized in the displayed (rotation-normalized) frame, whose
    dimensions are given by ``rotated_size(source_width, source_height, ...)``.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")
    _validate_rotation(rotation_degrees)

    # Work in pixel coordinates so dimensions are explicit, then re-normalize.
    x_px = point.x * source_width
    y_px = point.y * source_height

    if rotation_degrees == 0:
        return PointN(x=point.x, y=point.y)
    if rotation_degrees == 90:
        new_x_px = source_height - y_px
        new_y_px = x_px
        return PointN(x=new_x_px / source_height, y=new_y_px / source_width)
    if rotation_degrees == 180:
        new_x_px = source_width - x_px
        new_y_px = source_height - y_px
        return PointN(x=new_x_px / source_width, y=new_y_px / source_height)
    # rotation_degrees == 270
    new_x_px = y_px
    new_y_px = source_width - x_px
    return PointN(x=new_x_px / source_height, y=new_y_px / source_width)


def apply_rotation_to_points(
    points: Sequence[PointN],
    source_width: int,
    source_height: int,
    rotation_degrees: int,
) -> list[PointN]:
    """Apply ``rotate_norm`` to each point, preserving order."""
    return [
        rotate_norm(p, source_width, source_height, rotation_degrees)
        for p in points
    ]
