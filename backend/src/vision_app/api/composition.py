"""Public API composition surface.

This thin module re-exports the backend application factory so that API-layer
composition is discoverable under ``vision_app.api`` while the detailed wiring
lives in ``vision_app.bootstrap``.
"""

from __future__ import annotations

from typing import Any

from vision_app.bootstrap import create_app as _create_app


def create_app(profile: str, settings: dict[str, Any] | None = None) -> Any:
    """Create and configure a Vision App Creator FastAPI application.

    ``profile`` selects the runtime adapter set (e.g. ``"local"``). ``settings``
    is a trusted dictionary supplied by the test harness or launcher.
    """
    return _create_app(profile, settings)
