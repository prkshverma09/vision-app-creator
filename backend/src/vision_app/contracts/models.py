"""C0 wire/domain models. Pydantic is the contract source of truth."""
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceId(RootModel[str]):
    @field_validator("root")
    @classmethod
    def opaque(cls, value: str) -> str:
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("resource ID must be non-path opaque text")
        return value


class SourceTimeMs(RootModel[int]):
    @field_validator("root")
    @classmethod
    def nonnegative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("source time must be nonnegative")
        return value


class UtcTimestamp(RootModel[datetime]):
    @field_validator("root")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must be UTC")
        return value


class MoneyMicrousd(RootModel[int]):
    @field_validator("root")
    @classmethod
    def nonnegative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("money must be nonnegative")
        return value


class TimeRange(ContractModel):
    start_ms: SourceTimeMs
    end_ms: SourceTimeMs

    @model_validator(mode="after")
    def ordered(self) -> "TimeRange":
        if self.start_ms.root >= self.end_ms.root:
            raise ValueError("half-open range requires start < end")
        return self


class CrossingBracket(ContractModel):
    last_pre_ms: SourceTimeMs
    first_post_ms: SourceTimeMs

    @model_validator(mode="after")
    def ordered(self) -> "CrossingBracket":
        if self.last_pre_ms.root >= self.first_post_ms.root:
            raise ValueError("crossing bracket requires last_pre < first_post")
        return self


class PointN(ContractModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

    @field_validator("x", "y")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value): raise ValueError("coordinate must be finite")
        return value


class BoxN(ContractModel):
    x1: float = Field(ge=0, le=1); y1: float = Field(ge=0, le=1)
    x2: float = Field(ge=0, le=1); y2: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def positive(self) -> "BoxN":
        if not all(isfinite(v) for v in (self.x1, self.y1, self.x2, self.y2)) or self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("box must be finite with positive width and height")
        return self


class FrameRef(ContractModel):
    source_id: ResourceId; source_hash: str = Field(min_length=16)
    pts: int; time_base_num: int = Field(gt=0); time_base_den: int = Field(gt=0)
    source_time_ms: SourceTimeMs; sequence: int = Field(ge=0)
    width: int = Field(gt=0); height: int = Field(gt=0); transform_id: ResourceId


class QualityFlag(StrEnum):
    OCCLUDED="occluded"; TINY_ROI="tiny_roi"; TIMESTAMP_GAP="timestamp_gap"; PREDICTED_ONLY="predicted_only"


class ObservationQuality(ContractModel):
    flags: set[QualityFlag] = Field(default_factory=set)
    reasons: list[str] = Field(default_factory=list)


class ModelInvocationMetadata(ContractModel):
    provider: str; model: str; revision: str; prompt_hash: str
    input_tokens: int = Field(ge=0); output_tokens: int = Field(ge=0)
    duration_ms: int = Field(ge=0); retry_count: int = Field(ge=0)
    adapter_mode: Literal["structured", "video", "image", "scripted"]
    estimated_cost: MoneyMicrousd = MoneyMicrousd(0)


class EvidencePolicy(ContractModel):
    before_ms: int = Field(default=3000, ge=0); after_ms: int = Field(default=3000, ge=0)

class ExecutionLimits(ContractModel):
    max_duration_ms: int = Field(default=300000, gt=0); max_model_calls: int = Field(default=100, ge=0)

class TrackedRule(ContractModel):
    rule_id: ResourceId; capability_id: Literal["tracked.line_crossing", "tracked.person_in_zone", "tracked.red_phase_crossing"]
    object_classes: list[str] = Field(min_length=1)

class SemanticCondition(ContractModel):
    condition_id: ResourceId; prompt: str = Field(min_length=1); roi_id: ResourceId | None = None

class SpecCommon(ContractModel):
    schema_version: Literal["1.0"] = "1.0"; title: str = Field(min_length=1); objective: str = Field(min_length=1)
    evidence_policy: EvidencePolicy = EvidencePolicy(); approved_action_refs: list[ResourceId] = Field(default_factory=list)
    limits: ExecutionLimits = ExecutionLimits()

class TrackedRulesSpec(SpecCommon):
    kind: Literal["tracked_rules"]
    rules: list[TrackedRule] = Field(min_length=1)

class SemanticWindowsSpec(SpecCommon):
    kind: Literal["semantic_windows"]
    conditions: list[SemanticCondition] = Field(min_length=1)
    window_ms: int = Field(gt=0, le=30000); stride_ms: int = Field(gt=0, le=30000); sample_fps: float = Field(gt=0, le=10)

AppSpec = Annotated[TrackedRulesSpec | SemanticWindowsSpec, Field(discriminator="kind")]

class VisionApp(ContractModel):
    id: ResourceId; workspace_id: ResourceId; title: str; draft_version_id: ResourceId | None = None
    published_version_id: ResourceId | None = None; revision: int = Field(ge=0)

class AppVersion(ContractModel):
    id: ResourceId; app_id: ResourceId; workspace_id: ResourceId; parent_id: ResourceId | None = None; spec: AppSpec
    capability_manifest: dict[str, str]; model_manifest: dict[str, str]; validation_report: list[str]
    created_by: ResourceId; created_at: UtcTimestamp

class Calibration(ContractModel):
    id: ResourceId; source_id: ResourceId; workspace_id: ResourceId; camera_binding: str; revision: int = Field(ge=1)
    reference_frame: FrameRef; lanes: dict[str, list[PointN]]; lines: dict[str, list[PointN]]
    rois: dict[str, BoxN]; governing_signals: dict[str, str]; confirmed_by: ResourceId | None = None
    confirmed_at: UtcTimestamp | None = None; scene_fingerprint: str

