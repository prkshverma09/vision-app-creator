"""Execution context passed to the ordered runtime engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


from vision_app.contracts.models import (
    Calibration,
    EvidencePolicy,
    ResourceId,
    TrackedRulesSpec,
    SemanticWindowsSpec,
)
from vision_app.operations.limits import ExecutionLimits as OpsExecutionLimits
from vision_app.reasoning import ReasoningBudget


@dataclass(frozen=True)
class RunContext:
    """Immutable inputs for one run attempt."""

    run_id: ResourceId
    attempt_id: ResourceId
    workspace_id: ResourceId
    owner_id: str
    source_id: ResourceId
    source_path: str | Path
    storage_ref: str
    source_generation: int
    source_sha256: str | None
    spec_version_id: ResourceId
    spec: TrackedRulesSpec | SemanticWindowsSpec
    calibration: Calibration | None = None
    evidence_policy: EvidencePolicy = field(default_factory=EvidencePolicy)
    review_budget: ReasoningBudget | None = None
    review_prompt: str | None = None
    limits: OpsExecutionLimits = field(
        default_factory=lambda: OpsExecutionLimits(
            jobs=1, builds=1, frames=10_000, calls=100, output_bytes=10_000_000
        )
    )

    @property
    def source_path_str(self) -> str:
        return str(self.source_path)
