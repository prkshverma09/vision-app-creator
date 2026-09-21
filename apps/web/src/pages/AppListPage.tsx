import { useCallback, useEffect, useState } from 'react'
import type { ApiClient } from '../client'
import { Button, Loading, theme } from '../ui'
import type { AppSummary } from './types'

export interface AppListPageProps {
  apiClient: ApiClient
}

function messageText(error: unknown): string {
  return error instanceof Error ? error.message : 'Unexpected error'
}

const listStyle: React.CSSProperties = {
  listStyle: 'none',
  padding: 0,
  margin: 0,
  display: 'grid',
  gap: theme.spacing.sm,
  maxWidth: '480px',
}

const itemStyle: React.CSSProperties = {
  border: `1px solid ${theme.colors.surfaceBorder}`,
  borderRadius: theme.radii.md,
  padding: theme.spacing.md,
  backgroundColor: theme.colors.surface,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  flexWrap: 'wrap',
  gap: theme.spacing.sm,
}

export function AppListPage({ apiClient }: AppListPageProps) {
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const response = await apiClient.get<{ apps: AppSummary[] }>('/v1/apps')
      setApps(response.apps)
    } catch (caught) {
      setError(messageText(caught))
    }
  }, [apiClient])

  useEffect(() => {
    void load()
  }, [load])

  const createApp = async () => {
    setCreating(true)
    setError('')
    try {
      const app = await apiClient.post<AppSummary>('/v1/apps', { name: 'Untitled app' })
      window.location.hash = `#/app/${encodeURIComponent(app.id)}`
    } catch (caught) {
      setError(messageText(caught))
      setCreating(false)
    }
  }

  const deleteApp = async (appId: string) => {
    setDeletingId(appId)
    setDeleteError('')
    try {
      await apiClient.delete(`/v1/apps/${encodeURIComponent(appId)}`)
      setApps((current) => current?.filter((app) => app.id !== appId) ?? null)
      setConfirmingId(null)
    } catch (caught) {
      setDeleteError(messageText(caught))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div>
      <h2>Your apps</h2>
      {error && (
        <div role="alert">
          <p>{error}</p>
          <Button type="button" onClick={() => void load()}>Retry</Button>
        </div>
      )}
      {!apps && !error && <Loading message="Loading apps…" />}
      {apps && apps.length === 0 && <p>No apps yet. Create one to get started.</p>}
      {apps && apps.length > 0 && (
        <ul style={listStyle} aria-label="Saved apps">
          {apps.map((app) => (
            <li key={app.id} style={itemStyle}>
              <a href={`#/app/${encodeURIComponent(app.id)}`}>{app.name}</a>
              {confirmingId === app.id ? (
                <div>
                  <span>Delete this app? </span>
                  <Button type="button" variant="secondary" disabled={deletingId !== null} onClick={() => setConfirmingId(null)}>
                    Cancel
                  </Button>{' '}
                  <Button type="button" variant="danger" aria-label={`Confirm delete ${app.name}`} disabled={deletingId !== null} onClick={() => void deleteApp(app.id)}>
                    {deletingId === app.id ? 'Deleting…' : 'Delete'}
                  </Button>
                  {deleteError && <p role="alert">{deleteError}</p>}
                </div>
              ) : (
                <Button type="button" variant="secondary" aria-label={`Delete ${app.name}`} disabled={deletingId !== null} onClick={() => {
                  setDeleteError('')
                  setConfirmingId(app.id)
                }}>
                  Delete
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div style={{ marginTop: theme.spacing.md }}>
        <Button type="button" onClick={() => void createApp()} disabled={creating}>
          {creating ? 'Creating…' : 'New app'}
        </Button>
      </div>
    </div>
  )
}
