"""Shared interval/episode-merging primitives using C0 TimeRange."""
from __future__ import annotations

from collections.abc import Sequence

from vision_app.contracts.models import SourceTimeMs, TimeRange


def merge_time_ranges(
    ranges: Sequence[TimeRange],
    max_gap_ms: int = 0,
) -> list[TimeRange]:
    """Merge a sequence of half-open TimeRanges, bridging gaps up to ``max_gap_ms``.

    Adjacent intervals separated by a gap of at most ``max_gap_ms`` are merged.
    Larger gaps are preserved so the result does not hide unknown/negative spans.
    """
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: r.start_ms.root)
    merged: list[TimeRange] = [ordered[0]]
    for current in ordered[1:]:
        last = merged[-1]
        if current.start_ms.root <= last.end_ms.root + max_gap_ms:
            new_end = max(last.end_ms.root, current.end_ms.root)
            merged[-1] = TimeRange(
                start_ms=SourceTimeMs(last.start_ms.root),
                end_ms=SourceTimeMs(new_end),
            )
        else:
            merged.append(current)
    return merged
