import { useMemo } from 'react'
import { createApiClient } from './client'
import { AppListPage, RunPage, UseAppPage, WorkspacePage, useRoute } from './pages'
import { ErrorBoundary, Shell } from './ui'

function AppRoutes() {
  const route = useRoute()
  const apiClient = useMemo(() => createApiClient({ getToken: async () => '' }), [])

  switch (route.name) {
    case 'workspace':
      return <WorkspacePage apiClient={apiClient} appId={route.appId} />
    case 'use':
      return <UseAppPage apiClient={apiClient} appId={route.appId} />
    case 'run':
      return <RunPage apiClient={apiClient} appId={route.appId} runId={route.runId} />
    default:
      return <AppListPage apiClient={apiClient} />
  }
}

export function App() {
  return (
    <Shell>
      <ErrorBoundary fallbackMessage="The workspace could not be displayed. Try reloading the page.">
        <AppRoutes />
      </ErrorBoundary>
    </Shell>
  )
}
