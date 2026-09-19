"""Bounded typed builder-agent orchestration.

Pydantic AI is an optional deployment dependency.  The orchestration boundary is
kept compatible with it (typed dependencies/tools/results), while component tests
use the C0 scripted CompilerModel and make no cloud calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from vision_app.contracts.models import (
    AppSpec,
    AppVersion,
    BuildTurn,
    NeedsInput,
    ProposedVersion,
    ResourceId,
    UnsupportedRequest,
)
from vision_app.contracts.ports import CompilerModel, PreviewService, SceneInspector
from vision_app.validation.registry import REGISTRY, CapabilityRegistry

from .ports import BuildTurnStore, SpecValidator

MAX_REPAIR_ATTEMPTS = 2
TOOL_NAMES = ("inspect_scene", "list_capabilities", "validate_spec", "start_preview")


def pydantic_ai_agent_type() -> type[Any] | None:
    """Return the optional Pydantic AI Agent type without making it a core dependency."""
    try:
        from pydantic_ai import Agent
    except ImportError:  # pragma: no cover - dependency-minimal installations
        return None
    return cast(type[Any] | None, Agent)


class BuilderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    app_id: str
    workspace_id: str | None = None
    instruction: str = Field(min_length=1)
    base_revision: int = Field(ge=0)
    base_version_id: str | None = None
    source_id: str | None = None
    principal: Any = None
    preview: bool = False
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)


@dataclass
class TypedBuilderTools:
    """Fixed allowlist of typed tools; model text cannot register another tool."""

    inspector: SceneInspector
    registry: CapabilityRegistry
    validator: SpecValidator
    preview: PreviewService
    request: BuilderRequest
    progress: list[str]

    @property
    def names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    async def inspect_scene(self) -> Any:
        if self.request.source_id is None:
            raise ValueError("source_id is required to inspect a scene")
        value = await self.inspector.metadata(self.request.source_id, self.request.principal)
        self.progress.append("inspector.metadata")
        return value

    async def list_capabilities(self) -> list[str]:
        self.progress.append("registry.capabilities")
        return sorted(self.registry.capability_ids())

    async def validate_spec(self, version: AppVersion) -> dict[str, Any]:
        result = self.validator(version.spec, approved_action_refs=frozenset(), publication=False)
        self.progress.append("validator.validate")
        return {
            "state": result.state,
            "issues": [
                {"code": issue.code, "field": issue.field, "message": issue.message}
                for issue in result.issues
            ],
        }

    async def start_preview(self, version_id: str) -> str:
        if self.request.source_id is None:
            raise ValueError("source_id is required for preview")
        run_id = await self.preview.start(version_id, self.request.source_id)
        self.progress.append("preview.start")
        return run_id


class BuilderAgent:
    """Runs one compiler turn, validates externally, and performs bounded repair."""

    def __init__(
        self,
        *,
        compiler: CompilerModel,
        inspector: SceneInspector,
        registry: CapabilityRegistry | None,
        validator: SpecValidator,
        preview: PreviewService,
        turns: BuildTurnStore,
        id_factory: Any,
    ) -> None:
        self._compiler = compiler
        self._inspector = inspector
        self._registry = registry or REGISTRY
        self._validator = validator
        self._preview = preview
        self._turns = turns
        self._ids = id_factory

    async def build(self, request: BuilderRequest) -> BuildTurn:
        turn_id = ResourceId(str(self._ids.new("build-turn")))
        progress: list[str] = []
        initial = self._turn(turn_id, request, "running", progress)
        await self._turns.save(initial)
        tools = TypedBuilderTools(
            self._inspector, self._registry, self._validator, self._preview, request, progress
        )
        last_issues: list[str] = []
        usage = None

        for repair_attempt in range(MAX_REPAIR_ATTEMPTS + 1):
            context: dict[str, Any] = {
                "app_id": request.app_id,
                "workspace_id": request.workspace_id,
                "base_version_id": request.base_version_id,
                "base_revision": request.base_revision,
                "source_id": request.source_id,
                "tools": tools,
                "repair_attempt": repair_attempt,
                "validation_errors": last_issues,
                # Explicitly no action permissions are delegated to the model.
                "approved_action_refs": [],
            }
            try:
                result = await asyncio.wait_for(
                    self._compiler.compile(request.instruction, context),
                    timeout=request.timeout_seconds,
                )
            except TimeoutError:
                progress.append("failed:timeout")
                return await self._finish(self._turn(turn_id, request, "failed", progress))
            except Exception as exc:  # Provider details are not persisted into user state.
                progress.append(f"failed:{type(exc).__name__}")
                return await self._finish(self._turn(turn_id, request, "failed", progress))

            outcome = getattr(result, "outcome", result)
            usage = getattr(result, "usage", None)
            if isinstance(outcome, NeedsInput):
                clarification = "\n".join(outcome.questions)
                return await self._finish(
                    self._turn(
                        turn_id,
                        request,
                        "needs_input",
                        progress,
                        clarification=clarification,
                        usage=usage,
                    )
                )
            if isinstance(outcome, UnsupportedRequest):
                progress.append(f"unsupported:{outcome.code}")
                return await self._finish(
                    self._turn(turn_id, request, "unsupported", progress, usage=usage)
                )
            if not isinstance(outcome, ProposedVersion):
                progress.append("failed:invalid_compiler_outcome")
                return await self._finish(
                    self._turn(turn_id, request, "failed", progress, usage=usage)
                )

            validation = self._validator(
                outcome.version.spec, approved_action_refs=frozenset(), publication=False
            )
            progress.append("validator.validate")
            errors = [issue for issue in validation.issues if issue.severity == "error"]
            if errors:
                last_issues = [f"{issue.code}: {issue.message}" for issue in errors]
                progress.append(f"repair:{repair_attempt + 1}")
                continue

            # A proposal is not publication, calibration confirmation, or action permission.
            preview_run_id = None
            if request.preview:
                try:
                    preview_run_id = ResourceId(await tools.start_preview(outcome.version.id.root))
                except Exception as exc:
                    progress.append(f"failed:preview:{type(exc).__name__}")
                    return await self._finish(
                        self._turn(turn_id, request, "failed", progress, usage=usage)
                    )
            return await self._finish(
                self._turn(
                    turn_id,
                    request,
                    "proposed",
                    progress,
                    proposed_version_id=outcome.version.id,
                    proposed_version_spec=outcome.version.spec,
                    preview_run_id=preview_run_id,
                    usage=usage,
                )
            )

        progress.append("failed:repair_limit")
        return await self._finish(self._turn(turn_id, request, "failed", progress, usage=usage))

    async def _finish(self, turn: BuildTurn) -> BuildTurn:
        await self._turns.save(turn)
        return turn

    @staticmethod
    def _turn(
        turn_id: ResourceId,
        request: BuilderRequest,
        status: Literal["queued", "running", "needs_input", "proposed", "unsupported", "failed"],
        progress: list[str],
        *,
        clarification: str | None = None,
        proposed_version_id: ResourceId | None = None,
        proposed_version_spec: AppSpec | None = None,
        preview_run_id: ResourceId | None = None,
        usage: Any = None,
    ) -> BuildTurn:
        return BuildTurn(
            id=turn_id,
            app_id=ResourceId(request.app_id),
            instruction=request.instruction,
            base_version_id=ResourceId(request.base_version_id)
            if request.base_version_id
            else None,
            base_revision=request.base_revision,
            status=status,
            tool_progress=list(progress),
            clarification=clarification,
            proposed_version_id=proposed_version_id,
            proposed_version_spec=proposed_version_spec,
            preview_run_id=preview_run_id,
            usage=usage,
        )
