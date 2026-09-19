"""Real Pydantic-AI based transport.  Only loaded when pydantic-ai is installed."""

from __future__ import annotations

import json
from typing import Any, cast

from .config import GeminiConfig
from .transport import GeminiError, GeminiTransport, ModelResponse


class PydanticAITransport(GeminiTransport):
    def __init__(self, config: GeminiConfig) -> None:
        self._config = config
        try:
            import pydantic_ai as pai
            from pydantic_ai.models.gemini import GeminiModel
        except Exception as exc:  # pragma: no cover
            raise GeminiError(
                code="dependency_missing",
                message=f"pydantic-ai is not installed: {exc}",
                retryable=False,
            ) from exc

        self._pai = pai
        self._model = GeminiModel(config.model, api_key=config.api_key or "")

    async def send(
        self,
        prompt: str,
        *,
        images: list[bytes] | None = None,
        response_schema: dict[str, Any] | None = None,
        timeout_ms: int | None = None,
    ) -> ModelResponse:
        if response_schema is None:
            result_type = str
        else:
            # Build a runtime pydantic model from the JSON schema so structured output is enforced.
            result_type = self._pai._pydantic._pydantic_model_from_json_schema(json.dumps(response_schema))

        messages = []
        if images:
            for img in images:
                messages.append(self._pai.BinaryContent(data=img, media_type="image/jpeg"))
        messages.append(self._pai.UserPromptPart(content=prompt))
        agent = self._pai.Agent(self._model, result_type=result_type)
        try:
            result = await agent.run(messages)
        except Exception as exc:
            raise self._translate(exc) from exc

        usage = result.usage()
        return ModelResponse(
            content=self._result_to_dict(result.data),
            input_tokens=usage.request_tokens or 0,
            output_tokens=usage.response_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            model=self._config.model,
            finish_reason="stop",
            duration_ms=0,
        )

    def _translate(self, exc: BaseException) -> GeminiError:
        from google.api_core import exceptions as google_exceptions

        if isinstance(exc, TimeoutError):
            return GeminiError(code="timeout", message="Pydantic AI call timed out", retryable=True)
        if isinstance(exc, google_exceptions.ResourceExhausted):
            return GeminiError(code="rate_limited", message=str(exc), retryable=True, status_code=429)
        if isinstance(exc, google_exceptions.InvalidArgument):
            return GeminiError(code="invalid_argument", message=str(exc), retryable=False, status_code=400)
        return GeminiError(code="pydantic_ai_error", message=str(exc), retryable=True)

    @staticmethod
    def _result_to_dict(data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return data
        if hasattr(data, "model_dump"):
            return cast(dict[str, Any], data.model_dump())
        return {"result": str(data)}
