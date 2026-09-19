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
}

export function AppListPage({ apiClient }: AppListPageProps) {
  const [apps, setApps] = useState<AppSummary[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

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
