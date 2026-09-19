"""Deterministic EventSink fake with fenced, idempotent progress and coverage."""

from __future__ import annotations

from vision_app.contracts.models import Event, RunProgress, TimeRange


class InMemoryEventSink:
    def __init__(self) -> None:
        self.events: dict[str, Event] = {}
        self.progress_updates: list[RunProgress] = []
        self.coverage: list[TimeRange] = []
        self._progress_keys: set[tuple[str, str, int, int]] = set()
        self._event_fences: dict[str, int] = {}

    async def upsert(self, event: Event, fence: int) -> None:
        previous = self._event_fences.get(event.id.root, -1)
        if fence < previous:
            return
        self.events[event.id.root] = event
        self._event_fences[event.id.root] = fence

    async def progress(self, progress: RunProgress, fence: int) -> None:
        key = (progress.run_id.root, progress.attempt_id.root, fence, progress.sequence)
        if key in self._progress_keys:
            return
        self._progress_keys.add(key)
        self.progress_updates.append(progress)
        self.coverage.extend(progress.processed_ranges)
