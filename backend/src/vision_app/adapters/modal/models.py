"""JSON-only wire contracts for Modal run invocations."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vision_app.runtime.context import RunContext


class ModalRunInput(BaseModel):
    """Owned identifiers and immutable manifests sent to a worker.

    Local paths and signed URLs are deliberately excluded. The worker resolves the
    opaque storage reference using its own least-privilege service identity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    attempt_id: str
    workspace_id: str
    owner_id: str
    source_id: str
    storage_ref: str
    source_generation: int = Field(ge=1)
    source_sha256: str | None
    spec_version_id: str
    spec: dict[str, Any]
    calibration: dict[str, Any] | None
    evidence_policy: dict[str, Any]
    limits: dict[str, Any]
    fence: int = Field(ge=0)

    @classmethod
    def from_context(cls, context: RunContext, fence: int) -> ModalRunInput:
        limits = asdict(context.limits)
        if limits["deadline"] is not None:
            limits["deadline"] = limits["deadline"].isoformat()
        return cls(
            run_id=context.run_id.root,
            attempt_id=context.attempt_id.root,
            workspace_id=context.workspace_id.root,
            owner_id=context.owner_id,
            source_id=context.source_id.root,
            storage_ref=context.storage_ref,
            source_generation=context.source_generation,
            source_sha256=context.source_sha256,
            spec_version_id=context.spec_version_id.root,
            spec=context.spec.model_dump(mode="json"),
            calibration=(
                context.calibration.model_dump(mode="json") if context.calibration else None
            ),
            evidence_policy=context.evidence_policy.model_dump(mode="json"),
            limits=limits,
            fence=fence,
        )


class ModalStreamItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["progress", "event"]
    payload: dict[str, Any]
    fence: int = Field(ge=0)


class ModalInvocationStatus(BaseModel):
    invocation_id: str
    state: Literal["queued", "running", "completed", "failed", "cancelling", "cancelled", "unknown"]
