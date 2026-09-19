import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import { trackedRulesSpec } from '../features/chat/test-fixtures'
import { RunPage } from './RunPage'
import type { RunResponse } from './types'
import { jsonResponse, mockFetchRouter, sampleEvent, succeededRun } from './workspace-test-fixtures'

const apiClient = createApiClient({ getToken: async () => 'test-token' })
const analyzedRun: RunResponse = {
  ...succeededRun,
  run: { ...succeededRun.run, analysis_mode: 'gemini', analysis_complete: true, spec: trackedRulesSpec },
}

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
    expect(screen.getByLabelText('Run result')).toHaveTextContent('Analyzing your video…')
    expect(screen.queryByText(/No matching activity/)).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(screen.getByLabelText('Run result')).toHaveTextContent('Analyzing your video…')
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(screen.getByLabelText('Run result')).toHaveTextContent('No matching activity was detected in this video.')
    expect(screen.queryByText(/Published version/)).not.toBeInTheDocument()
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
    expect(screen.getByRole('alert')).toHaveTextContent('The video could not be analyzed')
    expect(screen.getByText('Provider rejected this video').closest('details')).not.toHaveAttribute('open')
    expect(screen.queryByText(/No matching activity/)).not.toBeInTheDocument()
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
    expect(screen.queryByText(/No matching activity/)).not.toBeInTheDocument()
  })

  it('shows one plain sentence with source playback and no result panels or technical metadata', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': analyzedRun })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    const summary = await screen.findByLabelText('Run result')
    expect(summary.tagName).toBe('P')
    expect(summary).toHaveTextContent('A vehicle crossed the stop line while the light was red.')
    expect(screen.getByLabelText('Run source video')).toHaveAttribute('src', 'blob:fixture-video')
    expect(screen.queryByRole('button', { name: 'Next frame' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '← App' })).toHaveAttribute('href', '#/app/app-1/use')
    expect(screen.queryByLabelText('Findings timeline')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Detected events')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Event detail')).not.toBeInTheDocument()
    expect(screen.queryByTestId('event-card-ev-1')).not.toBeInTheDocument()
    expect(screen.queryByText(/Run run-1|Rule:|Tracks:|Revision|supported/)).not.toBeInTheDocument()
  })

  it.each<{ name: string; data: RunResponse; expected: string }>([
    {
      name: 'completed negative',
      data: { ...analyzedRun, events: [] },
      expected: 'No red-light violations were detected in this video.',
    },
    {
      name: 'rejected observation',
      data: { ...analyzedRun, events: [{ ...sampleEvent, machine_decision: 'rejected' }] },
      expected: 'No red-light violations were detected in this video.',
    },
    {
      name: 'inconclusive observation',
      data: { ...analyzedRun, events: [{ ...sampleEvent, machine_decision: 'inconclusive' }] },
      expected: 'The video is inconclusive — the app could not determine whether the activity occurred.',
    },
    {
      name: 'candidate description from Gemini',
      data: { ...analyzedRun, events: [{ ...sampleEvent, machine_decision: 'candidate', facts: {
        description: 'A white car crossed the yellow line while the light was red. The car continued forward.',
      } }] },
      expected: 'Possible match: A white car crossed the yellow line while the light was red.',
    },
    {
      name: 'a different app without a description',
      data: { ...analyzedRun, run: { ...analyzedRun.run, spec: undefined }, events: [sampleEvent] },
      expected: 'Matching activity was detected in this video.',
    },
    {
      name: 'a different app with a description',
      data: { ...analyzedRun, events: [{ ...sampleEvent, facts: { description: 'Smoke is visible near the door' } }] },
      expected: 'Smoke is visible near the door.',
    },
    {
      name: 'a different app with no findings',
      data: { ...analyzedRun, run: { ...analyzedRun.run, spec: undefined }, events: [] },
      expected: 'No matching activity was detected in this video.',
    },
    {
      name: 'a partial run with no findings',
      data: { ...analyzedRun, run: { ...analyzedRun.run, analysis_complete: false }, events: [] },
      expected: 'Only part of the video was analyzed — no complete result is available.',
    },
    {
      name: 'a partial run with findings',
      data: { ...analyzedRun, run: { ...analyzedRun.run, analysis_complete: false } },
      expected: 'Only part of the video was analyzed — no complete result is available.',
    },
    {
      name: 'scripted positive fixture',
      data: { ...analyzedRun, run: { ...analyzedRun.run, analysis_mode: 'scripted' } },
      expected: 'Demo only: this video has not been analyzed.',
    },
    {
      name: 'scripted negative fixture',
      data: { ...analyzedRun, run: { ...analyzedRun.run, analysis_mode: 'scripted' }, events: [] },
      expected: 'Demo only: this video has not been analyzed.',
    },
  ])('reports $name honestly', async ({ data, expected }) => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/runs/run-1': data })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    expect(await screen.findByLabelText('Run result')).toHaveTextContent(expected)
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

  it('retries a failed request and displays the result', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValueOnce(jsonResponse(analyzedRun))
    vi.stubGlobal('fetch', fetchMock)
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByLabelText('Run result')).toHaveTextContent('A vehicle crossed the stop line')
  })

  it('shows a processing status while the run is not finished', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/runs/run-1': {
        run: { id: 'run-1', app_id: 'app-1', status: 'running' },
        events: [],
      },
    })))
    render(<RunPage apiClient={apiClient} appId="app-1" runId="run-1" />)

    expect(await screen.findByLabelText('Run result')).toHaveTextContent('Analyzing your video…')
  })
})
