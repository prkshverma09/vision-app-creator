"""Transport abstraction, retry/timeout/error translation, and scripted test double."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import GeminiConfig, GeminiProfileError


class GeminiError(Exception):
    """Normalized provider/transient error with retryability and safe client messaging."""

    def __init__(self, code: str, message: str, retryable: bool, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


def translate_exception(exc: BaseException) -> GeminiError:
    """Convert SDK/network exceptions into a normalized, retry-aware error."""
    # Imported lazily so component tests never need the real SDK.
    try:
        from google.api_core import exceptions as google_exceptions
        from google.generativeai import types as genai_types
    except Exception:  # pragma: no cover - optional dependency path
        google_exceptions = None
        genai_types = None

    if google_exceptions is not None and isinstance(exc, google_exceptions.GoogleAPIError):
        status = exc.code if hasattr(exc, "code") else None
        retryable = status in (429, 500, 502, 503, 504)
        return GeminiError(
            code=f"google_api_{status or 'error'}",
            message=str(exc),
            retryable=retryable,
            status_code=status,
        )
    if genai_types is not None and isinstance(exc, genai_types.BlockedPromptException):
        return GeminiError(code="blocked_prompt", message=str(exc), retryable=False, status_code=400)
    if isinstance(exc, TimeoutError):
        return GeminiError(code="timeout", message="Provider call timed out", retryable=True)
    if isinstance(exc, asyncio.TimeoutError):
        return GeminiError(code="timeout", message="Provider call timed out", retryable=True)
    return GeminiError(code="provider_error", message=str(exc), retryable=True)


@dataclass(frozen=True)
class ModelResponse:
    """Normalized model response after provider-specific decoding."""

    content: dict[str, Any]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    finish_reason: str | None
    duration_ms: int
    request_id: str = ""
    provider_file_ref: str | None = None


class GeminiTransport(Protocol):
    """Provider-specific transport normalized behind this port."""

    async def send(
        self,
        prompt: str,
        *,
        images: list[bytes] | None = None,
        response_schema: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> ModelResponse: ...


@dataclass
class ScriptedTransport:
    """Deterministic test double for component tests.  Never selected in production."""

    script: list[ModelResponse | GeminiError]
    _index: int = field(default=0, init=False, repr=False)

    async def send(
        self,
        prompt: str,
        *,
        images: list[bytes] | None = None,
        response_schema: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> ModelResponse:
        if self._index >= len(self.script):
            raise GeminiError(
                code="script_exhausted",
                message=f"Scripted transport exhausted after {self._index} calls",
                retryable=False,
            )
        step = self.script[self._index]
        self._index += 1
        if isinstance(step, GeminiError):
            raise step
        return step


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


async def with_retry(
    config: GeminiConfig,
    operation: Any,
    prompt: str,
) -> tuple[ModelResponse, int]:
    """Execute operation with bounded retries, exponential backoff, and total timeout.

    Returns the final response and the retry count actually expended.
    """
    deadline = time.monotonic() + (config.timeout_ms / 1000.0)
    last_error: GeminiError | None = None

    for attempt in range(config.max_retries + 1):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GeminiError(
                    code="timeout",
                    message="Total retry budget exceeded before provider call",
                    retryable=False,
                )
            call_timeout = min(
                config.timeout_ms if config.timeout_ms > 0 else 30_000,
                int(remaining * 1000),
            )
            response = await asyncio.wait_for(operation(), timeout=call_timeout / 1000.0)
            return response, attempt
        except GeminiError as e:
            last_error = e
            if not e.retryable or attempt >= config.max_retries:
                break
            backoff = min(config.retry_base_ms * (2**attempt), config.retry_max_ms)
            await asyncio.sleep(backoff / 1000.0)
        except Exception as e:
            last_error = translate_exception(e)
            if not last_error.retryable or attempt >= config.max_retries:
                break
            backoff = min(config.retry_base_ms * (2**attempt), config.retry_max_ms)
            await asyncio.sleep(backoff / 1000.0)

    assert last_error is not None
    raise last_error


def create_transport(
    config: GeminiConfig,
    *,
    script: list[ModelResponse | GeminiError] | None = None,
) -> GeminiTransport:
    """Build a transport for the given config, enforcing production profile rules."""
    if config.is_production() and script is not None:
        raise GeminiProfileError("scripted transport is prohibited in production profile")
    if script is not None:
        return ScriptedTransport(script)
    if config.is_production() and not config.api_key:
        raise GeminiProfileError("production profile requires a real provider API key")

    # Real transports are constructed lazily through optional imports.
    try:
        from .pydantic_ai_transport import PydanticAITransport

        return PydanticAITransport(config)
    except Exception:  # pragma: no cover - real dependency optional for tests
        pass
    raise GeminiError(
        code="transport_unavailable",
        message="No real transport available and no scripted transport requested",
        retryable=False,
    )
