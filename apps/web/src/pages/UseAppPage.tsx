import { useCallback, useEffect, useState } from 'react'
import { ApiError, type ApiClient } from '../client'
import { UploadPanel, type DirectUploader, type SourceMetadata } from '../features/upload'
import { STANDARD_GEOMETRIES, VideoPlayer } from '../features/video'
import { Button, Loading } from '../ui'
import { navigate } from './router'
import type { AppDetail, RunDetail, RuntimeInfo } from './types'

export interface UseAppPageProps {
  apiClient: ApiClient
  appId: string
  uploader?: DirectUploader
}

function messageText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected error'
}

export function UseAppPage({ apiClient, appId, uploader }: UseAppPageProps) {
  const [app, setApp] = useState<AppDetail | null>(null)
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)
  const [runs, setRuns] = useState<RunDetail[]>([])

  const load = useCallback(async () => {
    setLoadError('')
    setApp(null)
    try {
      const [detail, info, history] = await Promise.all([
        apiClient.get<AppDetail>(`/v1/apps/${appId}`),
        apiClient.get<RuntimeInfo>('/v1/runtime').catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 404) return null
          throw error
        }),
        apiClient.get<{ runs: RunDetail[] }>(`/v1/apps/${appId}/runs`).catch(() => ({ runs: [] })),
      ])
      setRuntime(info)
      setApp(detail)
      setRuns(history.runs.filter((run) => run.app_id === appId))
    } catch (error) {
      setLoadError(`The app could not be loaded. ${messageText(error)}`)
    }
  }, [apiClient, appId])

  useEffect(() => {
    void load()
  }, [load])

  const live = (runtime?.analysis_mode ?? app?.analysis_mode) === 'gemini'
  const consentBody = live || runtime?.external_processing === true ? { confirm_external_processing: true } : {}
  const processingAllowed = !live || runtime?.configured !== false
  const requiresCalibration = Boolean(app && (app.requires_calibration ?? app.spec?.kind !== 'semantic_windows'))

  const startRun = async () => {
    const response = await apiClient.post<{ run_id: string }>(`/v1/apps/${appId}/runs`, consentBody)
    navigate({ name: 'run', appId, runId: response.run_id })
  }

  const onSourceReady = async (source: SourceMetadata) => {
    if (busy) return
    setBusy(true)
    setActionError('')
    try {
      await apiClient.post<AppDetail>(`/v1/apps/${appId}/source`, { asset_id: source.asset_id })
      if (requiresCalibration) {
        await apiClient.post<{ calibration_id: string }>(`/v1/apps/${appId}/calibrations`, { geometries: STANDARD_GEOMETRIES })
      }
      await startRun()
    } catch (error) {
      setActionError(messageText(error))
      setBusy(false)
    }
  }

  const runCurrentSource = async () => {
    if (busy || !app?.source) return
    setBusy(true)
    setActionError('')
    try {
      await startRun()
    } catch (error) {
      setActionError(messageText(error))
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <div role="alert">
        <p>{loadError}</p>
        <Button type="button" onClick={() => void load()}>Retry</Button>
      </div>
    )
  }

  if (!app) {
    return <Loading message="Loading app…" />
  }

  return (
    <div>
      <p><a href={`#/app/${encodeURIComponent(appId)}`}>← Workspace</a></p>
      <h2>{app.spec?.title ?? app.name}</h2>
      {!live && <p>Demo · Scripted results</p>}
      {live && runtime?.configured === false && <p role="alert">Model processing is not configured on the server.</p>}
      {actionError && <p role="alert">{actionError}</p>}

      {!app.published_version_id ? (
        <p>The app is not published yet. Finish building it in the workspace first.</p>
      ) : (
        <>
          <h3>Upload a video</h3>
          <UploadPanel apiClient={apiClient} uploader={uploader} onReady={onSourceReady} maxBytes={runtime?.limits.max_bytes} />
          {busy && <p role="status">Analyzing video…</p>}
          {app.source?.playback_url && (
            <section aria-label="Current video">
              <VideoPlayer src={app.source.playback_url} ariaLabel="Current source video" />
              <Button type="button" disabled={busy || !processingAllowed} onClick={() => void runCurrentSource()}>
                {busy ? 'Analyzing…' : 'Run app'}
              </Button>
            </section>
          )}
          <section aria-label="Run history">
            <h3>Run history</h3>
            {runs.length === 0 ? <p>No runs yet.</p> : (
              <ul>{runs.map((run) => (
                <li key={run.id}>
                  <a href={`#/app/${encodeURIComponent(run.app_id)}/run/${encodeURIComponent(run.id)}`}>Run {run.id}</a>
                  {' · '}{run.status}
                  <details><summary>Details</summary>Source: {run.asset_id ?? run.source?.asset_id ?? 'Unknown'} · Version: {run.version_id ?? 'Unknown'}{run.is_seed_run ? ' · Seed video' : ''}</details>
                </li>
              ))}</ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
