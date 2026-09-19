"""Deterministic in-process Modal test double; never imports or contacts Modal."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from vision_app.contracts.models import MoneyMicrousd, ResourceId, RunProgress

from .models import ModalInvocationStatus, ModalRunInput, ModalStreamItem

_END = object()


@dataclass
class _Invocation:
    value: ModalRunInput
    queue: asyncio.Queue[ModalStreamItem | object] = field(default_factory=asyncio.Queue)
    cancel_requested: asyncio.Event = field(default_factory=asyncio.Event)
    state: str = "queued"
    task: asyncio.Task[None] | None = None


class FakeModalClient:
    """Runs a tiny worker lifecycle and exposes the same streaming client surface."""

    def __init__(self, *, step_delay: float = 0.0) -> None:
        self.step_delay = step_delay
        self.submitted_inputs: list[ModalRunInput] = []
        self._runs: dict[str, _Invocation] = {}
        self._idempotency: dict[str, str] = {}

    async def submit(self, value: ModalRunInput, *, idempotency_key: str) -> str:
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            return existing
        invocation_id = f"fake-modal-{len(self._runs) + 1}"
        run = _Invocation(value)
        self._runs[invocation_id] = run
        self._idempotency[idempotency_key] = invocation_id
        self.submitted_inputs.append(value)
        run.task = asyncio.create_task(self._execute(run))
        return invocation_id

    async def _execute(self, run: _Invocation) -> None:
        run.state = "running"
        for sequence, phase in enumerate(("preparing", "running", "completed")):
            if self.step_delay:
                await asyncio.sleep(self.step_delay)
            if run.cancel_requested.is_set():
                await self._progress(run, "cancelled", sequence, True)
                run.state = "cancelled"
                break
            await self._progress(run, phase, sequence, False)
            if phase == "completed":
                run.state = "completed"
        await run.queue.put(_END)

    async def _progress(self, run: _Invocation, phase: str, sequence: int, cancelled: bool) -> None:
        progress = RunProgress(
            run_id=ResourceId(run.value.run_id),
            attempt_id=ResourceId(run.value.attempt_id),
            phase=phase,  # type: ignore[arg-type]
            processed_ranges=[],
            requested_samples=1,
            processed_samples=0 if phase == "preparing" else 1,
            review_backlog=0,
            cancel_requested=cancelled,
            usage=MoneyMicrousd(0),
            sequence=sequence,
        )
        await run.queue.put(
            ModalStreamItem(
                kind="progress",
                payload=progress.model_dump(mode="json"),
                fence=run.value.fence,
            )
        )

    async def stream(self, invocation_id: str):  # type: ignore[no-untyped-def]
        run = self._runs[invocation_id]
        while True:
            item = await run.queue.get()
            if item is _END:
                return
            assert isinstance(item, ModalStreamItem)
            yield item

    async def cancel(self, invocation_id: str) -> None:
        run = self._runs[invocation_id]
        run.cancel_requested.set()
        if run.state not in {"completed", "cancelled"}:
            run.state = "cancelling"

    async def query(self, invocation_id: str) -> ModalInvocationStatus:
        run = self._runs.get(invocation_id)
        if run is None:
            return ModalInvocationStatus(invocation_id=invocation_id, state="unknown")
        return ModalInvocationStatus(invocation_id=invocation_id, state=run.state)  # type: ignore[arg-type]

    def was_cancelled(self, invocation_id: str) -> bool:
        return self._runs[invocation_id].cancel_requested.is_set()
