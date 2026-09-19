import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import { AppListPage } from './AppListPage'
import { mockFetchRouter } from './workspace-test-fixtures'

const apiClient = createApiClient({ getToken: async () => 'test-token' })

describe('AppListPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists saved apps and deep-links into each workspace', async () => {
    const user = userEvent.setup()
    window.location.hash = '#/'
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps': { apps: [{ id: 'app-1', name: 'Crossing watcher' }] },
    })))
    render(<AppListPage apiClient={apiClient} />)

    await user.click(await screen.findByRole('link', { name: 'Crossing watcher' }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-1'))
  })

  it('creates a new app and navigates to its workspace', async () => {
    const user = userEvent.setup()
    window.location.hash = '#/'
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps': { apps: [] },
      'POST /v1/apps': { id: 'app-2', name: 'New app' },
    })))
    render(<AppListPage apiClient={apiClient} />)

    await user.click(await screen.findByRole('button', { name: /new app|create app/i }))
    await waitFor(() => expect(window.location.hash).toBe('#/app/app-2'))
  })

  it('shows an empty state when there are no apps', async () => {
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({ 'GET /v1/apps': { apps: [] } })))
    render(<AppListPage apiClient={apiClient} />)

    expect(await screen.findByText(/no apps yet/i)).toBeInTheDocument()
  })
})
