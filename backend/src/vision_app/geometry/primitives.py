"""Basic point/box primitives built on C0 contract types."""
from __future__ import annotations

from vision_app.contracts.models import BoxN, PointN


def point_to_array(point: PointN) -> tuple[float, float]:
    """Return the normalized coordinates as a plain tuple."""
    return (point.x, point.y)


def point_from_array(pair: tuple[float, float]) -> PointN:
    """Build a ``PointN`` from a coordinate pair."""
    return PointN(x=pair[0], y=pair[1])


def box_area(box: BoxN) -> float:
    """Positive area of a normalized box."""
    return (box.x2 - box.x1) * (box.y2 - box.y1)


def box_contains(box: BoxN, point: PointN) -> bool:
    """Whether ``point`` lies inside ``box``, including the boundary."""
    return (
        box.x1 <= point.x <= box.x2
        and box.y1 <= point.y <= box.y2
    )


def box_intersection(a: BoxN, b: BoxN) -> BoxN | None:
    """Intersection of two boxes, or ``None`` if they do not overlap."""
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    if x1 >= x2 or y1 >= y2:
        return None
    return BoxN(x1=x1, y1=y1, x2=x2, y2=y2)


def box_union(a: BoxN, b: BoxN) -> BoxN:
    """Smallest axis-aligned box containing both boxes."""
    return BoxN(
        x1=min(a.x1, b.x1),
        y1=min(a.y1, b.y1),
        x2=max(a.x2, b.x2),
        y2=max(a.y2, b.y2),
    )