class SourceAsset(ContractModel):
    id: ResourceId; workspace_id: ResourceId; byte_size: int = Field(gt=0); codec: str
    width: int = Field(gt=0); height: int = Field(gt=0); duration_ms: SourceTimeMs
    storage_ref: ResourceId; sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["uploading", "ready", "invalid", "deleting", "deleted"]; generation: int = Field(ge=1)
    retention_until: UtcTimestamp | None = None; deleted_at: UtcTimestamp | None = None


class UploadGrant(ContractModel):
    grant_id: str = Field(min_length=1)
    resource_id: ResourceId
    upload_url: str | None = None
    expires_at: UtcTimestamp
    max_bytes: int = Field(gt=0)
    scope: Literal["upload"] = "upload"


class ReadGrant(ContractModel):
    grant_id: str = Field(min_length=1)
    resource_id: ResourceId
    expires_at: UtcTimestamp
    scope: Literal["read"] = "read"


class StoredMetadata(ContractModel):
    resource_id: ResourceId
    owner_id: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation: int = Field(ge=1)
    state: Literal["uploading", "ready", "deleted"]

class BuildTurn(ContractModel):
    id: ResourceId; app_id: ResourceId; instruction: str; base_version_id: ResourceId | None = None
    base_revision: int = Field(ge=0); status: Literal["queued", "running", "needs_input", "proposed", "unsupported", "failed"]
    tool_progress: list[str] = Field(default_factory=list); clarification: str | None = None
    proposed_version_id: ResourceId | None = None; proposed_version_spec: AppSpec | None = None
    preview_run_id: ResourceId | None = None
    usage: ModelInvocationMetadata | None = None

class NeedsInput(ContractModel):
    kind: Literal["needs_input"]; questions: list[str] = Field(min_length=1)
class ProposedVersion(ContractModel):
    kind: Literal["proposed_version"]; version: AppVersion
class UnsupportedRequest(ContractModel):
    kind: Literal["unsupported_request"]; code: str; reason: str
CompilerOutcome = Annotated[NeedsInput | ProposedVersion | UnsupportedRequest, Field(discriminator="kind")]

class DecodedFrame(ContractModel):
    frame_ref: FrameRef; rgb: bytes = Field(exclude=True); stride: int = Field(gt=0)
class Detection(ContractModel):
    class_name: str; box: BoxN; score: float = Field(ge=0, le=1); model_ref: str
class DetectionBatch(ContractModel):
    frame_ref: FrameRef; detections: list[Detection]; invocation: ModelInvocationMetadata | None = None
class TrackObservation(ContractModel):
    frame_ref: FrameRef; attempt_id: ResourceId; track_id: str; observed: bool; box: BoxN; anchor: PointN
    last_observed_ms: SourceTimeMs; quality: ObservationQuality
class SignalObservation(ContractModel):
    roi_id: ResourceId; source_time_ms: SourceTimeMs; state: Literal["red", "amber", "green", "unknown"]; quality: ObservationQuality
class SignalInterval(ContractModel):
    state: Literal["red", "amber", "green"]; confirmed_range: TimeRange; start_uncertainty: CrossingBracket | None = None
    end_uncertainty: CrossingBracket | None = None; gaps: list[TimeRange] = Field(default_factory=list)
class RuleCandidate(ContractModel):
    rule_id: ResourceId; episode_id: str; crossing: CrossingBracket | None = None; persistence: TimeRange | None = None
    fact_refs: list[str]; disposition: Literal["candidate", "supported", "rejected", "inconclusive"]
class SemanticObservation(ContractModel):
    condition_id: ResourceId; decision: Literal["present", "absent", "uncertain"]; requested_range: TimeRange
    observed_ranges: list[TimeRange]; evidence_refs: list[ResourceId]; invocation: ModelInvocationMetadata
class EvidenceManifest(ContractModel):
    requested_range: TimeRange; actual_range: TimeRange | None; thumbnail_ref: ResourceId | None = None
    clip_ref: ResourceId | None = None; clipped_start: bool = False; clipped_end: bool = False
    state: Literal["pending", "available", "degraded", "failed"]
class Event(ContractModel):
    id: ResourceId; run_id: ResourceId; attempt_id: ResourceId; spec_version_id: ResourceId; calibration_id: ResourceId | None
    source_range: TimeRange; rule_id: ResourceId; track_refs: list[str]; facts: dict[str, Any]
    evidence: EvidenceManifest; machine_decision: Literal["candidate", "supported", "rejected", "inconclusive"]
    human_review: Literal["unreviewed", "confirmed_by_user", "dismissed_by_user"]; revision: int = Field(ge=0)
class RunProgress(ContractModel):
    run_id: ResourceId; attempt_id: ResourceId; phase: Literal["queued", "preparing", "running", "completed", "partial", "failed", "cancelled"]
    processed_ranges: list[TimeRange]; requested_samples: int = Field(ge=0); processed_samples: int = Field(ge=0)
    review_backlog: int = Field(ge=0); cancel_requested: bool; usage: MoneyMicrousd; sequence: int = Field(ge=0)


class DeliveryAttempt(ContractModel):
    id: ResourceId; event_id: ResourceId; event_revision: int = Field(ge=0); destination_ref: str = Field(min_length=1)
    permission_version: int = Field(ge=0); state: Literal["pending", "dispatched", "delivered", "failed"] = "pending"
    payload: dict[str, Any] | None = None


class ErrorEnvelope(ContractModel):
    code: str; message: str; field_errors: dict[str, str] = Field(default_factory=dict); request_id: str; retryable: bool
