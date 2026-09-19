import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { draftApp, mockFetchRouter, succeededRun } from './pages/workspace-test-fixtures'

function stubFetch(routes: Parameters<typeof mockFetchRouter>[0]) {
  vi.stubGlobal('fetch', vi.fn(mockFetchRouter(routes)))
}

describe('App', () => {
  beforeEach(() => {
    window.location.hash = '#/'
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders the product title in the shell header', () => {
    stubFetch({ 'GET /v1/apps': { apps: [] } })
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Vision App Creator' })).toBeInTheDocument()
  })

  it('uses the Shell layout with header and main', () => {
    stubFetch({ 'GET /v1/apps': { apps: [] } })
    render(<App />)
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
  })

  it('navigates from the app list into a workspace and back', async () => {
    const user = userEvent.setup()
    stubFetch({
      'GET /v1/apps': { apps: [{ id: 'app-1', name: 'Crossing watcher' }] },
      'GET /v1/apps/app-1': draftApp,
    })
    render(<App />)

    await user.click(await screen.findByRole('link', { name: 'Crossing watcher' }))
    expect(await screen.findByRole('region', { name: /builder chat/i })).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: /all apps|back to apps/i }))
    expect(await screen.findByText(/no apps yet|crossing watcher/i)).toBeInTheDocument()
  })

  it('deep-links to a run route and renders results', async () => {
    window.location.hash = '#/app/app-1/run/run-1'
    stubFetch({ 'GET /v1/runs/run-1': succeededRun })
    render(<App />)

    expect(await screen.findByText(/run succeeded/i)).toBeInTheDocument()
    expect(screen.getByTestId('event-card-ev-1')).toBeInTheDocument()
  })

  it('shows the global error boundary fallback when a page crashes', async () => {
    // A malformed route payload (non-object) causes the page to throw during render data access.
    window.location.hash = '#/app/app-1/run/run-1'
    stubFetch({
      'GET /v1/runs/run-1': async () => new Response('{"unexpected":true}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    })
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<App />)

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    consoleError.mockRestore()
  })
})
