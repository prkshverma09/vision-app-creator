"""VisualReasoner port adapter backed by a Gemini model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vision_app.contracts.models import (
    BoxN,
    ModelInvocationMetadata,
    MoneyMicrousd,
    PointN,
    ResourceId,
    SemanticObservation,
    SourceTimeMs,
    TimeRange,
)
from vision_app.contracts.ports import ProviderAssetCleaner, VisualReasoner

from .config import GeminiConfig
from .normalizer import normalize_box, normalize_point
from .transport import GeminiError, GeminiTransport, ModelResponse, create_transport, with_retry


@dataclass(frozen=True)
class SceneProposal:
    """Typed scene proposal normalized to C0 coordinates plus invocation metadata."""

    lanes: dict[str, list[PointN]]
    lines: dict[str, list[PointN]]
    rois: dict[str, BoxN]
    governing_signals: dict[str, str]
    scene_fingerprint: str
    invocation: ModelInvocationMetadata


class GeminiVisualReasoner(VisualReasoner):
    """Scene proposal, clip classification, and candidate review behind the VisualReasoner port."""

    def __init__(
        self,
        config: GeminiConfig,
        clock: Any,
        *,
        transport: GeminiTransport | None = None,
        script: list[ModelResponse | GeminiError] | None = None,
        asset_cleaner: ProviderAssetCleaner | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._transport = transport or create_transport(config, script=script)
        self._asset_cleaner = asset_cleaner
        self._provider_refs: set[str] = set()

    def _usage(
        self,
        response: ModelResponse,
        retry_count: int,
        duration_ms: int,
        adapter_mode: str,
    ) -> ModelInvocationMetadata:
        return ModelInvocationMetadata(
            provider=self._config.provider_name,
            model=self._config.model,
            revision=self._config.revision,
            prompt_hash=response.request_id or "sha256-unknown",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            duration_ms=duration_ms,
            retry_count=retry_count,
            adapter_mode=adapter_mode,  # type: ignore[arg-type]
            estimated_cost=MoneyMicrousd(0),
        )

    def _register_provider_ref(self, provider_ref: str) -> None:
        """Track a provider-side uploaded asset for later cleanup."""
        self._provider_refs.add(provider_ref)

    def provider_asset_refs(self) -> frozenset[str]:
        return frozenset(self._provider_refs)

    async def cleanup_assets(self) -> None:
        """Delete all provider-side assets registered through this reasoner."""
        if self._asset_cleaner is None:
            return
        for ref in list(self._provider_refs):
            await self._asset_cleaner.delete(ref)
            self._provider_refs.discard(ref)

    async def propose_scene(
        self,
        source_id: str,
        prompt: str,
        frame_size: tuple[int, int],
    ) -> SceneProposal:
        """Propose lanes/lines/ROIs/signals for a source and normalize to C0 geometry."""
        width, height = frame_size
        request_prompt = _build_scene_prompt(source_id, prompt)
        schema = _scene_proposal_schema()
        started = self._clock.now()

        response, retry_count = await with_retry(
            self._config,
            lambda: self._transport.send(
                request_prompt,
                response_schema=schema,
                timeout_ms=self._config.timeout_ms,
            ),
            request_prompt,
        )

        duration_ms = int((self._clock.now() - started).total_seconds() * 1000)
        usage = self._usage(response, retry_count, duration_ms, adapter_mode="image")
        content = response.content
        if not isinstance(content, dict):
            raise GeminiError(
                code="invalid_scene_response",
                message="scene proposal returned a non-object",
                retryable=False,
            )

        lanes: dict[str, list[PointN]] = {}
        for lane_id, points in content.get("lanes", {}).items():
            lanes[lane_id] = [normalize_point(p, width, height) for p in points]

        lines: dict[str, list[PointN]] = {}
        for line_id, points in content.get("lines", {}).items():
            lines[line_id] = [normalize_point(p, width, height) for p in points]

        rois: dict[str, BoxN] = {}
        for roi_id, box in content.get("rois", {}).items():
            rois[roi_id] = normalize_box(box, width, height)

        return SceneProposal(
            lanes=lanes,
            lines=lines,
            rois=rois,
            governing_signals=content.get("governing_signals", {}),
            scene_fingerprint=content.get("scene_fingerprint", ""),
            invocation=usage,
        )

    async def classify(
        self,
        source_id: str,
        start_ms: int,
        end_ms: int,
        prompt: str,
    ) -> SemanticObservation:
        """Classify a bounded clip and return a C0 SemanticObservation."""
        if start_ms >= end_ms:
            raise ValueError("start_ms must be less than end_ms")
        request_prompt = _build_classification_prompt(source_id, start_ms, end_ms, prompt)
        schema = _semantic_observation_schema()
        started = self._clock.now()

        response, retry_count = await with_retry(
            self._config,
            lambda: self._transport.send(
                request_prompt,
                response_schema=schema,
                timeout_ms=self._config.timeout_ms,
            ),
            request_prompt,
        )

        duration_ms = int((self._clock.now() - started).total_seconds() * 1000)
        usage = self._usage(response, retry_count, duration_ms, adapter_mode="video")

        if response.provider_file_ref:
            self._register_provider_ref(response.provider_file_ref)

        content = response.content
        if not isinstance(content, dict):
            raise GeminiError(
                code="invalid_classification_response",
                message="classification returned a non-object",
                retryable=False,
            )

        observed_ranges_data = content.get("observed_ranges", [])
        observed_ranges: list[TimeRange] = []
        for item in observed_ranges_data:
            try:
                observed_ranges.append(
                    TimeRange(
                        start_ms=SourceTimeMs(item["start_ms"]),
                        end_ms=SourceTimeMs(item["end_ms"]),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise GeminiError(
                    code="invalid_observed_range",
                    message=f"Invalid observed range: {exc}",
                    retryable=False,
                ) from exc

        # Enforce source-bounded intervals.
        for r in observed_ranges:
            if r.start_ms.root < start_ms or r.end_ms.root > end_ms:
                raise GeminiError(
                    code="out_of_window_observation",
                    message=f"observed range {r.start_ms.root}-{r.end_ms.root} outside requested window {start_ms}-{end_ms}",
                    retryable=False,
                )

        decision: str = content.get("decision", "uncertain")
        if decision not in {"present", "absent", "uncertain"}:
            raise GeminiError(
                code="invalid_decision",
                message=f"unknown decision value: {decision}",
                retryable=False,
            )

        return SemanticObservation(
            condition_id=ResourceId(content.get("condition_id", "cond-unknown")),
            decision=decision,  # type: ignore[arg-type]
            requested_range=TimeRange(start_ms=SourceTimeMs(start_ms), end_ms=SourceTimeMs(end_ms)),
            observed_ranges=observed_ranges,
            evidence_refs=[ResourceId(ref) for ref in content.get("evidence_refs", [])],
            invocation=usage,
        )

    async def review_candidate(self, prompt: str, *, evidence_refs: list[str]) -> dict[str, Any]:
        """Review a rule candidate; returns a typed review result dictionary."""
        request_prompt = _build_review_prompt(prompt, evidence_refs)
        schema = _review_schema()
        started = self._clock.now()

        response, retry_count = await with_retry(
            self._config,
            lambda: self._transport.send(
                request_prompt,
                response_schema=schema,
                timeout_ms=self._config.timeout_ms,
            ),
            request_prompt,
        )

        duration_ms = int((self._clock.now() - started).total_seconds() * 1000)
        usage = self._usage(response, retry_count, duration_ms, adapter_mode="image")
        content = response.content
        if not isinstance(content, dict):
            raise GeminiError(
                code="invalid_review_response",
                message="review returned a non-object",
                retryable=False,
            )
        return {
            "agreement": content.get("agreement", "inconclusive"),
            "reason": content.get("reason", ""),
            "invocation": usage,
        }


def _build_scene_prompt(source_id: str, prompt: str) -> str:
    return (
        f"Propose scene geometry for source {source_id}.\n"
        f"Instruction: {prompt}\n"
        "Return JSON with lanes, lines, rois, governing_signals, scene_fingerprint. "
        "Coordinates may be normalized [0,1], pixels, or [0,1000]; include explicit keys."
    )


def _build_classification_prompt(source_id: str, start_ms: int, end_ms: int, prompt: str) -> str:
    return (
        f"Classify clip {source_id} from {start_ms}ms to {end_ms}ms.\n"
        f"Question: {prompt}\n"
        "Return JSON with condition_id, decision in {present,absent,uncertain}, "
        "and observed_ranges bounded by the requested window."
    )


def _build_review_prompt(prompt: str, evidence_refs: list[str]) -> str:
    return (
        f"Review candidate evidence: {evidence_refs}\n"
        f"Question: {prompt}\n"
        "Return JSON with agreement in {agree,disagree,inconclusive} and reason."
    )


def _scene_proposal_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "lanes": {"type": "object", "additionalProperties": {"type": "array", "items": {"$ref": "#/definitions/point"}}},
            "lines": {"type": "object", "additionalProperties": {"type": "array", "items": {"$ref": "#/definitions/point"}}},
            "rois": {"type": "object", "additionalProperties": {"$ref": "#/definitions/box"}},
            "governing_signals": {"type": "object", "additionalProperties": {"type": "string"}},
            "scene_fingerprint": {"type": "string"},
        },
        "definitions": {
            "point": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}, "required": ["x", "y"]},
            "box": {"type": "object", "properties": {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"}}, "required": ["x1", "y1", "x2", "y2"]},
        },
    }


def _semantic_observation_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "condition_id": {"type": "string"},
            "decision": {"enum": ["present", "absent", "uncertain"]},
            "observed_ranges": {
                "type": "array",
                "items": {"type": "object", "properties": {"start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}}, "required": ["start_ms", "end_ms"]},
            },
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["condition_id", "decision", "observed_ranges"],
    }


def _review_schema() -> dict[str, Any]:
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "agreement": {"enum": ["agree", "disagree", "inconclusive"]},
            "reason": {"type": "string"},
        },
        "required": ["agreement"],
    }
