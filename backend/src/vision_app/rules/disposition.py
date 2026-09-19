"""Hard-gate dispositions for rule candidates."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from vision_app.contracts.models import CrossingBracket, SignalInterval

Disposition = Literal["candidate", "supported", "rejected", "inconclusive"]


def _interval_covers(
    red: SignalInterval,
    bracket: CrossingBracket,
    margin_ms: int,
) -> bool:
    """True when ``red`` conservatively covers the bracket plus margin."""
    r0 = red.confirmed_range.start_ms.root
    r1 = red.confirmed_range.end_ms.root
    a = bracket.last_pre_ms.root
    b = bracket.first_post_ms.root
    if r0 > a - margin_ms or r1 <= b + margin_ms:
        return False
    for gap in red.gaps:
        if gap.end_ms.root > a and gap.start_ms.root < b:
            return False
    return True


def _bracket_overlaps_gap(
    red_intervals: Sequence[SignalInterval],
    bracket: CrossingBracket,
) -> bool:
    """True when the bracket overlaps a confirmed gap in any red interval."""
    a = bracket.last_pre_ms.root
    b = bracket.first_post_ms.root
    for red in red_intervals:
        for gap in red.gaps:
            if gap.end_ms.root > a and gap.start_ms.root < b:
                return True
    return False


def _bracket_in_inter_red_gap(
    red_intervals: Sequence[SignalInterval],
    bracket: CrossingBracket,
) -> bool:
    """True when the bracket falls entirely between two red intervals."""
    if len(red_intervals) < 2:
        return False
    a = bracket.last_pre_ms.root
    b = bracket.first_post_ms.root
    sorted_intervals = sorted(
        red_intervals, key=lambda r: r.confirmed_range.start_ms.root
    )
    for prev, nxt in zip(sorted_intervals, sorted_intervals[1:], strict=False):
        prev_end = prev.confirmed_range.end_ms.root
        nxt_start = nxt.confirmed_range.start_ms.root
        if a >= prev_end and b <= nxt_start:
            return True
    return False


def red_phase_disposition(
    bracket: CrossingBracket,
    red_intervals: Sequence[SignalInterval],
    margin_ms: int,
) -> tuple[Disposition, list[str]]:
    """Return (disposition, fact_refs) for a crossing against red intervals.

    A crossing is ``supported`` only when a confirmed red interval fully
    covers the bracket plus the ambiguity margin without an intervening gap.
    ``rejected`` means the bracket is entirely outside confirmed red periods.
    Everything else (partial overlap, transition proximity, missing coverage,
    or a gap inside/around the bracket) is ``inconclusive``.
    """
    facts = [
        f"crossing:{bracket.last_pre_ms.root}:{bracket.first_post_ms.root}",
    ]

    if not red_intervals:
        return "rejected", facts + ["signal:no_red_interval"]

    a = bracket.last_pre_ms.root
    b = bracket.first_post_ms.root

    fully_inside = any(
        _interval_covers(red, bracket, margin_ms) for red in red_intervals
    )
    if fully_inside:
        return "supported", facts + ["signal:red"]

    # Any direct overlap with a red interval means the timing is uncertain.
    overlaps_red = any(
        a < red.confirmed_range.end_ms.root and b > red.confirmed_range.start_ms.root
        for red in red_intervals
    )
    if overlaps_red or _bracket_overlaps_gap(red_intervals, bracket):
        return "inconclusive", facts + ["signal:partial_or_gap"]

    if _bracket_in_inter_red_gap(red_intervals, bracket):
        return "inconclusive", facts + ["signal:unknown_gap"]

    return "rejected", facts + ["signal:outside_red"]


def line_crossing_disposition(
    bracket: CrossingBracket,
) -> tuple[Disposition, list[str]]:
    return "supported", [
        f"crossing:{bracket.last_pre_ms.root}:{bracket.first_post_ms.root}",
        "direction:valid",
    ]
