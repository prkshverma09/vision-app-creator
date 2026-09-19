import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import type { DirectUploader } from '../features/upload'
import { STANDARD_GEOMETRIES } from '../features/video'
import { UseAppPage } from './UseAppPage'
import {
  calibratedApp,
  draftApp,
  liveRuntime,
  mockFetchRouter,
  semanticApp,
  sourcedApp,
} from './workspace-test-fixtures'

const apiClient = createApiClient({ getToken: async () => 'test-token' })

const instantUploader: DirectUploader = async (_grant, _file, onProgress) => {
  onProgress(100)
}

function videoFile() {
  return new File([new Uint8Array(64)], 'crossing.mp4', { type: 'video/mp4' })
}

const publishedTrackedApp = {
  ...calibratedApp,
  published_version_id: 'ver-1',
  requires_calibration: true,
  seed_asset_id: 'asset-1',
}

function uploadRoutes() {
  return {
    'POST /v1/uploads': { upload_id: 'upload-1', upload_url: 'https://upload.test/object' },
    'POST /v1/uploads/upload-1/complete': {
      asset_id: 'asset-2',
      status: 'ready',
      duration_ms: 12_500,
      width: 640,
      height: 360,
    },
    'POST /v1/apps/app-1/source': { ...publishedTrackedApp, source: { ...sourcedApp.source, asset_id: 'asset-2' } },
    'POST /v1/apps/app-1/calibrations': { calibration_id: 'cal-2' },
    'POST /v1/apps/app-1/runs': { run_id: 'run-1' },
  }
}

describe('UseAppPage', () => {
  beforeEach(() => {
    window.location.hash = '#/app/app-1/use'
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fixture-video'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('runs the attached source without re-uploading', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': semanticApp,
      'GET /v1/apps/app-1/runs': { runs: [] },
      'POST /v1/apps/app-1/runs': { run_id: 'run-9' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<UseAppPage apiClient={apiClient} appId="app-1" />)

    await user.click(await screen.findByRole('button', { name: 'Run app' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1/run/run-9'))
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/runs', expect.objectContaining({ body: JSON.stringify({ confirm_external_processing: true }) }))
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/source'))).toBe(false)
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('uploads a new video, applies standard calibration, and runs', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runtime': liveRuntime,
      'GET /v1/apps/app-1': publishedTrackedApp,
      'GET /v1/apps/app-1/runs': { runs: [] },
      ...uploadRoutes(),
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<UseAppPage apiClient={apiClient} appId="app-1" uploader={instantUploader} />)

    await user.upload(await screen.findByLabelText(/choose an mp4 video/i), videoFile())
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1/run/run-1'))
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/source', expect.objectContaining({ body: JSON.stringify({ asset_id: 'asset-2' }) }))
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/calibrations', expect.objectContaining({ body: JSON.stringify({ geometries: STANDARD_GEOMETRIES }) }))
    expect(fetchMock).toHaveBeenCalledWith('/v1/apps/app-1/runs', expect.objectContaining({ body: JSON.stringify({ confirm_external_processing: true }) }))
    const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST').map(([path]) => String(path))
    expect(posts.indexOf('/v1/apps/app-1/source')).toBeLessThan(posts.indexOf('/v1/apps/app-1/calibrations'))
    expect(posts.indexOf('/v1/apps/app-1/calibrations')).toBeLessThan(posts.indexOf('/v1/apps/app-1/runs'))
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('shows run history with each source and version under the correct app', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps/app-1': semanticApp,
      'GET /v1/apps/app-1/runs': { runs: [
        { id: 'seed-run', app_id: 'app-1', status: 'succeeded', asset_id: 'asset-1', version_id: 'ver-1', is_seed_run: true },
        { id: 'new-run', app_id: 'app-1', status: 'failed', asset_id: 'asset-2', version_id: 'ver-1', failure_reason: 'Video unreadable' },
        { id: 'other-run', app_id: 'app-other', status: 'succeeded' },
      ] },
    })))
    render(<UseAppPage apiClient={apiClient} appId="app-1" />)
    expect(await screen.findByRole('link', { name: 'Run seed-run' })).toHaveAttribute('href', '#/app/app-1/run/seed-run')
    expect(screen.getByRole('link', { name: 'Run new-run' }).parentElement).toHaveTextContent('Source: asset-2 · Version: ver-1')
    expect(screen.queryByRole('link', { name: 'Run other-run' })).not.toBeInTheDocument()
  })

  it('asks to finish building when the app is not published', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps/app-1': draftApp,
      'GET /v1/apps/app-1/runs': { runs: [] },
    })))
    render(<UseAppPage apiClient={apiClient} appId="app-1" />)
    expect(await screen.findByText(/not published yet/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/choose an mp4 video/i)).not.toBeInTheDocument()
  })
})
