/**
 * Auth/session context for Vision App Creator.
 *
 * Provides:
 * - FirebaseAuthAdapter interface for dependency injection (real Firebase or test stub)
 * - AuthProvider / useAuth for identity state (loading / authenticated / unauthenticated)
 * - WorkspaceProvider / useWorkspace for selected workspace context
 *
 * Design decisions (per DESIGN.md section 10):
 * - Firebase Auth hook/stub for tests; no real Firebase import in this module.
 * - Identity state is loading -> authenticated | unauthenticated.
 * - getToken returns current token or null.
 * - Production session cannot be swapped by untrusted query flag.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react'

// ---------------------------------------------------------------------------
// Firebase auth adapter interface (port for DI / testing)
// ---------------------------------------------------------------------------

export interface AuthUser {
  uid: string
  email: string
}

export interface FirebaseAuthAdapter {
  /** Subscribe to auth state changes. Returns unsubscribe function. */
  onAuthStateChanged(callback: (user: AuthUser | null) => void): () => void
  /** Get current ID token, or null if not authenticated. */
  getIdToken(): Promise<string | null>
  /** Sign out the current user. */
  signOut(): Promise<void>
}

// ---------------------------------------------------------------------------
// Auth state types
// ---------------------------------------------------------------------------

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface AuthState {
  status: AuthStatus
  user: AuthUser | null
  getToken: () => Promise<string | null>
  signOut: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Auth context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({
  adapter,
  children,
}: {
  adapter: FirebaseAuthAdapter
  children: ReactNode
}) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)

  useEffect(() => {
    const unsubscribe = adapter.onAuthStateChanged((authUser) => {
      if (authUser) {
        setUser(authUser)
        setStatus('authenticated')
      } else {
        setUser(null)
        setStatus('unauthenticated')
      }
    })
    return unsubscribe
  }, [adapter])

  const getToken = useCallback(async () => {
    return adapter.getIdToken()
  }, [adapter])

  const signOut = useCallback(async () => {
    await adapter.signOut()
  }, [adapter])

  return (
    <AuthContext value={{ status, user, getToken, signOut }}>
      {children}
    </AuthContext>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}

// ---------------------------------------------------------------------------
// Workspace context
// ---------------------------------------------------------------------------

export interface WorkspaceState {
  workspaceId: string | null
  setWorkspaceId: (id: string | null) => void
}

const WorkspaceContext = createContext<WorkspaceState | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)

  return (
    <WorkspaceContext value={{ workspaceId, setWorkspaceId }}>
      {children}
    </WorkspaceContext>
  )
}

export function useWorkspace(): WorkspaceState {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider')
  }
  return ctx
}
