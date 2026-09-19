import { describe, expect, it } from 'vitest'
import { parseHash, routeToHash } from './router'

describe('parseHash', () => {
  it('maps empty and root hashes to the app list route', () => {
    expect(parseHash('')).toEqual({ name: 'apps' })
    expect(parseHash('#')).toEqual({ name: 'apps' })
    expect(parseHash('#/')).toEqual({ name: 'apps' })
    expect(parseHash('#/apps')).toEqual({ name: 'apps' })
  })

  it('maps app hashes to the workspace route', () => {
    expect(parseHash('#/app/app-1')).toEqual({ name: 'workspace', appId: 'app-1' })
  })

  it('maps run hashes to the run route', () => {
    expect(parseHash('#/app/app-1/run/run-9')).toEqual({
      name: 'run',
      appId: 'app-1',
      runId: 'run-9',
    })
  })

  it('maps use hashes to the use-app route', () => {
    expect(parseHash('#/app/app-1/use')).toEqual({ name: 'use', appId: 'app-1' })
  })

  it('decodes URI-encoded identifiers', () => {
    expect(parseHash('#/app/my%20app/run/run%2F1')).toEqual({
      name: 'run',
      appId: 'my app',
      runId: 'run/1',
    })
  })

  it('falls back to the app list for unknown hashes', () => {
    expect(parseHash('#/nonsense')).toEqual({ name: 'apps' })
    expect(parseHash('#/app')).toEqual({ name: 'apps' })
  })
})

describe('routeToHash', () => {
  it('round-trips every route', () => {
    const routes = [
      { name: 'apps' },
      { name: 'workspace', appId: 'app-1' },
      { name: 'use', appId: 'app-1' },
      { name: 'run', appId: 'app-1', runId: 'run-2' },
    ] as const
    for (const route of routes) {
      expect(parseHash(routeToHash(route))).toEqual(route)
    }
  })
})
