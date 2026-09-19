import type { AppSpec, CompilerOutcome, Event } from '@vision-app/contracts'
import type { SourceMetadata } from '../features/upload'

/** Source attached to an app, with a playback URL the workspace can render. */
export type WorkspaceSource = SourceMetadata & { playback_url?: string }

export interface AppSummary {
  id: string
  name: string
  created_at?: string
}

export interface AppDetail {
  id: string
  name: string
  spec: AppSpec | null
  source: WorkspaceSource | null
  calibration_id: string | null
  analysis_mode?: 'scripted' | 'gemini'
  published_version_id?: string | null
  draft_version_id?: string | null
  requires_calibration?: boolean
  seed_asset_id?: string | null
}

export interface RuntimeInfo {
  analysis_mode: 'scripted' | 'gemini'
  provider: string | null
  model: string | null
  configured: boolean
  external_processing: boolean
  limits: { max_duration_ms: number; max_bytes: number }
}

export interface BuildTurnResponse {
  reply: string
  outcome: CompilerOutcome
}

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface RunDetail {
  id: string
  app_id: string
  status: RunStatus
  playback_url?: string
  coverage_note?: string
  version_id?: string | null
  asset_id?: string | null
  calibration_id?: string | null
  is_seed_run?: boolean
  analysis_mode?: 'scripted' | 'gemini'
  analysis_complete?: boolean
  spec?: AppSpec
  source?: WorkspaceSource | null
  failure_reason?: string | null
  progress?: unknown[] | null
}

export interface RunResponse {
  run: RunDetail
  events: Event[]
}
