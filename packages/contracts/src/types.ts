// Generated-compatible C0 wire types. Python Pydantic models remain authoritative.
export type ResourceId = string
export type SourceTimeMs = number
export interface TimeRange { start_ms: SourceTimeMs; end_ms: SourceTimeMs }
export interface CrossingBracket { last_pre_ms: SourceTimeMs; first_post_ms: SourceTimeMs }
export interface PointN { x: number; y: number }
export interface BoxN { x1: number; y1: number; x2: number; y2: number }
export interface EvidencePolicy { before_ms: number; after_ms: number }
export interface ExecutionLimits { max_duration_ms: number; max_model_calls: number }
export interface TrackedRule { rule_id: ResourceId; capability_id: 'tracked.line_crossing'|'tracked.person_in_zone'|'tracked.red_phase_crossing'; object_classes: string[] }
export interface TrackedRulesSpec { kind:'tracked_rules'; schema_version:'1.0'; title:string; objective:string; evidence_policy:EvidencePolicy; approved_action_refs:ResourceId[]; limits:ExecutionLimits; rules:TrackedRule[] }
export interface SemanticCondition { condition_id:ResourceId; prompt:string; roi_id:ResourceId|null }
export interface SemanticWindowsSpec { kind:'semantic_windows'; schema_version:'1.0'; title:string; objective:string; evidence_policy:EvidencePolicy; approved_action_refs:ResourceId[]; limits:ExecutionLimits; conditions:SemanticCondition[]; window_ms:number; stride_ms:number; sample_fps:number }
export type AppSpec = TrackedRulesSpec | SemanticWindowsSpec
export type CompilerOutcome = {kind:'needs_input';questions:string[]} | {kind:'proposed_version';version:unknown} | {kind:'unsupported_request';code:string;reason:string}
export interface ErrorEnvelope { code:string; message:string; field_errors:Record<string,string>; request_id:string; retryable:boolean }

// ---------------------------------------------------------------------------
// Runtime evidence and events
// ---------------------------------------------------------------------------

export interface EvidenceManifest {
  requested_range: TimeRange
  actual_range: TimeRange | null
  clip_ref: ResourceId | null
  thumbnail_ref: ResourceId | null
  clipped_start: boolean
  clipped_end: boolean
  state: 'pending' | 'available' | 'degraded' | 'failed'
}

export type MachineDecision = 'candidate' | 'supported' | 'rejected' | 'inconclusive'
export type HumanReview = 'unreviewed' | 'confirmed_by_user' | 'dismissed_by_user'

export interface Event {
  id: ResourceId
  run_id: ResourceId
  attempt_id: ResourceId
  spec_version_id: ResourceId
  calibration_id: ResourceId | null
  source_range: TimeRange
  rule_id: ResourceId
  track_refs: string[]
  facts: Record<string, unknown>
  evidence: EvidenceManifest
  machine_decision: MachineDecision
  human_review: HumanReview
  revision: number
}

// ---------------------------------------------------------------------------
// Human review
// ---------------------------------------------------------------------------

export interface ReviewRequest {
  human_review: HumanReview
  note?: string
}

// ---------------------------------------------------------------------------
// Actions and delivery
// ---------------------------------------------------------------------------

export interface WebhookDestination {
  kind: 'webhook'
  url: string
}

export interface ActionConfig {
  id: ResourceId
  enabled: boolean
  destination: WebhookDestination
}

export interface ActionPreviewRequest {
  event_id: ResourceId
  action_ref: ResourceId
}

export interface ActionPreviewResponse {
  would_send: boolean
  payload: unknown
  destination: WebhookDestination
  safety_notice: string
}

export type DeliveryState = 'pending' | 'delivered' | 'failed' | 'suppressed'

export interface Delivery {
  id: ResourceId
  event_id: ResourceId
  action_ref: ResourceId
  destination: WebhookDestination
  state: DeliveryState
  created_at: string
}
