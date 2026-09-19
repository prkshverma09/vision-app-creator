"""Convert provider-native coordinates into C0 PointN/BoxN normalized geometry."""

from __future__ import annotations

from typing import Any, Literal

from vision_app.contracts.models import BoxN, PointN


class CoordinateError(ValueError):
    pass


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise CoordinateError(f"{name} must be a number, not bool")
    if not isinstance(value, (int, float)):
        raise CoordinateError(f"{name} must be a number")
    from math import isfinite

    if not isfinite(value):
        raise CoordinateError(f"{name} must be finite")
    return float(value)


def detect_coordinate_space(
    raw: dict[str, Any],
    width: int,
    height: int,
    keys: tuple[str, ...],
    hint: Literal["normalized", "pixels", "thousand"] | None = None,
) -> Literal["normalized", "pixels", "thousand"]:
    """Best-effort coordinate space detection.  A provided hint always wins."""
    if hint is not None:
        return hint

    values = [_finite_number(raw.get(k, 0.0), k) for k in keys if k in raw]
    if not values:
        raise CoordinateError("no coordinate keys found")

    max_value = max(abs(v) for v in values)
    if max_value <= 1.0:
        return "normalized"
    if width > 0 and height > 0 and all(
        v <= max(width, height) * 1.01 or v == 0 for v in values
    ):
        # Values fit within the source pixel rectangle, but are not [0,1].
        return "pixels"
    # Providers often use a [0,1000] relative encoding (e.g. legacy vision APIs).
    if max_value <= 1001.0:
        return "thousand"
    return "pixels"


def normalize_point(
    raw: dict[str, Any],
    width: int,
    height: int,
    *,
    x_key: str = "x",
    y_key: str = "y",
    hint: Literal["normalized", "pixels", "thousand"] | None = None,
) -> PointN:
    """Normalize a provider point into C0 PointN."""
    if x_key not in raw or y_key not in raw:
        raise CoordinateError(f"point must contain '{x_key}' and '{y_key}'")
    space = detect_coordinate_space(raw, width, height, (x_key, y_key), hint=hint)
    x = _finite_number(raw[x_key], x_key)
    y = _finite_number(raw[y_key], y_key)

    if space == "normalized":
        xn, yn = x, y
    elif space == "thousand":
        xn, yn = x / 1000.0, y / 1000.0
    else:
        if width <= 0 or height <= 0:
            raise CoordinateError("pixel normalization requires positive width and height")
        xn, yn = x / width, y / height

    # Clip to [0,1] defensively, then let PointN validate.
    xn = max(0.0, min(1.0, xn))
    yn = max(0.0, min(1.0, yn))
    return PointN(x=xn, y=yn)


def normalize_box(
    raw: dict[str, Any],
    width: int,
    height: int,
    *,
    keys: tuple[str, str, str, str] = ("x1", "y1", "x2", "y2"),
    hint: Literal["normalized", "pixels", "thousand"] | None = None,
) -> BoxN:
    """Normalize a provider box into C0 BoxN (x1,y1) top-left, (x2,y2) bottom-right."""
    k1, k2, k3, k4 = keys
    for k in keys:
        if k not in raw:
            raise CoordinateError(f"box must contain '{k}'")
    space = detect_coordinate_space(raw, width, height, keys, hint=hint)
    x1 = _finite_number(raw[k1], k1)
    y1 = _finite_number(raw[k2], k2)
    x2 = _finite_number(raw[k3], k3)
    y2 = _finite_number(raw[k4], k4)

    if space == "normalized":
        x1n, y1n, x2n, y2n = x1, y1, x2, y2
    elif space == "thousand":
        x1n, y1n, x2n, y2n = x1 / 1000.0, y1 / 1000.0, x2 / 1000.0, y2 / 1000.0
    else:
        if width <= 0 or height <= 0:
            raise CoordinateError("pixel normalization requires positive width and height")
        x1n, y1n, x2n, y2n = x1 / width, y1 / height, x2 / width, y2 / height

    x1n = max(0.0, min(1.0, x1n))
    y1n = max(0.0, min(1.0, y1n))
    x2n = max(0.0, min(1.0, x2n))
    y2n = max(0.0, min(1.0, y2n))

    if x1n >= x2n:
        x1n, x2n = min(x1n, x2n), max(x1n, x2n)
        if x1n == x2n:
            x2n = min(1.0, x1n + 1e-6)
    if y1n >= y2n:
        y1n, y2n = min(y1n, y2n), max(y1n, y2n)
        if y1n == y2n:
            y2n = min(1.0, y1n + 1e-6)

    return BoxN(x1=x1n, y1=y1n, x2=x2n, y2=y2n)
