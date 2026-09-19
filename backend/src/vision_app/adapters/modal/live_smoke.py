"""Operator-approved live health smoke: python -m vision_app.adapters.modal.live_smoke."""
from __future__ import annotations

import importlib
import os


def main() -> int:
    missing = [
        name
        for name in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"missing required credentials: {', '.join(missing)}")
    try:
        modal = importlib.import_module("modal")
    except ImportError as exc:
        raise SystemExit("install the optional modal package before live smoke") from exc
    function = modal.Function.from_name("vision-app-creator", "health_check")
    result = function.remote()
    if result.get("status") != "ok":
        raise SystemExit(f"unhealthy Modal deployment: {result!r}")
    print("Modal health smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
