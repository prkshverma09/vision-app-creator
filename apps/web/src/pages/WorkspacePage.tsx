import { useCallback, useEffect, useState } from 'react'
import type { CompilerOutcome } from '@vision-app/contracts'
import { ApiError, type ApiClient } from '../client'
import {
  BuildTurnOutcome,
  ChatInput,
  ChatThread,
  type ChatMessage,
} from '../features/chat'
import {
  UploadPanel,
  type DirectUploader,
  type SourceMetadata,
} from '../features/upload'
import { CalibrationEditor, VideoPlayer, type OverlayGeometry } from '../features/video'
import { Button, Loading, theme } from '../ui'
import { stageForApp, stageLabels, stageOrder } from './builder-state'
import { navigate } from './router'
import type { AppDetail, BuildTurnResponse, RunDetail, RuntimeInfo } from './types'

export interface WorkspacePageProps {
  apiClient: ApiClient
  appId: string
  uploader?: DirectUploader
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

const stepsStyle: React.CSSProperties = {
  display: 'flex',
  gap: theme.spacing.sm,
  listStyle: 'none',
  padding: 0,
  margin: `${theme.spacing.sm} 0 ${theme.spacing.md}`,
  flexWrap: 'wrap',
}

export function WorkspacePage({ apiClient, appId, uploader }: WorkspacePageProps) {
  const [app, setApp] = useState<AppDetail | null>(null)
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [outcome, setOutcome] = useState<CompilerOutcome | null>(null)
  const [pending, setPending] = useState(false)
  const [startingRun, setStartingRun] = useState(false)
  const [attachingSource, setAttachingSource] = useState(false)
  const [changingSource, setChangingSource] = useState(false)
  const [runReady, setRunReady] = useState(false)
  const [calibrationConfirmed, setCalibrationConfirmed] = useState(false)
  const [runs, setRuns] = useState<RunDetail[]>([])
  const [historyError, setHistoryError] = useState('')

  const load = useCallback(async () => {
    setLoadError('')
    setApp(null)
    try {
      const [detail, info] = await Promise.all([
        apiClient.get<AppDetail>(`/v1/apps/${appId}`),
        apiClient.get<RuntimeInfo>('/v1/runtime').catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 404) return null
          throw error
        }),
      ])
      setRuntime(info)
      setApp(detail)
    } catch (error) {
      setLoadError(`The app could not be loaded. ${messageText(error)}`)
    }
  }, [apiClient, appId])

  const loadHistory = useCallback(async () => {
    setHistoryError('')
    try {
      const response = await apiClient.get<{ runs: RunDetail[] }>(`/v1/apps/${appId}/runs`)
      setRuns(response.runs.filter((run) => run.app_id === appId))
    } catch (error) {
      setHistoryError(`Run history unavailable. ${messageText(error)}`)
    }
  }, [apiClient, appId])

  useEffect(() => {
    setRunReady(false)
    setCalibrationConfirmed(false)
    setChangingSource(false)
    setMessages([])
    setOutcome(null)
    setRuns([])
    void load()
    void loadHistory()
  }, [load, loadHistory])

  const live = (runtime?.analysis_mode ?? app?.analysis_mode) === 'gemini'
  // External-processing consent is assumed: the operator opted in by running in
  // this mode, so requests always carry the confirmation flag without a dialog.
  const needsConsent = live || runtime?.external_processing === true
  const processingAllowed = !live || runtime?.configured !== false
  const consentBody = needsConsent ? { confirm_external_processing: true } : {}
  const canPrompt = processingAllowed && (!live || Boolean(app?.source)) && !attachingSource
  const chooseRunVideo = () => {
    setRunReady(false)
    setChangingSource(true)
    setActionError('')
  }

  const sendMessage = async (text: string) => {
    if (!canPrompt || pending) return false
    setPending(true)
    setActionError('')
    try {
      const response = await apiClient.post<BuildTurnResponse>(`/v1/apps/${appId}/turns`, { message: text, ...consentBody })
      setMessages((current) => [
        ...current,
        { id: `m-${current.length + 1}`, kind: 'user', content: text },
        { id: `m-${current.length + 2}`, kind: 'assistant', content: response.reply },
      ])
      setOutcome(response.outcome)
    } catch (error) {
      setMessages((current) => [
        ...current,
        { id: `m-${current.length + 1}`, kind: 'error', content: messageText(error) },
      ])
    } finally {
      setPending(false)
    }
  }

  const submitClarification = async (answers: string[]) => {
    if (!canPrompt || pending) return
    setPending(true)
    setActionError('')
    try {
      const response = await apiClient.post<BuildTurnResponse>(`/v1/apps/${appId}/clarifications`, { answers, ...consentBody })
      setMessages((current) => [
        ...current,
        { id: `m-${current.length + 1}`, kind: 'assistant', content: response.reply },
      ])
      setOutcome(response.outcome)
    } catch (error) {
      setActionError(messageText(error))
    } finally {
      setPending(false)
    }
  }

  const acceptProposal = async (version: AppDetail['spec']) => {
    if (pending) return
    setPending(true)
    setActionError('')
    try {
      const detail = await apiClient.post<AppDetail>(`/v1/apps/${appId}/versions`, { spec: version })
      setApp(detail)
      setOutcome(null)
      setRunReady(Boolean(detail.published_version_id && detail.source))
      setMessages((current) => [
        ...current,
        { id: `m-${current.length + 1}`, kind: 'assistant', content: detail.source ? 'Proposal accepted.' : 'Proposal accepted. Upload a source video next.' },
      ])
    } catch (error) {
      setActionError(messageText(error))
    } finally {
      setPending(false)
    }
  }

  const onSourceReady = async (source: SourceMetadata) => {
    setAttachingSource(true)
    setActionError('')
    try {
      const detail = await apiClient.post<AppDetail>(`/v1/apps/${appId}/source`, { asset_id: source.asset_id })
      setApp({ ...detail, calibration_id: app?.source?.asset_id === source.asset_id ? detail.calibration_id : null })
      setChangingSource(false)
      setCalibrationConfirmed(false)
      setRunReady(Boolean(app?.spec))
    } catch (error) {
      setActionError(messageText(error))
    } finally {
      setAttachingSource(false)
    }
  }

  const onConfirmCalibration = async (geometries: OverlayGeometry[]) => {
    setActionError('')
    try {
      const response = await apiClient.post<{ calibration_id: string }>(`/v1/apps/${appId}/calibrations`, { geometries })
      setApp((current) => current ? {
        ...current,
        calibration_id: response.calibration_id,
        published_version_id: current.draft_version_id ?? current.published_version_id,
      } : current)
      setCalibrationConfirmed(true)
      setRunReady(true)
    } catch (error) {
      setActionError(messageText(error))
    }
  }

  const startRun = async (assetId?: string) => {
    if (!processingAllowed || startingRun || attachingSource || changingSource) return
    if (assetId === undefined && !app?.source) return
    setStartingRun(true)
    setActionError('')
    try {
      const response = await apiClient.post<{ run_id: string }>(`/v1/apps/${appId}/runs`, { ...consentBody, ...(assetId ? { asset_id: assetId } : {}) })
      navigate({ name: 'run', appId, runId: response.run_id })
    } catch (error) {
      setActionError(messageText(error))
      setStartingRun(false)
    }
  }

  // A published app never silently re-runs its previous source: starting a run
  // first asks for a new video unless one was just attached or calibrated.
  const onStartRun = () => {
    if (app?.published_version_id && !runReady) { chooseRunVideo(); return }
    void startRun()
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
    return <Loading message="Loading workspace…" />
  }

  const stage = stageForApp(app)
  const requiresCalibration = app.requires_calibration ?? app.spec?.kind !== 'semantic_windows'
  const steps = stageOrder.filter((step) => step !== 'calibration' || requiresCalibration)
  const currentIndex = steps.indexOf(stage)
  const source = app.source
  const runDisabled = startingRun || !processingAllowed || attachingSource || changingSource
  const seedRunnable = app.seed_asset_id && (app.spec?.kind === 'semantic_windows' || app.seed_asset_id === source?.asset_id)

  return (
    <div>
      <p><a href="#/">← All apps</a></p>
      <h2>{app.spec?.title ?? app.name}</h2>
      {!live && <p style={{ color: theme.colors.textSecondary }}>Demo · Scripted results</p>}
      <details style={{ color: theme.colors.textSecondary, fontSize: theme.fontSizes.sm, marginBottom: theme.spacing.sm }}>
        <summary style={{ cursor: 'pointer' }}>Details</summary>
        <p aria-label="Analysis mode">{live ? 'Gemini · Model-assisted review' : 'Scripted · Synthetic demo · NOT actual detection'}</p>
        {runtime && <p>Provider: {runtime.provider ?? 'None'} · Model: {runtime.model ?? 'None'} · Video limit: {runtime.limits.max_duration_ms / 1000} seconds, {runtime.limits.max_bytes / 1_000_000} MB</p>}
        <p>Published version: {app.published_version_id ?? 'Not published yet'}</p>
        {app.seed_asset_id && <p>Seed video: {app.seed_asset_id}</p>}
      </details>
      {source && !changingSource && <p>Current source: {source.asset_id}{source.asset_id === app.seed_asset_id ? ' (seed video)' : ''}</p>}
      {live && runtime?.configured === false && <p role="alert">Model processing is not configured on the server.</p>}

      {!app.published_version_id && <ol aria-label="Builder steps" style={stepsStyle}>
        {steps.map((step, index) => (
          <li key={step} aria-current={step === stage ? 'step' : undefined} style={{
            padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
            borderRadius: theme.radii.sm,
            border: `1px solid ${index <= currentIndex ? theme.colors.primary : theme.colors.surfaceBorder}`,
            color: index <= currentIndex ? theme.colors.primary : theme.colors.textSecondary,
            fontSize: theme.fontSizes.sm,
          }}>
            {index + 1}. {stageLabels[step]}
          </li>
        ))}
      </ol>}

      {actionError && <p role="alert">{actionError}</p>}

      <div style={gridStyle}>
        <section aria-label="Builder chat" style={panelStyle}>
          {messages.length > 0 && <ChatThread messages={messages} />}
          {outcome && stage === 'chat' && (
            <fieldset disabled={pending || !canPrompt} style={{ border: 0, padding: 0 }}>
              <BuildTurnOutcome outcome={outcome} onClarify={submitClarification} onAccept={acceptProposal} onEditPrompt={async (text) => { await sendMessage(text) }} />
            </fieldset>
          )}
          {stage === 'chat' ? (
            <ChatInput onSubmit={sendMessage} pending={pending} submitDisabled={!canPrompt} />
          ) : app.spec && (
            <section aria-label="Reusable app definition">
              <h3>{app.spec.title}</h3>
              <p>{app.spec.objective}</p>
              <details><summary>Conditions</summary>
              <ul>{app.spec.kind === 'semantic_windows'
                ? app.spec.conditions.map((condition) => <li key={condition.condition_id}>{condition.prompt}</li>)
                : app.spec.rules.map((rule) => <li key={rule.rule_id}>{{ 'tracked.line_crossing': 'Crossing the drawn line', 'tracked.person_in_zone': 'Presence in the marked zone', 'tracked.red_phase_crossing': 'Crossing during a red signal' }[rule.capability_id]}: {rule.object_classes.join(', ')}</li>)}</ul>
              </details>
            </section>
          )}
        </section>

        <section aria-label="Source and calibration" style={panelStyle}>
          {changingSource && <h3>Upload a new video</h3>}
          {source?.playback_url && !changingSource && <VideoPlayer src={source.playback_url} ariaLabel="Current source video" />}
          {(!source || changingSource) && (
            <UploadPanel apiClient={apiClient} uploader={uploader} onReady={onSourceReady} maxBytes={runtime?.limits.max_bytes} />
          )}
          {attachingSource && <p role="status">Attaching source…</p>}
          {app.spec && stage === 'run' && !changingSource && <Button type="button" disabled={!processingAllowed || pending} onClick={chooseRunVideo}>Analyze a new video</Button>}
          {changingSource && source && <Button type="button" variant="secondary" disabled={attachingSource} onClick={() => setChangingSource(false)}>Cancel</Button>}
          {stage === 'calibration' && source && !changingSource && (
            <CalibrationEditor key={source.asset_id} src={source.playback_url ?? ''} sourceWidth={source.width ?? 640} sourceHeight={source.height ?? 360} onConfirm={onConfirmCalibration} />
          )}
          {calibrationConfirmed && <p role="status">Source ready and calibration confirmed.</p>}
          {stage === 'run' && <Button type="button" onClick={onStartRun} disabled={runDisabled}>{startingRun ? 'Analyzing…' : 'Start run'}</Button>}
          {stage === 'run' && seedRunnable && !changingSource && <details style={{ marginTop: theme.spacing.md }}>
            <summary>Example video</summary>
            {app.seed_asset_id === source?.asset_id && source?.playback_url && <VideoPlayer src={source.playback_url} ariaLabel="Example video" />}
            <Button type="button" variant="secondary" onClick={() => void startRun(app.seed_asset_id ?? undefined)} disabled={runDisabled}>Run on seed video</Button>
          </details>}
        </section>

        <section aria-label="Run and results" style={panelStyle}>
          <h3>Run history</h3>
          {historyError ? <p role="note">{historyError}</p> : runs.length === 0 ? <p>No runs yet.</p> : (
            <ul>{runs.map((run) => (
              <li key={run.id}>
                <a href={`#/app/${encodeURIComponent(run.app_id)}/run/${encodeURIComponent(run.id)}`}>Run {run.id}</a>
                {' · '}{run.status}
                <details><summary>Details</summary>Source: {run.asset_id ?? run.source?.asset_id ?? 'Unknown'} · Version: {run.version_id ?? 'Unknown'}{run.is_seed_run ? ' · Seed video' : ''}</details>
                {run.failure_reason && <p>{run.failure_reason}</p>}
              </li>
            ))}</ul>
          )}
          {app.spec && stage === 'run' && !changingSource && <Button type="button" onClick={chooseRunVideo} disabled={!processingAllowed || pending || startingRun}>Run app</Button>}
          <Button type="button" variant="secondary" onClick={() => void loadHistory()}>Refresh history</Button>
        </section>
      </div>
    </div>
  )
}
