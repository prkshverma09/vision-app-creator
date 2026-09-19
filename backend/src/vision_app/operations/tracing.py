"""Best-effort tracing adapters with an allow-safe redaction boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from vision_app.contracts.ports import TraceSink

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = (
    "authorization",
    "auth",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "prompt",
    "media",
    "image",
    "bytes",
)
_URL_KEYS = ("url", "uri")


@dataclass(frozen=True)
class TraceRecord:
    name: str
    attributes: dict[str, str | int | bool]


class InMemoryTraceSink:
    """Deterministic component-test sink."""

    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def record(self, name: str, attributes: dict[str, str | int | bool]) -> None:
        safe = {key: _redact(key, value) for key, value in attributes.items()}
        self.records.append(TraceRecord(name=name, attributes=safe))


class SafeTraceSink:
    """Redacts at the final boundary and swallows all telemetry failures."""

    def __init__(self, sink: TraceSink) -> None:
        self._sink = sink

    def record(self, name: str, attributes: dict[str, str | int | bool]) -> None:
        safe = {key: _redact(key, value) for key, value in attributes.items()}
        try:
            self._sink.record(name, safe)
        except Exception:
            # Telemetry is explicitly non-critical; accounting happens outside tracing.
            return


class LogfireTraceSink:
    """Optional Logfire binding. Absence or outage degrades to a no-op."""

    def __init__(self) -> None:
        try:
            import logfire
        except ImportError:
            self._logfire: Any | None = None
        else:
            self._logfire = logfire

    def record(self, name: str, attributes: dict[str, str | int | bool]) -> None:
        if self._logfire is None:
            return
        safe = {key: _redact(key, value) for key, value in attributes.items()}
        try:
            self._logfire.info(name, **safe)
        except Exception:
            return


def _redact(key: str, value: object) -> str | int | bool:
    lowered = key.casefold()
    if isinstance(value, bytes | bytearray | memoryview):
        return _REDACTED
    if any(marker in lowered for marker in _SENSITIVE_KEYS):
        return _REDACTED
    if isinstance(value, str) and any(marker in lowered for marker in _URL_KEYS):
        try:
            parts = urlsplit(value)
        except ValueError:
            return _REDACTED
        if parts.query or parts.username or parts.password:
            return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))
    if isinstance(value, str | int | bool):
        return value
    return _REDACTED
