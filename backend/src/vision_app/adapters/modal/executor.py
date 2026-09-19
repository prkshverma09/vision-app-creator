"""JobExecutor adapter translating runtime context to Modal's wire contract."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from vision_app.contracts.models import Event, RunProgress
from vision_app.contracts.ports import EventSink
from vision_app.runtime.context import RunContext

from .models import ModalInvocationStatus, ModalRunInput, ModalStreamItem

ContextLoader = Callable[[str], RunContext | Awaitable[RunContext]]


class ModalClient(Protocol):
    async def submit(self, value: ModalRunInput, *, idempotency_key: str) -> str: ...
    def stream(self, invocation_id: str) -> AsyncIterator[ModalStreamItem]: ...
    async def cancel(self, invocation_id: str) -> None: ...
    async def query(self, invocation_id: str) -> ModalInvocationStatus: ...


class ModalExecutor:
    """Streams remote output into the normal fenced EventSink."""

    def __init__(
        self,
        client: ModalClient,
        context_loader: ContextLoader,
        sink: EventSink,
        *,
        fence: int,
    ) -> None:
        self._client = client
        self._load = context_loader
        self._sink = sink
        self._fence = fence
        self._by_run: dict[str, str] = {}
        self._pumps: dict[str, asyncio.Task[None]] = {}

    async def submit(self, run_id: str) -> str:
        if run_id in self._by_run:
            return self._by_run[run_id]
        loaded = self._load(run_id)
        context = await loaded if isinstance(loaded, Awaitable) else loaded
        if context.run_id.root != run_id:
            raise ValueError("loaded run context does not match submitted run")
        value = ModalRunInput.from_context(context, self._fence)
        invocation_id = await self._client.submit(value, idempotency_key=run_id)
        self._by_run[run_id] = invocation_id
        self._pumps[invocation_id] = asyncio.create_task(self._pump(invocation_id))
        return invocation_id

    async def _pump(self, invocation_id: str) -> None:
        async for item in self._client.stream(invocation_id):
            if item.kind == "progress":
                await self._sink.progress(RunProgress.model_validate(item.payload), item.fence)
            else:
                await self._sink.upsert(Event.model_validate(item.payload), item.fence)

    async def cancel(self, invocation_id: str) -> None:
        await self._client.cancel(invocation_id)

    async def query(self, invocation_id: str) -> ModalInvocationStatus:
        return await self._client.query(invocation_id)

    async def wait(self, invocation_id: str) -> None:
        task = self._pumps.get(invocation_id)
        if task is not None:
            await task
