"""Source-time stability confirmation and conservative signal intervals."""
from __future__ import annotations

from dataclasses import dataclass

from vision_app.contracts.models import (
    CrossingBracket,
    SignalInterval,
    SignalObservation,
    SourceTimeMs,
    TimeRange,
)

from .observer import ColorState


@dataclass(frozen=True, slots=True)
class IntervalUpdate:
    confirmed_state: ColorState | None
    confirmed_since_ms: int | None
    completed_intervals: tuple[SignalInterval, ...]


class ConfirmedSignalIntervals:
    """Confirm stable colors without backdating and terminate coverage on unknown.

    Intervals are emitted only after their end is observed. Their start is the
    confirming sample, not the first candidate sample. The end is the first
    differing/unknown sample, with the adjacent observations retained as an
    uncertainty bracket where available.
    """

    def __init__(self, *, stability_ms: int) -> None:
        if stability_ms < 0:
            raise ValueError("stability_ms must be nonnegative")
        self._stability_ms = stability_ms
        self._last_time: int | None = None
        self._candidate: ColorState | None = None
        self._candidate_since: int | None = None
        self._candidate_start_uncertainty: CrossingBracket | None = None
        self._confirmed: ColorState | None = None
        self._confirmed_since: int | None = None
        self._last_confirmed_sample: int | None = None
        self._start_uncertainty: CrossingBracket | None = None
        self._completed: list[SignalInterval] = []

    def update(self, observation: SignalObservation) -> IntervalUpdate:
        time_ms = observation.source_time_ms.root
        if self._last_time is not None and time_ms < self._last_time:
            raise ValueError("signal observations must be ordered by source time")
        previous_time = self._last_time
        self._last_time = time_ms
        state = observation.state

        if self._confirmed is not None and state != self._confirmed:
            self._close_confirmed(time_ms, previous_time)
            self._candidate = None
            self._candidate_since = None
            self._candidate_start_uncertainty = None

        if state == "unknown":
            self._candidate = None
            self._candidate_since = None
            self._candidate_start_uncertainty = None
            return self._result()

        color: ColorState = state
        if self._confirmed == color:
            self._last_confirmed_sample = time_ms
            return self._result()

        if self._candidate != color:
            self._candidate = color
            self._candidate_since = time_ms
            self._candidate_start_uncertainty = self._bracket(previous_time, time_ms)

        assert self._candidate_since is not None
        if time_ms - self._candidate_since >= self._stability_ms:
            self._confirmed = color
            self._confirmed_since = time_ms
            self._last_confirmed_sample = time_ms
            self._start_uncertainty = self._candidate_start_uncertainty
            self._candidate = None
            self._candidate_since = None
            self._candidate_start_uncertainty = None
        return self._result()

    def _close_confirmed(self, end_ms: int, previous_time: int | None) -> None:
        assert self._confirmed is not None
        assert self._confirmed_since is not None
        # A same-timestamp contradiction has no positive half-open coverage.
        if end_ms > self._confirmed_since:
            self._completed.append(
                SignalInterval(
                    state=self._confirmed,
                    confirmed_range=TimeRange(
                        start_ms=SourceTimeMs(self._confirmed_since),
                        end_ms=SourceTimeMs(end_ms),
                    ),
                    start_uncertainty=self._start_uncertainty,
                    end_uncertainty=self._bracket(previous_time, end_ms),
                )
            )
        self._confirmed = None
        self._confirmed_since = None
        self._last_confirmed_sample = None
        self._start_uncertainty = None

    @staticmethod
    def _bracket(before_ms: int | None, after_ms: int) -> CrossingBracket | None:
        if before_ms is None or before_ms >= after_ms:
            return None
        return CrossingBracket(
            last_pre_ms=SourceTimeMs(before_ms), first_post_ms=SourceTimeMs(after_ms)
        )

    def flush(self, end_ms: int) -> tuple[SignalInterval, ...]:
        """Close any active confirmed interval at ``end_ms`` and return all intervals."""
        if self._confirmed is not None and self._confirmed_since is not None:
            self._close_confirmed(end_ms, self._last_time)
        return tuple(self._completed)

    def _result(self) -> IntervalUpdate:
        return IntervalUpdate(
            confirmed_state=self._confirmed,
            confirmed_since_ms=self._confirmed_since,
            completed_intervals=tuple(self._completed),
        )
