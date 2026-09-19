import { Component, type ErrorInfo, type ReactNode } from 'react'
import { theme } from './theme'

export interface ErrorBoundaryProps {
  children: ReactNode
  fallbackMessage?: string
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

const alertStyle: React.CSSProperties = {
  padding: theme.spacing.md,
  backgroundColor: '#fef2f2', // red-50
  border: `1px solid ${theme.colors.error}`,
  borderRadius: theme.radii.md,
  color: theme.colors.error,
}

const buttonStyle: React.CSSProperties = {
  marginTop: theme.spacing.sm,
  padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
  backgroundColor: theme.colors.error,
  color: theme.colors.textInverse,
  border: 'none',
  borderRadius: theme.radii.sm,
  cursor: 'pointer',
  fontSize: theme.fontSizes.sm,
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Log to console in dev; in production this would go to an error service
    console.error('ErrorBoundary caught:', error, info)
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      const message = this.props.fallbackMessage ?? 'Something went wrong'
      return (
        <div role="alert" style={alertStyle}>
          <p style={{ margin: 0 }}>{message}</p>
          <button onClick={this.handleRetry} style={buttonStyle}>
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
