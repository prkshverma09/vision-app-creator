import { describe, it, expect, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { type ReactNode } from 'react'

// ---------------------------------------------------------------------------
// RED tests for auth/session context
// ---------------------------------------------------------------------------
// 1. Provides identity state (loading / authenticated / unauthenticated)
// 2. getToken returns current token or null
// 3. Workspace context tracks selected workspace
// 4. Sign-out clears identity
// ---------------------------------------------------------------------------

import {
  AuthProvider,
  useAuth,
  WorkspaceProvider,
  useWorkspace,
  type AuthState,
  type FirebaseAuthAdapter,
} from './auth-context'

// --- Test helper to consume context ---
function AuthConsumer() {
  const auth = useAuth()
  return (
    <div>
      <span data-testid="status">{auth.status}</span>
      <span data-testid="uid">{auth.user?.uid ?? 'none'}</span>
      <button onClick={() => auth.signOut()}>Sign Out</button>
    </div>
  )
}

function WorkspaceConsumer() {
  const ws = useWorkspace()
  return (
    <div>
      <span data-testid="workspace-id">{ws.workspaceId ?? 'none'}</span>
      <button onClick={() => ws.setWorkspaceId('ws-42')}>Set WS</button>
      <button onClick={() => ws.setWorkspaceId(null)}>Clear WS</button>
    </div>
  )
}

// --- Fake Firebase auth adapter for testing ---
function createFakeAuth(opts?: { initialUser?: { uid: string; email: string } }): FirebaseAuthAdapter {
  let listener: ((user: { uid: string; email: string } | null) => void) | null = null
  const currentUser = opts?.initialUser ?? null

  return {
    onAuthStateChanged(callback) {
      listener = callback
      // Simulate async auth resolution
      Promise.resolve().then(() => callback(currentUser))
      return () => { listener = null }
    },
    async getIdToken() {
      return currentUser ? `token-for-${currentUser.uid}` : null
    },
    async signOut() {
      if (listener) listener(null)
    },
  }
}

describe('AuthProvider', () => {
  it('starts in loading state', () => {
    const adapter = createFakeAuth()
    render(
      <AuthProvider adapter={adapter}>
        <AuthConsumer />
      </AuthProvider>
    )
    // Before auth resolves, status should be loading
    expect(screen.getByTestId('status').textContent).toBe('loading')
  })

  it('transitions to authenticated when user present', async () => {
    const adapter = createFakeAuth({ initialUser: { uid: 'u1', email: 'a@b.com' } })
    render(
      <AuthProvider adapter={adapter}>
        <AuthConsumer />
      </AuthProvider>
    )
    // Wait for async auth resolution
    await screen.findByText('authenticated')
    expect(screen.getByTestId('uid').textContent).toBe('u1')
  })

  it('transitions to unauthenticated when no user', async () => {
    const adapter = createFakeAuth()
    render(
      <AuthProvider adapter={adapter}>
        <AuthConsumer />
      </AuthProvider>
    )
    await screen.findByText('unauthenticated')
    expect(screen.getByTestId('uid').textContent).toBe('none')
  })

  it('getToken returns token for authenticated user', async () => {
    const adapter = createFakeAuth({ initialUser: { uid: 'u2', email: 'b@c.com' } })
    let tokenResult: string | null = null
    function TokenConsumer() {
      const auth = useAuth()
      return (
        <button onClick={async () => { tokenResult = await auth.getToken() }}>
          Get Token
        </button>
      )
    }

    render(
      <AuthProvider adapter={adapter}>
        <TokenConsumer />
      </AuthProvider>
    )
    // Wait for auth resolution
    await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    await act(async () => {
      screen.getByText('Get Token').click()
    })
    expect(tokenResult).toBe('token-for-u2')
  })

  it('signOut transitions to unauthenticated', async () => {
    const adapter = createFakeAuth({ initialUser: { uid: 'u3', email: 'c@d.com' } })
    render(
      <AuthProvider adapter={adapter}>
        <AuthConsumer />
      </AuthProvider>
    )

    await screen.findByText('authenticated')
    await act(async () => {
      screen.getByText('Sign Out').click()
    })
    expect(screen.getByTestId('status').textContent).toBe('unauthenticated')
    expect(screen.getByTestId('uid').textContent).toBe('none')
  })
})

describe('WorkspaceProvider', () => {
  it('starts with no workspace selected', () => {
    const adapter = createFakeAuth()
    render(
      <AuthProvider adapter={adapter}>
        <WorkspaceProvider>
          <WorkspaceConsumer />
        </WorkspaceProvider>
      </AuthProvider>
    )
    expect(screen.getByTestId('workspace-id').textContent).toBe('none')
  })

  it('allows selecting and clearing workspace', async () => {
    const adapter = createFakeAuth({ initialUser: { uid: 'u1', email: 'a@b.com' } })
    render(
      <AuthProvider adapter={adapter}>
        <WorkspaceProvider>
          <WorkspaceConsumer />
        </WorkspaceProvider>
      </AuthProvider>
    )

    await act(async () => { screen.getByText('Set WS').click() })
    expect(screen.getByTestId('workspace-id').textContent).toBe('ws-42')

    await act(async () => { screen.getByText('Clear WS').click() })
    expect(screen.getByTestId('workspace-id').textContent).toBe('none')
  })
})
