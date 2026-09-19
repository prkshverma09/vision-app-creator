import { useEffect, useRef, useState } from 'react'
import type { Event, ReviewRequest } from '@vision-app/contracts'
import type { ApiClient } from '../client'
import { EventList, EvidenceViewer, ReviewPanel } from '../features/results'
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

  const submitReview = async (eventId: string, review: ReviewRequest) => {
    setActionError('')
    try {
      const updated = await apiClient.post<Event>(`/v1/events/${eventId}/review`, review)
      setData((current) => current && ({
        ...current,
        events: current.events.map((event) => (event.id === updated.id ? updated : event)),
      }))
    } catch (error) {
      setActionError(messageText(error))
    }
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

  return (
    <div>
      <p>
        <a href={`#/app/${encodeURIComponent(appId)}`}>← Workspace</a>
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
      {active && <p>Analysis is in progress. Results will update automatically; no final conclusions are available yet.</p>}
      {failed && <p role="alert">{run.status === 'failed' ? 'Analysis failed.' : 'Analysis was cancelled.'} {run.failure_reason ?? 'No completed analysis is available. Return to the workspace to try again.'}</p>}
      {run.status === 'succeeded' && events.length === 0 && <p>No matching observations were returned for this video. This does not prove that the conditions never occurred; consider video coverage and model limitations.</p>}
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
              <ReviewPanel
                event={selectedEvent}
                onReview={(review) => void submitReview(selectedEvent.id, review)}
              />
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
