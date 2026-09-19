import type { ReactNode } from 'react'
import { ErrorBoundary } from './ErrorBoundary'
import { theme } from './theme'

export interface ShellProps {
  children: ReactNode
}

const headerStyle: React.CSSProperties = {
  backgroundColor: theme.colors.surface,
  borderBottom: `1px solid ${theme.colors.surfaceBorder}`,
  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
  display: 'flex',
  alignItems: 'center',
  height: '56px',
  boxSizing: 'border-box',
}

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: theme.fontSizes.lg,
  fontWeight: 700,
  color: theme.colors.text,
}

const mainStyle: React.CSSProperties = {
  flex: 1,
  padding: theme.spacing.md,
  backgroundColor: theme.colors.background,
  minHeight: 0,
  overflow: 'auto',
}

const shellStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  minHeight: '100vh',
  backgroundColor: theme.colors.background,
}

export function Shell({ children }: ShellProps) {
  return (
    <div style={shellStyle}>
      <header style={headerStyle}>
        <h1 style={titleStyle}>Vision App Creator</h1>
      </header>
      <main style={mainStyle}>
        <ErrorBoundary>
          {children}
        </ErrorBoundary>
      </main>
    </div>
  )
}
