import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import { RunPage } from './RunPage'
import { jsonResponse, mockFetchRouter, sampleEvent, succeededRun } from './workspace-test-fixtures'

const apiClient = createApiClient({ getToken: async () => 'test-token' })

describe('RunPage', () => {
  beforeEach(() => {
    window.location.hash = '#/app/app-1/run/run-1'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('polls queued then running then succeeded and stops at completion', async () => {
    vi.useFakeTimers()
    let requestCount = 0
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': () => jsonResponse({
        run: { ...succeededRun.run, status: ['queued', 'running', 'succeeded'][Math.min(requestCount++, 2)], analysis_mode: 'gemini', asset_id: 'asset-2', version_id: 'ver-1' },
        events: [],
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    await act(async () => { render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />) })
    expect(screen.getByText('Run queued')).toBeInTheDocument()
    expect(screen.queryByText(/No matching observations/)).not.toBeInTheDocument()
    expect(screen.queryByText('Total: 0')).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(screen.getByText('Run running')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(screen.getByText('Run succeeded')).toBeInTheDocument()
    expect(screen.getByText(/No matching observations/)).toBeInTheDocument()
    expect(screen.getByText(/AI findings may be inaccurate/).closest('details')).not.toHaveAttribute('open')
    expect(screen.getByText(/Published version: ver-1 · Source: asset-2/)).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('shows terminal failure reasons rather than successful empty results and stops polling', async () => {
    vi.useFakeTimers()
    let requestCount = 0
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': () => jsonResponse({
        run: { ...succeededRun.run, status: requestCount++ === 0 ? 'running' : 'failed', failure_reason: 'Provider rejected this video' },
        events: [],
      }),
    }))
    vi.stubGlobal('fetch', fetchMock)
    await act(async () => { render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />) })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(screen.getByRole('alert')).toHaveTextContent('Provider rejected this video')
    expect(screen.queryByText(/No matching observations/)).not.toBeInTheDocument()
    expect(screen.queryByText('Total: 0')).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('clears scheduled polling and aborts the fetch signal on unmount', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': { run: { ...succeededRun.run, status: 'queued' }, events: [] },
    }))
    vi.stubGlobal('fetch', fetchMock)
    let unmount = () => {}
    await act(async () => { ({ unmount } = render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)) })
    const signal = fetchMock.mock.calls[0][1]?.signal
    unmount()
    expect(signal?.aborted).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('ignores a pending response after unmount without scheduling another poll', async () => {
    vi.useFakeTimers()
    let resolveResponse: (response: Response) => void = () => {}
    const fetchMock = vi.fn(() => new Promise<Response>((resolve) => { resolveResponse = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    let unmount = () => {}
    await act(async () => { ({ unmount } = render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)) })
    unmount()
    await act(async () => {
      resolveResponse(jsonResponse({ run: { ...succeededRun.run, status: 'running' }, events: [] }))
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('rejects run data from a different app lineage', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': { ...succeededRun, run: { ...succeededRun.run, app_id: 'another-app' } },
    })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('does not belong to this app')
    expect(screen.queryByTestId('event-card-ev-1')).not.toBeInTheDocument()
  })

  it('shows cancellation without treating it as a successful empty run', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': { run: { ...succeededRun.run, status: 'cancelled' }, events: [] },
    })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Analysis was cancelled')
    expect(screen.queryByText(/No matching observations/)).not.toBeInTheDocument()
  })

  it('shows a visual finding summary and clickable timeline that seeks playback', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': succeededRun })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    const summary = await screen.findByRole('region', { name: 'Run result' })
    expect(summary).toHaveTextContent('1 finding')
    expect(summary).toHaveAttribute('data-result', 'findings')
    const marker = screen.getByRole('button', { name: /Jump to finding/ })
    await userEvent.click(marker)
    const video = screen.getByLabelText('Run source video') as HTMLVideoElement
    expect(video.currentTime).toBe(sampleEvent.source_range.start_ms / 1000)
    expect(screen.getByTestId('event-card-ev-1')).toHaveAttribute('aria-selected', 'true')
  })

  it('distinguishes an inconclusive result from a successful no-match result', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': {
      ...succeededRun, events: [{ ...sampleEvent, machine_decision: 'inconclusive' }],
    } })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    const summary = await screen.findByRole('region', { name: 'Run result' })
    expect(summary).toHaveAttribute('data-result', 'uncertain')
    expect(summary).toHaveTextContent('Needs review')
    expect(screen.queryByRole('heading', { name: 'No matches' })).not.toBeInTheDocument()
  })

  it('loads the run and lists events for the selected attempt', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': succeededRun })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)

    expect(await screen.findByText(/run succeeded/i)).toBeInTheDocument()
    expect(screen.getByTestId('event-card-ev-1')).toBeInTheDocument()
    expect(screen.getByLabelText('Run result')).toBeInTheDocument()
  })

  it('shows an error alert when the run cannot be fetched', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': () => jsonResponse(
        { code: 'not_found', message: 'Run run-1 does not exist.', field_errors: {}, request_id: 'r1', retryable: false },
        404,
      ),
    })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Run run-1 does not exist.')
  })

  it('selects an event and shows its evidence', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': succeededRun })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)

    await user.click(await screen.findByTestId('event-card-ev-1'))
    expect(await screen.findByText('clip clip-1')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /approve|reject/i })).not.toBeInTheDocument()
  })

  it('shows a processing status while the run is not finished', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': {
        run: { id: 'run-1', app_id: 'app-1', status: 'running' },
        events: [],
      },
    })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)

    expect(await screen.findByText(/run running/i)).toBeInTheDocument()
  })
})
