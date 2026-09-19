import { useEffect, useState } from 'react'
import type { ApiClient } from '../client'
import { VideoPlayer } from '../features/video'
import { Button, Loading, theme } from '../ui'
import type { RunResponse } from './types'

export interface RunPageProps {
  apiClient: ApiClient
  appId: string
  runId: string
}

function resultText({ run, events }: RunResponse): string {
  if (run.status === 'queued' || run.status === 'running') return 'Analyzing your video…'
  if (run.status === 'failed') return 'The video could not be analyzed — please try again.'
  if (run.status === 'cancelled') return 'Analysis was cancelled — no result is available.'
  if (run.analysis_mode !== 'gemini') return 'Demo only: this video has not been analyzed.'
  if (run.analysis_complete === false) return 'Only part of the video was analyzed — no complete result is available.'

  const finding = events.find(event => event.machine_decision === 'supported')
    ?? events.find(event => event.machine_decision === 'candidate')
  const spec = run.spec
  if (finding) {
    const description = finding.facts.description
    const rule = spec?.kind === 'tracked_rules'
      ? spec.rules.find(rule => rule.rule_id === finding.rule_id)
      : undefined
    const text = typeof description === 'string' && description.trim()
      ? description.trim().replace(/\s+/g, ' ')
      : rule?.capability_id === 'tracked.red_phase_crossing'
        ? 'A vehicle crossed the stop line while the light was red.'
        : 'Matching activity was detected in this video.'
    const sentence = text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? `${text.replace(/[.!?]+$/, '')}.`
    return finding.machine_decision === 'candidate' ? `Possible match: ${sentence}` : sentence
  }
  if (events.some(event => event.machine_decision === 'inconclusive')) {
    return 'The video is inconclusive — the app could not determine whether the activity occurred.'
  }
  return spec?.kind === 'tracked_rules' && spec.rules.length > 0
    && spec.rules.every(rule => rule.capability_id === 'tracked.red_phase_crossing')
    ? 'No red-light violations were detected in this video.'
    : 'No matching activity was detected in this video.'
}

export function RunPage({ apiClient, appId, runId }: RunPageProps) {
  const [data, setData] = useState<RunResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setLoadError('')
    setData(null)
    const poll = async () => {
      try {
        const response = await apiClient.get<RunResponse>(`/v1/runs/${runId}`, { signal: controller.signal })
        if (controller.signal.aborted) return
        if (response.run && response.run.app_id !== appId) throw new Error('This run does not belong to this app.')
        setData(response)
        if (response.run?.status === 'queued' || response.run?.status === 'running') {
          timer = setTimeout(() => void poll(), 1000)
        }
      } catch (error) {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : 'Unexpected error')
      }
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [apiClient, appId, runId, reload])

  if (loadError) {
    return (
      <div role="alert">
        <p>{loadError}</p>
        <Button type="button" onClick={() => setReload((value) => value + 1)}>Retry</Button>
      </div>
    )
  }

  if (!data) {
    return <Loading message="Loading result…" />
  }

  // An invalid payload is a defect: surface it through the error boundary
  // rather than silently rendering an empty run.
  if (!data.run || typeof data.run.id !== 'string' || !Array.isArray(data.events)) {
    throw new Error('Unexpected run response from the server')
  }

  const { run } = data
  const failed = run.status === 'failed' || run.status === 'cancelled'
  const playbackUrl = run.source?.playback_url ?? run.playback_url

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', fontFamily: 'system-ui, sans-serif', color: theme.colors.text }}>
      <p>
        <a href={`#/app/${encodeURIComponent(appId)}/use`}>← App</a>
      </p>
      <h2 style={{ fontSize: theme.fontSizes.md, color: theme.colors.textSecondary }}>{run.spec?.title ?? 'Result'}</h2>
      <p
        role={failed ? 'alert' : 'status'}
        aria-label="Run result"
        data-status={run.status}
        style={{ fontSize: theme.fontSizes.xl, lineHeight: 1.5, marginBottom: theme.spacing.lg }}
      >
        {resultText(data)}
      </p>
      {run.status === 'failed' && run.failure_reason && (
        <details>
          <summary>Error details</summary>
          <p>{run.failure_reason}</p>
        </details>
      )}
      {playbackUrl && <VideoPlayer src={playbackUrl} ariaLabel="Run source video" showFrameControls={false} />}
    </div>
  )
}
