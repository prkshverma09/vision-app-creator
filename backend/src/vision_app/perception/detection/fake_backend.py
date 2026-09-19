"""Test-only fake detector backend; never used in production composition."""
from __future__ import annotations

from .backend import DetectorBackend, PreprocessedFrame, RawDetection
from .config import DetectorConfig
from .errors import DetectionError


class FakeDetectorBackend(DetectorBackend):
    """Scriptable inference backend for CT-DETECT.

    Accepts either:
    - ``responses``: an iterable of response lists, returned in order across calls.
    - ``raises``: an exception (or exception class/message) raised on every call.
    - ``record_inputs``: a list that receives the preprocessed frame bytes for each call.
    """

    def __init__(
        self,
        responses: list[list[RawDetection]] | None = None,
        raises: DetectionError | type[DetectionError] | str | None = None,
        record_inputs: list[bytes] | None = None,
    ) -> None:
        self._responses = list(responses) if responses else []
        self._raises = raises
        self._record_inputs = record_inputs
        self.load_count = 0
        self._closed = False

    def load(self) -> None:
        self.load_count += 1

    def __call__(self, frame: PreprocessedFrame, config: DetectorConfig) -> list[RawDetection]:
        if self._record_inputs is not None:
            self._record_inputs.append(frame.data)
        if self._raises is not None:
            if isinstance(self._raises, str):
                raise DetectionError(self._raises)
            if isinstance(self._raises, type):
                raise self._raises()
            raise self._raises
        if not self._responses:
            return []
        return self._responses.pop(0)
