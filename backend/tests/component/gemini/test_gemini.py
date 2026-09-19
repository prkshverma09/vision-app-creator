"""CT-GEMINI component tests: scripted transport, retry, usage, coordinates, profile safety."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter

from vision_app.contracts.models import (
    AppSpec,
    BoxN,
    CompilerOutcome,
    ModelInvocationMetadata,
    MoneyMicrousd,
    PointN,
    SemanticObservation,
)
from vision_app.providers.gemini import (
    CompilerResult,
    GeminiCompilerModel,
    GeminiConfig,
    GeminiError,
    GeminiProfileError,
    GeminiVisualReasoner,
    ModelResponse,
    ScriptedTransport,
    create_transport,
)


class _FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance_ms(self, ms: int) -> None:
        self._now = self._now.replace(microsecond=self._now.microsecond + ms * 1000)


class _SequentialIdFactory:
    def __init__(self) -> None:
        self._n = 0

    def new(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n:04d}"


@pytest.fixture
def clock() -> _FixedClock:
    return _FixedClock()


@pytest.fixture
def id_factory() -> _SequentialIdFactory:
    return _SequentialIdFactory()


@pytest.fixture
def base_config() -> GeminiConfig:
    return GeminiConfig(
        api_key=None,
        model="gemini-test",
        profile="cpu",
        timeout_ms=5_000,
        max_retries=2,
        retry_base_ms=10,
        retry_max_ms=100,
    )


def _valid_tracked_rules_spec() -> dict:
    return {
        "kind": "tracked_rules",
        "schema_version": "1.0",
        "title": "Red crossing",
        "objective": "Flag vehicles crossing during red",
        "evidence_policy": {"before_ms": 3000, "after_ms": 3000},
        "approved_action_refs": [],
        "limits": {"max_duration_ms": 300000, "max_model_calls": 100},
        "rules": [
            {
                "rule_id": "rule-red",
                "capability_id": "tracked.red_phase_crossing",
                "object_classes": ["car", "bus", "truck"],
            }
        ],
    }


def test_compile_typed_success_returns_proposed_version(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    response = ModelResponse(
        content=_valid_tracked_rules_spec(),
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=200,
    )
    transport = ScriptedTransport([response])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("build a red light app", {}))

    assert isinstance(result, CompilerResult)
    assert result.outcome.kind == "proposed_version"
    version = result.outcome.version
    assert version.spec.kind == "tracked_rules"
    TypeAdapter(AppSpec).validate_python(version.spec.model_dump())
    assert version.capability_manifest == {"tracked.red_phase_crossing": "required"}
    assert version.model_manifest["compiler"] == base_config.model
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50
    assert result.usage.retry_count == 0
    assert result.usage.adapter_mode == "scripted"


def test_compile_malformed_provider_response_fails_validation(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    malformed = {
        "kind": "tracked_rules",
        "schema_version": "1.0",
        "title": "Bad",
        "objective": "Missing required rules list",
        "evidence_policy": {"before_ms": 3000, "after_ms": 3000},
        "approved_action_refs": [],
        "limits": {"max_duration_ms": 300000, "max_model_calls": 100},
        # missing rules
    }
    transport = ScriptedTransport([ModelResponse(
        content=malformed,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
    )])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("bad spec", {}))

    assert result.outcome.kind == "unsupported_request"
    assert result.outcome.code == "spec_validation_failed"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 10


def test_compile_retry_exhaustion_on_retryable_errors(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    retryable = GeminiError(code="rate_limited", message="too many requests", retryable=True, status_code=429)
    transport = ScriptedTransport([retryable, retryable, retryable])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("retry me", {}))

    assert result.outcome.kind == "unsupported_request"
    assert result.outcome.code == "rate_limited"
    # 1 initial attempt + 2 retries = 3 consumed script entries
    assert transport._index == 3
    assert result.usage.retry_count == 2


def test_compile_missing_usage_metadata_still_records_zero_tokens(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    response = ModelResponse(
        content=_valid_tracked_rules_spec(),
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=200,
    )
    transport = ScriptedTransport([response])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("missing usage", {}))

    assert result.outcome.kind == "proposed_version"
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


def test_compile_records_invocation_metadata_on_success(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    response = ModelResponse(
        content=_valid_tracked_rules_spec(),
        input_tokens=120,
        output_tokens=80,
        total_tokens=200,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=300,
    )
    transport = ScriptedTransport([response])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("with usage", {}))

    assert result.outcome.kind == "proposed_version"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 80
    TypeAdapter(ModelInvocationMetadata).validate_python(result.usage.model_dump())


def test_scene_proposal_normalizes_pixel_coordinates(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "lanes": {"lane1": [{"x": 0, "y": 0}, {"x": 1920, "y": 1080}]},
        "lines": {"stop_line": [{"x": 100, "y": 100}, {"x": 1820, "y": 100}]},
        "rois": {"signal": {"x1": 960, "y1": 540, "x2": 1060, "y2": 640}},
        "governing_signals": {"lane1": "signal"},
        "scene_fingerprint": "fp-1",
    }
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=50,
        output_tokens=40,
        total_tokens=90,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=100,
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport)

    proposal = asyncio.run(reasoner.propose_scene("src-1", "propose scene", (1920, 1080)))

    assert proposal.lanes["lane1"] == [PointN(x=0.0, y=0.0), PointN(x=1.0, y=1.0)]
    assert proposal.lines["stop_line"] == [PointN(x=100 / 1920, y=100 / 1080), PointN(x=1820 / 1920, y=100 / 1080)]
    assert proposal.rois["signal"] == BoxN(
        x1=960 / 1920, y1=540 / 1080, x2=1060 / 1920, y2=640 / 1080
    )


def test_scene_proposal_normalizes_thousand_scale_coordinates(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "lanes": {},
        "lines": {},
        "rois": {"roi": {"x1": 100, "y1": 100, "x2": 900, "y2": 900}},
        "governing_signals": {},
        "scene_fingerprint": "fp-2",
    }
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport)

    proposal = asyncio.run(reasoner.propose_scene("src-1", "propose scene", (640, 480)))

    # Values exceed source dimensions so normalizer treats them as thousand-scale.
    assert proposal.rois["roi"] == BoxN(x1=0.1, y1=0.1, x2=0.9, y2=0.9)


def test_classify_returns_typed_semantic_observation(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "condition_id": "cond-1",
        "decision": "present",
        "observed_ranges": [{"start_ms": 1000, "end_ms": 3000}],
        "evidence_refs": ["ev-1"],
    }
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=30,
        output_tokens=20,
        total_tokens=50,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=80,
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport)

    observation = asyncio.run(reasoner.classify("src-1", 0, 5000, "is a person present?"))

    assert observation.decision == "present"
    assert observation.requested_range.start_ms.root == 0
    assert observation.requested_range.end_ms.root == 5000
    assert len(observation.observed_ranges) == 1
    assert observation.invocation.provider == "gemini"
    assert observation.invocation.adapter_mode == "video"
    assert observation.invocation.input_tokens == 30


def test_classify_registers_provider_asset_for_cleanup(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    class _FakeAssetCleaner:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete(self, provider_ref: str) -> None:
            self.deleted.append(provider_ref)

    raw = {
        "condition_id": "cond-1",
        "decision": "absent",
        "observed_ranges": [],
        "evidence_refs": [],
    }
    cleaner = _FakeAssetCleaner()
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
        provider_file_ref="gemini-upload-ref-1",
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport, asset_cleaner=cleaner)

    observation = asyncio.run(reasoner.classify("src-1", 0, 1000, "prompt"))

    assert observation.decision == "absent"
    assert reasoner.provider_asset_refs() == frozenset({"gemini-upload-ref-1"})
    asyncio.run(reasoner.cleanup_assets())
    assert cleaner.deleted == ["gemini-upload-ref-1"]
    assert reasoner.provider_asset_refs() == frozenset()


def test_classify_rejects_out_of_window_observed_range(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "condition_id": "cond-1",
        "decision": "present",
        "observed_ranges": [{"start_ms": 0, "end_ms": 6000}],
        "evidence_refs": [],
    }
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport)

    with pytest.raises(GeminiError) as exc_info:
        asyncio.run(reasoner.classify("src-1", 1000, 5000, "is a person present?"))

    assert exc_info.value.code == "out_of_window_observation"


def test_retry_recovers_after_single_429(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    retryable = GeminiError(code="rate_limited", message="slow down", retryable=True, status_code=429)
    success = ModelResponse(
        content=_valid_tracked_rules_spec(),
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
    )
    transport = ScriptedTransport([retryable, success])
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("retry then succeed", {}))

    assert result.outcome.kind == "proposed_version"
    assert transport._index == 2
    assert result.usage.retry_count == 1


def test_create_transport_rejects_scripted_in_production() -> None:
    config = GeminiConfig(api_key="real-key", profile="production")
    script: list[ModelResponse | GeminiError] = []
    with pytest.raises(GeminiProfileError, match="scripted transport is prohibited"):
        create_transport(config, script=script)


def test_create_transport_rejects_missing_real_key_in_production() -> None:
    config = GeminiConfig(api_key=None, profile="production")
    with pytest.raises(GeminiProfileError, match="production profile requires a real provider API key"):
        create_transport(config)


def test_error_messages_do_not_leak_api_key(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    secret = "sk-real-key-12345"
    config = replace(base_config, api_key=secret)
    error = GeminiError(
        code="provider_error",
        message=f"request failed with key {secret}",
        retryable=False,
    )
    transport = ScriptedTransport([error])
    compiler = GeminiCompilerModel(config, clock, id_factory, transport=transport)

    result = asyncio.run(compiler.compile("leaky error", {}))

    assert result.outcome.kind == "unsupported_request"
    assert secret not in result.outcome.reason
    assert secret not in result.usage.prompt_hash
    # The error code/path is preserved without the secret payload.
    assert result.outcome.code == "provider_error"


def test_compiler_model_port_methods_exist(
    base_config: GeminiConfig, clock: _FixedClock, id_factory: _SequentialIdFactory
) -> None:
    response = ModelResponse(
        content={"kind": "needs_input", "questions": ["Which lane?"]},
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=10,
    )
    compiler = GeminiCompilerModel(base_config, clock, id_factory, transport=ScriptedTransport([response]))
    # Protocol checks require @runtime_checkable; verify structural conformance instead.
    assert callable(getattr(compiler, "compile", None))
    result = asyncio.run(compiler.compile("unclear instruction", {}))
    assert result.outcome.kind == "needs_input"
    assert result.outcome.questions == ["Which lane?"]
    TypeAdapter(CompilerOutcome).validate_python(result.outcome.model_dump())


def test_visual_reasoner_port_methods_exist(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "condition_id": "cond-1",
        "decision": "absent",
        "observed_ranges": [],
        "evidence_refs": [],
    }
    reasoner = GeminiVisualReasoner(
        base_config,
        clock,
        transport=ScriptedTransport([ModelResponse(
            content=raw,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            model=base_config.model,
            finish_reason="stop",
            duration_ms=10,
        )]),
    )
    assert callable(getattr(reasoner, "classify", None))
    observation = asyncio.run(reasoner.classify("src-1", 0, 1000, "prompt"))
    assert observation.decision == "absent"
    TypeAdapter(SemanticObservation).validate_python(observation.model_dump())


def test_visual_reasoner_metadata_is_typed_model_invocation(
    base_config: GeminiConfig, clock: _FixedClock
) -> None:
    raw = {
        "condition_id": "cond-1",
        "decision": "uncertain",
        "observed_ranges": [],
        "evidence_refs": [],
    }
    transport = ScriptedTransport([ModelResponse(
        content=raw,
        input_tokens=42,
        output_tokens=7,
        total_tokens=49,
        model=base_config.model,
        finish_reason="stop",
        duration_ms=120,
    )])
    reasoner = GeminiVisualReasoner(base_config, clock, transport=transport)

    observation = asyncio.run(reasoner.classify("src-1", 0, 1000, "prompt"))

    usage = observation.invocation
    TypeAdapter(ModelInvocationMetadata).validate_python(usage.model_dump())
    assert usage.input_tokens == 42
    assert usage.output_tokens == 7
    assert usage.retry_count == 0
    assert usage.estimated_cost == MoneyMicrousd(0)
