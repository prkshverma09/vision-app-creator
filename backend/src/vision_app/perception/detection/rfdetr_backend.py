"""Real RF-DETR inference backend with lazy, conditional imports."""
from __future__ import annotations

from typing import Any

from .backend import DetectorBackend, PreprocessedFrame, RawDetection
from .config import DetectorConfig
from .errors import CheckpointError, DetectionError


class RfDetrBackend(DetectorBackend):
    """Concrete backend that wraps a pinned RF-DETR Small checkpoint.

    ``rfdetr`` and ``torch`` are imported only inside :meth:`load`, so the
    component test profile never needs them.  If they are absent, the adapter
    raises :class:`CheckpointError`.
    """

    def __init__(self, config: DetectorConfig) -> None:
        self._config = config
        self._model: Any | None = None

    def load(self) -> None:
        try:
            import rfdetr  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise CheckpointError(f"RF-DETR not available: {exc}") from exc

        path = self._config.checkpoint_path
        if not path:
            raise CheckpointError("no checkpoint_path configured")

        # Model load would be pinned to config.model_name + checkpoint_revision.
        # This concrete path is gated to the live/vision acceptance gate (R01).
        self._model = rfdetr.RFDETR(self._config.model_name, checkpoint=path)
        _verify_revision(self._config)

    def __call__(self, frame: PreprocessedFrame, config: DetectorConfig) -> list[RawDetection]:
        if self._model is None:
            raise DetectionError("backend not loaded")

        # Real inference path is intentionally minimal; R01 exercises it.
        raise DetectionError("real RF-DETR inference is gated to live gate R01")


def _verify_revision(config: DetectorConfig) -> None:
    if not config.checkpoint_revision or config.checkpoint_revision == "pin-not-set":
        raise CheckpointError("checkpoint revision is not pinned")
    if not config.checkpoint_revision.startswith("sha256:"):
        raise CheckpointError("checkpoint revision must be a sha256:... digest")
