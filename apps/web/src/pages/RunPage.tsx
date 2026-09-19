import { useEffect, useRef, useState } from 'react'
import type { Event } from '@vision-app/contracts'
import type { ApiClient } from '../client'
import { EventList, EvidenceViewer } from '../features/results'
import { VideoPlayer } from '../features/video'
import { Button, Loading, theme } from '../ui'
import type { RunResponse } from './types'

export interface RunPageProps {
  apiClient: ApiClient
  appId: string
  runId: string
}

function messageText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected error'
}

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
  gap: theme.spacing.md,
  alignItems: 'start',
}

const panelStyle: React.CSSProperties = {
  backgroundColor: theme.colors.surface,
  border: `1px solid ${theme.colors.surfaceBorder}`,
  borderRadius: theme.radii.md,
  padding: theme.spacing.md,
}

type RunResultKind = 'findings' | 'uncertain' | 'none' | 'failed'

const resultStyles: Record<RunResultKind, { background: string; border: string; text: string }> = {
  findings: { background: '#fef2f2', border: theme.colors.danger, text: theme.colors.danger },
  uncertain: { background: '#fffbeb', border: theme.colors.warning, text: theme.colors.warning },
  none: { background: '#f0fdf4', border: theme.colors.success, text: theme.colors.success },
  failed: { background: '#fef2f2', border: theme.colors.danger, text: theme.colors.danger },
}

const formatSeconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`

export function RunPage({ apiClient, appId, runId }: RunPageProps) {
  const [data, setData] = useState<RunResponse | null>(null)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const videoContainerRef = useRef<HTMLDivElement>(null)

  const [reload, setReload] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    setLoadError('')
    setActionError('')
    setData(null)
    setSelectedEventId(null)
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
        if (!controller.signal.aborted) setLoadError(messageText(error))
      }
    }
    void poll()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [apiClient, appId, runId, reload])

  const seekToSourceTime = (ms: number) => {
    const video = videoContainerRef.current?.querySelector('video')
    if (video) video.currentTime = ms / 1000
  }

  const jumpToEvent = (event: Event) => {
    seekToSourceTime(event.source_range.start_ms)
    setSelectedEventId(event.id)
  }

  if (loadError) {
    return (
      <div role="alert">
        <p>{loadError}</p>
        <Button type="button" onClick={() => setReload((value) => value + 1)}>Retry</Button>
      </div>
    )
  }

  if (!data) {
    return <Loading message="Loading run…" />
  }

  // An invalid payload is a defect: surface it through the error boundary
  // rather than silently rendering an empty run.
  if (!data.run || typeof data.run.id !== 'string' || !Array.isArray(data.events)) {
    throw new Error('Unexpected run response from the server')
  }

  const { run, events } = data
  const active = run.status === 'queued' || run.status === 'running'
  const failed = run.status === 'failed' || run.status === 'cancelled'
  const playbackUrl = run.source?.playback_url ?? run.playback_url
  const selectedEvent = events.find((event) => event.id === selectedEventId) ?? null

  const findings = events.filter((event) => event.machine_decision === 'supported' || event.machine_decision === 'candidate')
  const uncertain = events.filter((event) => event.machine_decision === 'inconclusive')
  const resultKind: RunResultKind | null = failed ? 'failed'
    : run.status !== 'succeeded' ? null
    : findings.length > 0 ? 'findings'
    : uncertain.length > 0 ? 'uncertain'
    : 'none'
  const resultStyle = resultKind ? resultStyles[resultKind] : null
  const resultTitle = resultKind === 'findings'
    ? `${findings.length} finding${findings.length === 1 ? '' : 's'}`
    : resultKind === 'uncertain' ? 'Needs review'
    : resultKind === 'none' ? 'No matches'
    : resultKind === 'failed' ? (run.status === 'cancelled' ? 'Run cancelled' : 'Run failed')
    : ''
  const sourceDurationMs = run.source?.duration_ms
    ?? events.reduce((max, event) => Math.max(max, event.source_range.end_ms), 0)

  return (
    <div>
      <p>
        <a href={`#/app/${encodeURIComponent(appId)}/use`}>← App</a>
      </p>
      <h2>Run {run.id}</h2>
      <p role="status">Run {run.status}</p>
      {run.analysis_mode !== 'gemini' && <p style={{ color: theme.colors.textSecondary }}>Demo · Scripted results</p>}
      <details style={{ color: theme.colors.textSecondary, fontSize: theme.fontSizes.sm, marginBottom: theme.spacing.md }}>
        <summary style={{ cursor: 'pointer' }}>Details</summary>
        <p aria-label="Analysis mode">{run.analysis_mode === 'gemini' ? 'Gemini · Model-assisted review' : 'Scripted · Synthetic demo · NOT actual detection'}</p>
        {run.analysis_mode === 'gemini' && <p>AI findings may be inaccurate. Review the video before confirming a finding.</p>}
        <p>App: {run.app_id} · Published version: {run.version_id ?? 'Unknown'} · Source: {run.asset_id ?? run.source?.asset_id ?? 'Unknown'}{run.is_seed_run ? ' · Seed video' : ''}</p>
        {run.calibration_id && <p>Calibration: {run.calibration_id}</p>}
      </details>

      {resultKind && resultStyle && (
        <section
          aria-label="Run result"
          data-result={resultKind}
          style={{
            border: `2px solid ${resultStyle.border}`,
            borderRadius: theme.radii.md,
            backgroundColor: resultStyle.background,
            padding: theme.spacing.md,
            marginBottom: theme.spacing.md,
          }}
        >
          <h3 style={{ margin: 0, color: resultStyle.text }}>{resultTitle}</h3>
          {resultKind === 'none' && <p style={{ marginBottom: 0 }}>No matching observations were returned for this video.</p>}
          {resultKind === 'uncertain' && <p style={{ marginBottom: 0 }}>{uncertain.length} uncertain observation{uncertain.length === 1 ? '' : 's'} need a human decision.</p>}
          {resultKind === 'failed' && <p role="alert" style={{ marginBottom: 0 }}>{run.status === 'failed' ? 'Analysis failed.' : 'Analysis was cancelled.'} {run.failure_reason ?? 'No completed analysis is available. Return to the workspace to try again.'}</p>}
          {events.length > 0 && (
            <div
              aria-label="Findings timeline"
              style={{ position: 'relative', height: '28px', marginTop: theme.spacing.sm, backgroundColor: theme.colors.surface, borderRadius: theme.radii.full, border: `1px solid ${theme.colors.surfaceBorder}` }}
            >
              {events.map((event) => {
                const fraction = sourceDurationMs > 0 ? Math.min(1, Math.max(0, event.source_range.start_ms / sourceDurationMs)) : 0
                const markerColor = event.machine_decision === 'inconclusive' ? theme.colors.warning
                  : event.machine_decision === 'rejected' ? theme.colors.secondary
                  : theme.colors.danger
                return (
                  <button
                    key={event.id}
                    type="button"
                    aria-label={`Jump to finding at ${formatSeconds(event.source_range.start_ms)}`}
                    title={`${formatSeconds(event.source_range.start_ms)} – ${formatSeconds(event.source_range.end_ms)}`}
                    onClick={() => jumpToEvent(event)}
                    style={{
                      position: 'absolute',
                      left: `calc(${fraction * 100}% - 8px)`,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      width: '16px',
                      height: '16px',
                      borderRadius: theme.radii.full,
                      border: `2px solid ${theme.colors.surface}`,
                      backgroundColor: markerColor,
                      cursor: 'pointer',
                      padding: 0,
                    }}
                  />
                )
              })}
            </div>
          )}
        </section>
      )}

      {active && <p>Analysis in progress…</p>}
      {run.coverage_note && <p role="note">{run.coverage_note}</p>}
      {actionError && <p role="alert">{actionError}</p>}

      <div style={gridStyle}>
        <section aria-label="Detected events" style={panelStyle}>
          {events.length > 0 && (
            <EventList
              events={events}
              selectedEventId={selectedEventId}
              onSelectEvent={setSelectedEventId}
            />
          )}
        </section>

        <section aria-label="Event detail" style={panelStyle}>
          {selectedEvent ? (
            <>
              <EvidenceViewer evidence={selectedEvent.evidence} onSeekToSourceTime={seekToSourceTime} />
            </>
          ) : (
            <p>Select an event to inspect evidence and review.</p>
          )}
        </section>

        <section aria-label="Source playback" style={panelStyle}>
          <div ref={videoContainerRef}>
            {playbackUrl ? (
              <VideoPlayer src={playbackUrl} ariaLabel="Run source video" />
            ) : (
              <p>No source playback available.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
