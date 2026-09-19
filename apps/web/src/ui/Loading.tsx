import { theme } from './theme'

export interface LoadingProps {
  message?: string
}

const containerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: theme.spacing.sm,
  padding: theme.spacing.md,
  color: theme.colors.textSecondary,
  fontSize: theme.fontSizes.sm,
}

const spinnerStyle: React.CSSProperties = {
  width: '20px',
  height: '20px',
  border: `2px solid ${theme.colors.surfaceBorder}`,
  borderTopColor: theme.colors.primary,
  borderRadius: theme.radii.full,
  animation: 'spin 0.8s linear infinite',
}

export function Loading({ message }: LoadingProps) {
  const displayMessage = message ?? 'Loading...'
  return (
    <div role="status" style={containerStyle}>
      <div style={spinnerStyle} aria-hidden="true" />
      <span>{displayMessage}</span>
    </div>
  )
}
