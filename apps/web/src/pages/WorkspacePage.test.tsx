import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import type { DirectUploader } from '../features/upload'
import { proposedVersion } from '../features/chat/test-fixtures'
import { WorkspacePage } from './WorkspacePage'
import {
  calibratedApp,
  draftApp,
  mockFetchRouter,
  liveRuntime,
  semanticApp,
  sourcedApp,
  specifiedApp,
} from './workspace-test-fixtures'

const apiClient = createApiClient({ getToken: async () => 'test-token' })

const instantUploader: DirectUploader = async (_grant, _file, onProgress) => {
  onProgress(100)
}

function videoFile() {
  return new File([new Uint8Array(64)], 'crossing.mp4', { type: 'video/mp4' })
}

/** Routes covering the whole builder happy path for a draft app. */
function happyPathRoutes() {
  return {
    'GET /v1/apps/app-1': draftApp,
    'POST /v1/apps/app-1/turns': {
      reply: 'Here is a draft spec.',
      outcome: proposedVersion,
    },
    'POST /v1/apps/app-1/versions': specifiedApp /* version accepted */,
    'POST /v1/uploads': { upload_id: 'upload-1', upload_url: 'https://upload.test/object' },
    'POST /v1/uploads/upload-1/complete': {
      asset_id: 'asset-1',
      status: 'ready',
      duration_ms: 12_500,
      width: 640,
      height: 360,
    },
    'POST /v1/apps/app-1/source': sourcedApp,
    'POST /v1/apps/app-1/calibrations': { calibration_id: 'cal-1' },
    'POST /v1/apps/app-1/runs': { run_id: 'run-1' },
  }
}

