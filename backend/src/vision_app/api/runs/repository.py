"""Deterministic in-memory runs repository used by route component tests."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from vision_app.contracts.models import Event, RunProgress
from vision_app.security.authorization.boundary import ResourceFamily, ResourceOwnership

from .router import RunCreate, RunRecord


class InMemoryRunRepository:
    """Small fake preserving idempotency, active-attempt selection and stable records."""

    def __init__(self, *, resolver: Any | None = None) -> None:
        self._resolver = resolver
        self._runs: dict[str, RunRecord] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._events: dict[str, dict[str, Event]] = {}
        self._progress: dict[str, list[RunProgress]] = {}

    async def create(
        self, workspace_id: str, request: RunCreate, idempotency_key: str
    ) -> RunRecord:
        key = (workspace_id, idempotency_key)
        existing = self._idempotency.get(key)
        if existing is not None:
            return self._runs[existing]
        run_id = f"run-{len(self._runs) + 1}"
        record = RunRecord(
            run_id, workspace_id, request.version_id, request.asset_id, request.calibration_id
        )
        self._runs[run_id] = record
        self._idempotency[key] = run_id
        self._register(ResourceFamily.RUN, run_id, workspace_id)
        return record

    async def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def events(self, run_id: str, attempt_id: str) -> list[Event]:
        return [
            item for item in self._events.get(run_id, {}).values()
            if item.attempt_id.root == attempt_id
        ]

    async def event(self, run_id: str, attempt_id: str, event_id: str) -> Event | None:
        item = self._events.get(run_id, {}).get(event_id)
        return item if item is not None and item.attempt_id.root == attempt_id else None

    async def progress(self, run_id: str, attempt_id: str) -> list[RunProgress]:
        return [item for item in self._progress.get(run_id, []) if item.attempt_id.root == attempt_id]

    def select_attempt(self, run_id: str, attempt_id: str) -> None:
        record = self._runs[run_id]
        self._runs[run_id] = replace(record, selected_attempt_id=attempt_id)
        self._register(ResourceFamily.ATTEMPT, attempt_id, record.workspace_id)

    def add_event(self, event: Event) -> None:
        self._events.setdefault(event.run_id.root, {})[event.id.root] = event
        record = self._runs[event.run_id.root]
        self._register(ResourceFamily.EVENT, event.id.root, record.workspace_id)

    def add_progress(self, progress: RunProgress) -> None:
        self._progress.setdefault(progress.run_id.root, []).append(progress)

    def _register(self, family: ResourceFamily, resource_id: str, workspace_id: str) -> None:
        if self._resolver is None:
            return
        items = getattr(self._resolver, "_items", None)
        if isinstance(items, dict):
            ownership = ResourceOwnership(family, resource_id, workspace_id)
            items[(family, resource_id)] = ownership
