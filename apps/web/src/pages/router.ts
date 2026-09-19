/**
 * Minimal hash-based router for the workspace SPA.
 *
 * react-router-dom is intentionally not added (root manifest changes require
 * coordinator approval). Routes:
 *   #/                      → saved app list
 *   #/app/:appId            → builder workspace
 *   #/app/:appId/run/:runId → run/results view
 */

import { useEffect, useState } from 'react'

export type Route =
  | { name: 'apps' }
  | { name: 'workspace'; appId: string }
  | { name: 'run'; appId: string; runId: string }

export function parseHash(hash: string): Route {
  const segments = hash.replace(/^#/, '').split('/').filter(Boolean)
  if (segments[0] === 'app' && segments[1]) {
    const appId = decodeURIComponent(segments[1])
    if (segments[2] === 'run' && segments[3]) {
      return { name: 'run', appId, runId: decodeURIComponent(segments[3]) }
    }
    return { name: 'workspace', appId }
  }
  return { name: 'apps' }
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case 'workspace':
      return `#/app/${encodeURIComponent(route.appId)}`
    case 'run':
      return `#/app/${encodeURIComponent(route.appId)}/run/${encodeURIComponent(route.runId)}`
    default:
      return '#/'
  }
}

/** Navigate by assigning location.hash; browsers fire `hashchange`. */
export function navigate(route: Route): void {
  window.location.hash = routeToHash(route)
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash))

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  return route
}