describe('WorkspacePage', () => {
  beforeEach(() => {
    window.location.hash = '#/app/app-1'
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fixture-video'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uploads the seed before the first prompt and sends live processing consent without a dialog', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(mockFetchRouter({
      ...happyPathRoutes(),
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': { ...draftApp, analysis_mode: 'gemini' },
      'POST /v1/apps/app-1/source': { ...draftApp, source: sourcedApp.source, seed_asset_id: 'asset-1', analysis_mode: 'gemini' },
      'POST /v1/apps/app-1/turns': { reply: 'Ready.', outcome: { kind: 'proposed_version', version: semanticApp.spec } },
      'POST /v1/apps/app-1/versions': semanticApp,
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    await user.type(await screen.findByRole('textbox', { name: 'Message' }), 'Review the exit')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.upload(screen.getByLabelText(/choose an mp4 video/i), videoFile())
    expect(await screen.findByText('Current source: asset-1 (seed video)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(window.confirm).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(window.confirm).not.toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: 'Accept proposal' }))

    expect(await screen.findByText('Published version: ver-1')).toBeInTheDocument()
    expect(screen.getByText('Is the exit visibly obstructed?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run app' })).toBeEnabled()
    const paths = fetchMock.mock.calls.map(([path]) => path)
    expect(paths.indexOf('/v1/apps/app-1/source')).toBeLessThan(paths.indexOf('/v1/apps/app-1/turns'))
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/turns', expect.objectContaining({ body: JSON.stringify({ message: 'Review the exit', confirm_external_processing: true }) }))
  })

  it('navigates a published app to the use page without running anything', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': semanticApp,
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage apiClient={apiClient} appId="app-1" />)

    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Run app' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1/use'))
    expect(window.confirm).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('sends live clarifications without a consent dialog', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': { ...draftApp, source: sourcedApp.source },
      'POST /v1/apps/app-1/turns': { reply: 'More detail?', outcome: { kind: 'needs_input', questions: ['Which exit?'] } },
      'POST /v1/apps/app-1/clarifications': { reply: 'Ready.', outcome: { kind: 'proposed_version', version: semanticApp.spec } },
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage apiClient={apiClient} appId="app-1" />)
    await user.type(await screen.findByRole('textbox', { name: 'Message' }), 'Review exits')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await user.type(await screen.findByLabelText('Which exit?'), 'The rear exit')
    await user.click(screen.getByRole('button', { name: 'Submit clarification' }))
    expect(window.confirm).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: 'Accept proposal' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/clarifications', expect.objectContaining({ body: JSON.stringify({ answers: ['The rear exit'], confirm_external_processing: true }) }))
  })

  it('does not enable live processing when the server is unconfigured', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runtime': { ...liveRuntime, configured: false },
      'GET /v1/apps/app-1': semanticApp,
    })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" />)
    expect(await screen.findByRole('button', { name: 'Run app' })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('not configured on the server')
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('keeps provider information collapsed and does not show a consent checkbox', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': semanticApp,
    })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" />)
    const mode = await screen.findByLabelText('Analysis mode')
    expect(mode.closest('details')).not.toHaveAttribute('open')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(window.confirm).not.toHaveBeenCalled()
    await userEvent.click(screen.getByText('Details', { selector: 'summary' }))
    expect(mode.closest('details')).toHaveAttribute('open')
    expect(screen.getByText(/Model: gemini-test/)).toBeInTheDocument()
  })

  it('sends the prompt without a consent dialog on a live workspace', async () => {
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': { ...draftApp, source: sourcedApp.source, analysis_mode: 'gemini' },
      'POST /v1/apps/app-1/turns': { reply: 'Ready.', outcome: { kind: 'proposed_version', version: semanticApp.spec } },
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage apiClient={apiClient} appId="app-1" />)
    await userEvent.type(await screen.findByRole('textbox', { name: 'Message' }), 'Find cars')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(window.confirm).not.toHaveBeenCalled()
    expect(await screen.findByRole('button', { name: 'Accept proposal' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/turns', expect.objectContaining({ body: JSON.stringify({ message: 'Find cars', confirm_external_processing: true }) }))
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('')
  })

  it('shows a loading state, then renders the workspace panels', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/apps/app-1': draftApp })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    expect(await screen.findByRole('region', { name: /builder chat/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /source and calibration/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Crossing watcher' })).toBeInTheDocument()
  })

  it('shows an error alert with retry when the app fails to load', async () => {
    const fetchMock = vi.fn(mockFetchRouter({}))
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be loaded|no mock/i)
    fetchMock.mockImplementation(mockFetchRouter({ 'GET /v1/apps/app-1': draftApp }))
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    expect(await screen.findByRole('heading', { name: 'Crossing watcher' })).toBeInTheDocument()
  })

  it('walks the builder workflow chat → upload → calibrate → use page', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter(happyPathRoutes())))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    // Chat: describe the app, receive a proposal.
    const messageBox = await screen.findByRole('textbox', { name: 'Message' })
    await user.type(messageBox, 'Detect cars crossing on red')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('heading', { name: 'Red light crossing' })).toBeInTheDocument()

    // Accept proposal → upload step.
    await user.click(screen.getByRole('button', { name: 'Accept proposal' }))
    const fileInput = await screen.findByLabelText(/choose an mp4 video/i)
    await user.upload(fileInput, videoFile())

    // Standard calibration is preloaded; confirm publishes the version.
    await user.click(await screen.findByRole('button', { name: 'Confirm calibration' }))
    expect(await screen.findByText(/calibration confirmed/i)).toBeInTheDocument()

    // Run step → navigates to the use page.
    await user.click(await screen.findByRole('button', { name: 'Run app' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1/use'))
  })

  it('reconstructs the calibration stage after reload when source exists but no calibration', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/apps/app-1': sourcedApp })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    // No in-memory transcript is required: the stage derives from server state.
    expect(await screen.findByLabelText('Calibration drawing canvas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm calibration' })).toBeEnabled()
  })

  it('reconstructs the run stage for a fully calibrated app without a transcript', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/apps/app-1': calibratedApp })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Run app' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1/use'))
  })

  it('surfaces clarification outcomes in the chat panel', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps/app-1': draftApp,
      'POST /v1/apps/app-1/turns': {
        reply: 'I need more detail.',
        outcome: { kind: 'needs_input', questions: ['Which signal governs this lane?'] },
      },
      'POST /v1/apps/app-1/clarifications': {
        reply: 'Thanks.',
        outcome: proposedVersion,
      },
    })))
    render(<WorkspacePage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    await user.type(await screen.findByRole('textbox', { name: 'Message' }), 'Catch red light runners')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await user.type(await screen.findByLabelText('Which signal governs this lane?'), 'Left signal')
    await user.click(screen.getByRole('button', { name: 'Submit clarification' }))
    expect(await screen.findByRole('heading', { name: 'Red light crossing' })).toBeInTheDocument()
  })
})
