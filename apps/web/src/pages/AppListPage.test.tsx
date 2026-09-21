import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../client'
import { AppListPage } from './AppListPage'
import { jsonResponse, mockFetchRouter } from './workspace-test-fixtures'

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

  it('confirms inline, supports cancellation, and removes only the deleted app', async () => {
    const user = userEvent.setup()
    window.location.hash = '#/'
    const deleteRequest = vi.fn(() => jsonResponse({ deleted: true }))
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps': { apps: [
        { id: 'app-1', name: 'Crossing watcher' },
        { id: 'app-2', name: 'Smoke detector' },
      ] },
      'DELETE /v1/apps/app-1': deleteRequest,
    })))
    render(<AppListPage apiClient={apiClient} />)

    await user.click(await screen.findByRole('button', { name: 'Delete Crossing watcher' }))
    expect(deleteRequest).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Delete this app?')).not.toBeInTheDocument()
    expect(deleteRequest).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Delete Crossing watcher' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Crossing watcher' }))
    await waitFor(() => expect(screen.queryByRole('link', { name: 'Crossing watcher' })).not.toBeInTheDocument())
    expect(deleteRequest).toHaveBeenCalledOnce()
    expect(screen.getByRole('link', { name: 'Smoke detector' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#/')
  })

  it('keeps the app after a deletion failure and allows retrying', async () => {
    const user = userEvent.setup()
    const deleteRequest = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ message: 'Could not save deletion. Try again.' }, 503))
      .mockResolvedValueOnce(jsonResponse({ deleted: true }))
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps': { apps: [{ id: 'app-1', name: 'Crossing watcher' }] },
      'DELETE /v1/apps/app-1': deleteRequest,
    })))
    render(<AppListPage apiClient={apiClient} />)

    await user.click(await screen.findByRole('button', { name: 'Delete Crossing watcher' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Crossing watcher' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save deletion')
    expect(screen.getByRole('link', { name: 'Crossing watcher' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm delete Crossing watcher' }))
    expect(await screen.findByText(/no apps yet/i)).toBeInTheDocument()
    expect(deleteRequest).toHaveBeenCalledTimes(2)
  })

  it('disables deletion controls while the request is pending', async () => {
    const user = userEvent.setup()
    let finishDeletion!: (response: Response) => void
    const pending = new Promise<Response>((resolve) => { finishDeletion = resolve })
    const deleteRequest = vi.fn(() => pending)
    vi.stubGlobal('fetch', vi.fn(mockFetchRouter({
      'GET /v1/apps': { apps: [{ id: 'app-1', name: 'Crossing watcher' }] },
      'DELETE /v1/apps/app-1': deleteRequest,
    })))
    render(<AppListPage apiClient={apiClient} />)

    await user.click(await screen.findByRole('button', { name: 'Delete Crossing watcher' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Crossing watcher' }))
    expect(screen.getByRole('button', { name: 'Confirm delete Crossing watcher' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByText('Deleting…')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Crossing watcher' })).toBeInTheDocument()
    finishDeletion(jsonResponse({ deleted: true }))
    expect(await screen.findByText(/no apps yet/i)).toBeInTheDocument()
  })
})
