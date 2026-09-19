import type { Event } from '@vision-app/contracts'
import type { AppDetail, RunResponse, RuntimeInfo } from './types'
import { proposedVersion } from '../features/chat/test-fixtures'

export const draftApp: AppDetail = {
  id: 'app-1',
  name: 'Crossing watcher',
  spec: null,
  source: null,
  calibration_id: null,
}

export const specifiedApp: AppDetail = {
  ...draftApp,
  spec: proposedVersion.version as AppDetail['spec'],
}

export const sourcedApp: AppDetail = {
  ...specifiedApp,
  source: {
    asset_id: 'asset-1',
    status: 'ready',
    duration_ms: 12_500,
    width: 640,
    height: 360,
    playback_url: 'blob:fixture-video',
  },
}

export const calibratedApp: AppDetail = {
  ...sourcedApp,
  calibration_id: 'cal-1',
}

export const liveRuntime: RuntimeInfo = {
  analysis_mode: 'gemini',
  provider: 'google',
  model: 'gemini-test',
  configured: true,
  external_processing: true,
  limits: { max_duration_ms: 60_000, max_bytes: 100_000_000 },
}

export const semanticApp: AppDetail = {
  ...sourcedApp,
  analysis_mode: 'gemini',
  published_version_id: 'ver-1',
  draft_version_id: null,
  requires_calibration: false,
  seed_asset_id: 'asset-1',
  spec: {
    kind: 'semantic_windows',
    schema_version: '1.0',
    title: 'Safety review',
    objective: 'Review visible safety conditions',
    conditions: [{ condition_id: 'condition-1', prompt: 'Is the exit visibly obstructed?', roi_id: null }],
    evidence_policy: { before_ms: 3000, after_ms: 3000 },
    approved_action_refs: [],
    limits: { max_duration_ms: 60_000, max_model_calls: 10 },
    window_ms: 5000,
    stride_ms: 5000,
    sample_fps: 1,
  },
}

export const sampleEvent: Event = {
  id: 'ev-1',
  run_id: 'run-1',
  attempt_id: 'attempt-1',
  spec_version_id: 'ver-1',
  calibration_id: 'cal-1',
  source_range: { start_ms: 4_000, end_ms: 6_500 },
  rule_id: 'red-crossing',
  track_refs: ['track-7'],
  facts: { object_class: 'car' },
  evidence: {
    requested_range: { start_ms: 1_000, end_ms: 9_500 },
    actual_range: { start_ms: 1_000, end_ms: 9_500 },
    clip_ref: 'clip-1',
    thumbnail_ref: null,
    clipped_start: false,
    clipped_end: false,
    state: 'available',
  },
  machine_decision: 'supported',
  human_review: 'unreviewed',
  revision: 1,
}

export const succeededRun: RunResponse = {
  run: {
    id: 'run-1',
    app_id: 'app-1',
    status: 'succeeded',
    playback_url: 'blob:fixture-video',
  },
  events: [sampleEvent],
}

type Handler = (init: RequestInit | undefined) => Response | Promise<Response>

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/**
 * Minimal fetch router for workspace tests. Keys are `METHOD path`.
 * No real network: install with vi.stubGlobal('fetch', mockFetchRouter(...)).
 */
export function mockFetchRouter(routes: Record<string, Handler | unknown>) {
  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = (init?.method ?? 'GET').toUpperCase()
    const key = `${method} ${url}`
    const route = routes[key]
    if (route === undefined) {
      return jsonResponse({ code: 'not_found', message: `No mock for ${key}`, field_errors: {}, request_id: 'req-test', retryable: false }, 404)
    }
    if (typeof route === 'function') return (route as Handler)(init)
    return jsonResponse(route)
  }
}
