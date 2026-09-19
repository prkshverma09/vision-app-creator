"""Modal deployment entrypoints.

The module remains importable without the optional ``modal`` package. Production
composition supplies ``VISION_APP_MODAL_RUNNER`` as ``module:async_callable``;
the callable consumes a validated ModalRunInput and yields ModalStreamItem values.
"""
from __future__ import annotations

import importlib
import inspect
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from .models import ModalRunInput, ModalStreamItem

Runner = Callable[[ModalRunInput], AsyncIterator[ModalStreamItem]]


def health() -> dict[str, str]:
    return {"status": "ok", "adapter": "modal", "runtime": "vision_app.runtime"}


def load_runner(path: str | None = None) -> Runner:
    target = path or os.environ.get("VISION_APP_MODAL_RUNNER")
    if not target or ":" not in target:
        raise RuntimeError("VISION_APP_MODAL_RUNNER must be set to module:callable")
    module_name, name = target.split(":", 1)
    value = getattr(importlib.import_module(module_name), name)
    if not callable(value):
        raise TypeError("configured Modal runner is not callable")
    return value  # type: ignore[no-any-return]


async def execute(payload: dict[str, Any], runner: Runner | None = None) -> list[dict[str, Any]]:
    """Validate input and execute the shared B07-composed runner."""
    value = ModalRunInput.model_validate(payload)
    selected = runner or load_runner()
    produced = selected(value)
    if inspect.isawaitable(produced):
        produced = await produced
    return [item.model_dump(mode="json") async for item in produced]


try:  # Optional cloud binding; component/integration tests never need Modal installed.
    modal_sdk: Any = importlib.import_module("modal")
except ImportError:  # pragma: no cover - exercised by ordinary import without modal
    modal_sdk = None

if modal_sdk is not None:  # pragma: no cover - definition validation/live smoke only
    image = (
        modal_sdk.Image.debian_slim(python_version="3.12")
        .apt_install("ffmpeg")
        .pip_install_from_pyproject("pyproject.toml", optional_dependencies=["vision", "cloud"])
        .add_local_python_source("vision_app")
    )
    app = modal_sdk.App("vision-app-creator")
    checkpoint_volume = modal_sdk.Volume.from_name(
        "vision-app-checkpoints", create_if_missing=False
    )

    @app.function(image=image, timeout=900, cpu=2.0, memory=4096)  # type: ignore[misc]
    def health_check() -> dict[str, str]:
        return health()

    @app.function(  # type: ignore[misc]
        image=image,
        gpu="L4",
        timeout=3600,
        scaledown_window=300,
        volumes={"/models": checkpoint_volume},
        secrets=[modal_sdk.Secret.from_name("vision-app-runtime")],
    )
    async def run_gpu(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return await execute(payload)
