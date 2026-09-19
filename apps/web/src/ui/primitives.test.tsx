import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ---------------------------------------------------------------------------
// RED tests for UI primitives
// ---------------------------------------------------------------------------

import { Button } from './Button'
import { Input } from './Input'
import { Card } from './Card'
import { Loading } from './Loading'
import { ErrorBoundary } from './ErrorBoundary'
import { theme } from './theme'

// ---------------------------------------------------------------------------
// Theme tokens
// ---------------------------------------------------------------------------
describe('theme', () => {
  it('exports color tokens', () => {
    expect(theme.colors).toBeDefined()
    expect(theme.colors.primary).toBeTruthy()
    expect(theme.colors.error).toBeTruthy()
    expect(theme.colors.background).toBeTruthy()
    expect(theme.colors.surface).toBeTruthy()
    expect(theme.colors.text).toBeTruthy()
  })

  it('exports spacing tokens', () => {
    expect(theme.spacing).toBeDefined()
    expect(theme.spacing.xs).toBeTruthy()
    expect(theme.spacing.sm).toBeTruthy()
    expect(theme.spacing.md).toBeTruthy()
    expect(theme.spacing.lg).toBeTruthy()
  })

  it('exports font size tokens', () => {
    expect(theme.fontSizes).toBeDefined()
    expect(theme.fontSizes.sm).toBeTruthy()
    expect(theme.fontSizes.md).toBeTruthy()
    expect(theme.fontSizes.lg).toBeTruthy()
  })

  it('exports border radius tokens', () => {
    expect(theme.radii).toBeDefined()
    expect(theme.radii.sm).toBeTruthy()
    expect(theme.radii.md).toBeTruthy()
  })
})

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------
describe('Button', () => {
  it('renders with text content', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument()
  })

  it('calls onClick handler when clicked', async () => {
    const user = userEvent.setup()
    const handler = vi.fn()
    render(<Button onClick={handler}>Submit</Button>)
    await user.click(screen.getByRole('button', { name: 'Submit' }))
    expect(handler).toHaveBeenCalledOnce()
  })

  it('does not fire onClick when disabled', async () => {
    const user = userEvent.setup()
    const handler = vi.fn()
    render(<Button onClick={handler} disabled>Submit</Button>)
    await user.click(screen.getByRole('button', { name: 'Submit' }))
    expect(handler).not.toHaveBeenCalled()
  })

  it('renders with variant="primary" by default', () => {
    render(<Button>Primary</Button>)
    const btn = screen.getByRole('button', { name: 'Primary' })
    expect(btn.dataset.variant).toBe('primary')
  })

  it('renders with variant="secondary"', () => {
    render(<Button variant="secondary">Secondary</Button>)
    const btn = screen.getByRole('button', { name: 'Secondary' })
    expect(btn.dataset.variant).toBe('secondary')
  })

  it('renders with variant="danger"', () => {
    render(<Button variant="danger">Danger</Button>)
    const btn = screen.getByRole('button', { name: 'Danger' })
    expect(btn.dataset.variant).toBe('danger')
  })

  it('supports type="submit"', () => {
    render(<Button type="submit">Go</Button>)
    expect(screen.getByRole('button', { name: 'Go' })).toHaveAttribute('type', 'submit')
  })

  it('is keyboard accessible', async () => {
    const user = userEvent.setup()
    const handler = vi.fn()
    render(<Button onClick={handler}>Accessible</Button>)
    const btn = screen.getByRole('button', { name: 'Accessible' })
    btn.focus()
    await user.keyboard('{Enter}')
    expect(handler).toHaveBeenCalledOnce()
  })
})

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
describe('Input', () => {
  it('renders an accessible text input with label', () => {
    render(<Input label="Email" />)
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Email').tagName).toBe('INPUT')
  })

  it('displays an error message', () => {
    render(<Input label="Email" error="Required field" />)
    expect(screen.getByText('Required field')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
  })

  it('passes through value and onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Input label="Name" value="" onChange={onChange} />)
    await user.type(screen.getByLabelText('Name'), 'hello')
    expect(onChange).toHaveBeenCalled()
  })

  it('supports placeholder text', () => {
    render(<Input label="Search" placeholder="Type here..." />)
    expect(screen.getByPlaceholderText('Type here...')).toBeInTheDocument()
  })

  it('can be disabled', () => {
    render(<Input label="Disabled" disabled />)
    expect(screen.getByLabelText('Disabled')).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------
describe('Card', () => {
  it('renders children content', () => {
    render(<Card>Card content here</Card>)
    expect(screen.getByText('Card content here')).toBeInTheDocument()
  })

  it('renders with a title', () => {
    render(<Card title="Details">Body text</Card>)
    expect(screen.getByText('Details')).toBeInTheDocument()
    expect(screen.getByText('Body text')).toBeInTheDocument()
  })

  it('applies the section role for accessibility', () => {
    render(<Card title="Info">Content</Card>)
    expect(screen.getByRole('region')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------
describe('Loading', () => {
  it('renders a loading indicator with status role', () => {
    render(<Loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('displays custom message', () => {
    render(<Loading message="Processing..." />)
    expect(screen.getByText('Processing...')).toBeInTheDocument()
  })

  it('has default loading text for screen readers', () => {
    render(<Loading />)
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// ErrorBoundary
// ---------------------------------------------------------------------------
describe('ErrorBoundary', () => {
  // Suppress console.error for expected error
  const originalError = console.error
  beforeEach(() => { console.error = vi.fn() })
  afterEach(() => { console.error = originalError })

  function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
    if (shouldThrow) throw new Error('Test render error')
    return <div>Normal content</div>
  }

  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={false} />
      </ErrorBoundary>
    )
    expect(screen.getByText('Normal content')).toBeInTheDocument()
  })

  it('renders fallback UI when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    )
    expect(screen.queryByText('Normal content')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('renders custom fallback message', () => {
    render(
      <ErrorBoundary fallbackMessage="Custom error text">
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    )
    expect(screen.getByText('Custom error text')).toBeInTheDocument()
  })

  it('provides a retry button that resets the error state', async () => {
    const user = userEvent.setup()
    let shouldThrow = true
    function Conditional() {
      if (shouldThrow) throw new Error('Boom')
      return <div>Recovered</div>
    }

    render(
      <ErrorBoundary>
        <Conditional />
      </ErrorBoundary>
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()

    shouldThrow = false
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(screen.getByText('Recovered')).toBeInTheDocument()
  })
})
