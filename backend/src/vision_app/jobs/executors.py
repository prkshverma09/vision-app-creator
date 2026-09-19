"""JobExecutor adapters. The in-memory adapter is deterministic and makes no network calls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

Worker = Callable[[asyncio.Event], Coroutine[Any, Any, None]]


@dataclass(frozen=True)
class InvocationStatus:
    invocation_id: str
    state: str


class InMemoryJobExecutor:
    """Idempotent executor keyed by run ID with cooperative task cancellation."""

    def __init__(self, worker: Worker | None = None) -> None:
        self.worker = worker
        self.raise_after_submit_once = False
        self.submission_count = 0
        self.cancelled_invocations: list[str] = []
        self._by_run: dict[str, str] = {}
        self._cancel: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def submit(self, run_id: str) -> str:
        existing = self._by_run.get(run_id)
        if existing is not None:
            return existing
        invocation = f"invocation-{len(self._by_run) + 1}"
        self._by_run[run_id] = invocation
        self.submission_count += 1
        cancelled = asyncio.Event()
        self._cancel[invocation] = cancelled
        if self.worker is not None:
            self._tasks[invocation] = asyncio.create_task(self.worker(cancelled))
        if self.raise_after_submit_once:
            self.raise_after_submit_once = False
            raise ConnectionError("submission response lost")
        return invocation

    async def cancel(self, invocation_id: str) -> None:
        cancelled = self._cancel.get(invocation_id)
        if cancelled is not None and not cancelled.is_set():
            cancelled.set()
            self.cancelled_invocations.append(invocation_id)

    async def query(self, invocation_id: str) -> InvocationStatus:
        task = self._tasks.get(invocation_id)
        cancelled = self._cancel.get(invocation_id)
        if invocation_id not in self._cancel:
            return InvocationStatus(invocation_id, "unknown")
        if task is not None and task.done():
            state = "failed" if task.exception() is not None else "completed"
        elif cancelled is not None and cancelled.is_set():
            state = "cancelling"
        else:
            state = "running"
        return InvocationStatus(invocation_id, state)

    async def wait_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks.values())


class ModalJobExecutor:
    """Optional adapter boundary; a configured client is injected to avoid eager cloud imports."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def submit(self, run_id: str) -> str:
        return str(await self._client.submit(run_id, idempotency_key=run_id))

    async def cancel(self, invocation_id: str) -> None:
        await self._client.cancel(invocation_id)

    async def query(self, invocation_id: str) -> Any:
        return await self._client.query(invocation_id)
