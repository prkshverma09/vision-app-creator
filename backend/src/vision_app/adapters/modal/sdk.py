"""Optional Modal SDK client. Importing this module does not initialize cloud credentials."""
from __future__ import annotations

import asyncio
import importlib
from collections.abc import AsyncIterator
from typing import Any

from .models import ModalInvocationStatus, ModalRunInput, ModalStreamItem


class ModalSdkClient:
    """Thin async wrapper around a deployed Modal function.

    SDK objects can be injected for tests. Calls are spawned so their IDs can be durably
    recorded and cancelled by B08 before output collection finishes.
    """

    def __init__(
        self,
        function: Any | None = None,
        *,
        app_name: str = "vision-app-creator",
        function_name: str = "run_gpu",
    ) -> None:
        if function is None:
            try:
                modal = importlib.import_module("modal")
            except ImportError as exc:
                raise RuntimeError(
                    "Modal SDK is not installed; use FakeModalClient locally"
                ) from exc
            function = modal.Function.from_name(app_name, function_name)
        self._function = function
        self._calls: dict[str, Any] = {}
        self._states: dict[str, str] = {}

    async def submit(self, value: ModalRunInput, *, idempotency_key: str) -> str:
        call = await self._function.spawn.aio(value.model_dump(mode="json"))
        invocation_id = str(call.object_id)
        self._calls[invocation_id] = call
        self._states[invocation_id] = "running"
        return invocation_id

    async def stream(self, invocation_id: str) -> AsyncIterator[ModalStreamItem]:
        call = self._calls[invocation_id]
        try:
            values = await call.get.aio()
            for value in values:
                yield ModalStreamItem.model_validate(value)
            self._states[invocation_id] = "completed"
        except asyncio.CancelledError:
            self._states[invocation_id] = "cancelled"
            raise
        except Exception:
            self._states[invocation_id] = "failed"
            raise

    async def cancel(self, invocation_id: str) -> None:
        call = self._calls[invocation_id]
        self._states[invocation_id] = "cancelling"
        await call.cancel.aio()

    async def query(self, invocation_id: str) -> ModalInvocationStatus:
        return ModalInvocationStatus(
            invocation_id=invocation_id,
            state=self._states.get(invocation_id, "unknown"),  # type: ignore[arg-type]
        )
