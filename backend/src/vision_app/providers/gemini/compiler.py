"""CompilerModel port adapter backed by a Gemini model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter, ValidationError

from vision_app.contracts.capabilities import CAPABILITIES
from vision_app.contracts.models import (
    AppSpec,
    AppVersion,
    CompilerOutcome,
    ModelInvocationMetadata,
    MoneyMicrousd,
    NeedsInput,
    ProposedVersion,
    ResourceId,
    UnsupportedRequest,
    UtcTimestamp,
)
from vision_app.contracts.ports import CompilerModel

from .config import GeminiConfig
from .transport import GeminiError, GeminiTransport, ModelResponse, create_transport, with_retry


@dataclass(frozen=True)
class CompilerResult:
    """Typed compilation output containing the C0 outcome plus captured usage metadata."""

    outcome: CompilerOutcome
    usage: ModelInvocationMetadata


class GeminiCompilerModel(CompilerModel):
    """Turn a user instruction and optional scene context into a typed CompilerOutcome."""

    def __init__(
        self,
        config: GeminiConfig,
        clock: Any,
        id_factory: Any,
        *,
        transport: GeminiTransport | None = None,
        script: list[ModelResponse | GeminiError] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._id_factory = id_factory
        self._transport = transport or create_transport(config, script=script)

    def _usage(
        self, prompt: str, response: ModelResponse, retry_count: int, duration_ms: int
    ) -> ModelInvocationMetadata:
        return ModelInvocationMetadata(
            provider=self._config.provider_name,
            model=self._config.model,
            revision=self._config.revision,
            prompt_hash=_prompt_hash(prompt),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            duration_ms=duration_ms,
            retry_count=retry_count,
            adapter_mode="scripted" if self._config.profile in ("cpu", "test") else "structured",
            estimated_cost=MoneyMicrousd(0),
        )

    async def compile(self, instruction: str, context: dict[str, Any]) -> CompilerResult:
        prompt = _build_compiler_prompt(instruction, context)
        schema = _app_spec_schema()
        started = self._clock.now()

        try:
            response, retry_count = await with_retry(
                self._config,
                lambda: self._transport.send(
                    prompt,
                    response_schema=schema,
                    timeout_ms=self._config.timeout_ms,
                ),
                prompt,
            )
        except GeminiError as exc:
            # A translated provider error is surfaced as an unsupported request so the builder
            # can report it without leaking secrets or SDK internals.
            error_usage = ModelInvocationMetadata(
                provider=self._config.provider_name,
                model=self._config.model,
                revision=self._config.revision,
                prompt_hash=_prompt_hash(prompt),
                input_tokens=0,
                output_tokens=0,
                duration_ms=0,
                retry_count=self._config.max_retries,
                adapter_mode="scripted" if self._config.profile in ("cpu", "test") else "structured",
                estimated_cost=MoneyMicrousd(0),
            )
            return CompilerResult(
                outcome=UnsupportedRequest(
                    kind="unsupported_request",
                    code=exc.code,
                    reason=_redact_secrets(exc.message, self._config.api_key),
                ),
                usage=error_usage,
            )

        duration_ms = int((self._clock.now() - started).total_seconds() * 1000)
        usage = self._usage(prompt, response, retry_count, duration_ms)

        content = response.content
        if not isinstance(content, dict):
            return CompilerResult(
                outcome=UnsupportedRequest(
                    kind="unsupported_request",
                    code="invalid_response_type",
                    reason="model returned a non-object response",
                ),
                usage=usage,
            )

        outcome_kind = content.get("kind")
        if outcome_kind == "needs_input":
            questions = content.get("questions", [])
            if not isinstance(questions, list) or not questions:
                return CompilerResult(
                    outcome=UnsupportedRequest(
                        kind="unsupported_request",
                        code="invalid_needs_input",
                        reason="needs_input must contain a non-empty questions list",
                    ),
                    usage=usage,
                )
            return CompilerResult(
                outcome=NeedsInput(kind="needs_input", questions=[str(q) for q in questions]),
                usage=usage,
            )

        if outcome_kind == "unsupported_request":
            return CompilerResult(
                outcome=UnsupportedRequest(
                    kind="unsupported_request",
                    code=str(content.get("code", "unsupported")),
                    reason=str(content.get("reason", "request unsupported")),
                ),
                usage=usage,
            )

        if outcome_kind == "proposed_version":
            content = content.get("spec", content)

        # Validate the returned object as an AppSpec.
        typed_spec: AppSpec
        try:
            typed_spec = TypeAdapter(AppSpec).validate_python(content)
        except ValidationError as exc:
            return CompilerResult(
                outcome=UnsupportedRequest(
                    kind="unsupported_request",
                    code="spec_validation_failed",
                    reason=str(exc),
                ),
                usage=usage,
            )

        app_id = ResourceId(_id_or_new(context, "app_id", self._id_factory, "app"))
        version_id = ResourceId(_id_or_new(context, "version_id", self._id_factory, "version"))
        created_by = ResourceId(_id_or_new(context, "created_by", self._id_factory, "user"))
        workspace_id = ResourceId(str(context.get("workspace_id") or "workspace-a"))

        capability_manifest = _capability_manifest(typed_spec)
        model_manifest = {"compiler": self._config.model, "compiler_revision": self._config.revision}
        validation_report = ["compiled"]

        version = AppVersion(
            id=version_id,
            app_id=app_id,
            workspace_id=workspace_id,
            parent_id=None,
            spec=typed_spec,
            capability_manifest=capability_manifest,
            model_manifest=model_manifest,
            validation_report=validation_report,
            created_by=created_by,
            created_at=_utc_timestamp(self._clock.now()),
        )

        return CompilerResult(
            outcome=ProposedVersion(
                kind="proposed_version",
                version=version,
            ),
            usage=usage,
        )


def _utc_timestamp(value: datetime) -> UtcTimestamp:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return UtcTimestamp(value)


def _id_or_new(context: dict[str, Any], key: str, id_factory: Any, prefix: str) -> str:
    value = context.get(key)
    if value:
        return str(value)
    return str(id_factory.new(prefix))


def _build_compiler_prompt(instruction: str, context: dict[str, Any]) -> str:
    capabilities = ", ".join(sorted(CAPABILITIES))
    scene = context.get("scene", {})
    scene_text = json.dumps(scene, default=str) if scene else "none"
    return (
        f"You are a video-intelligence compiler. Available capabilities: {capabilities}.\n"
        f"Scene context: {scene_text}\n"
        f"Instruction: {instruction}\n"
        "Return a JSON object matching the AppSpec schema. If information is missing, "
        "return {\"kind\":\"needs_input\",\"questions\":[...]}. If the request is outside "
        "supported capabilities, return {\"kind\":\"unsupported_request\",\"code\":...,\"reason\":...}."
    )


def _app_spec_schema() -> dict[str, Any]:
    from vision_app.contracts.models import AppSpec

    schema = TypeAdapter(AppSpec).json_schema()
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    return schema


def _capability_manifest(spec: Any) -> dict[str, str]:
    from vision_app.contracts.models import SemanticWindowsSpec, TrackedRulesSpec

    manifest: dict[str, str] = {}
    if isinstance(spec, TrackedRulesSpec):
        for rule in spec.rules:
            manifest[rule.capability_id] = "required"
    elif isinstance(spec, SemanticWindowsSpec):
        manifest["semantic.visible_condition"] = "required"
    return manifest


def _prompt_hash(prompt: str) -> str:
    import hashlib

    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _redact_secrets(text: str, api_key: str | None) -> str:
    if not api_key:
        return text
    # Simple substring redaction; also redact common credential patterns.
    redacted = text.replace(api_key, "***REDACTED***")
    redacted = re.sub(r"AIza[\w-]{35,}", "***REDACTED***", redacted)
    return redacted
