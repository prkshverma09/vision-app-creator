import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Tests for Shell / global layout component
// ---------------------------------------------------------------------------

import { Shell } from './Shell'

describe('Shell', () => {
  it('renders a header with the app title', () => {
    render(
      <Shell>
        <div>Page content</div>
      </Shell>
    )
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByText('Vision App Creator')).toBeInTheDocument()
  })

  it('renders a main content area with children', () => {
    render(
      <Shell>
        <div>My feature page</div>
      </Shell>
    )
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByText('My feature page')).toBeInTheDocument()
  })

  it('renders navigation landmark', () => {
    render(
      <Shell>
        <div>Content</div>
      </Shell>
    )
    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('main')).toBeInTheDocument()
  })

  it('wraps children in ErrorBoundary', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    function Bomb(): null {
      throw new Error('Boom')
    }
    render(
      <Shell>
        <Bomb />
      </Shell>
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    spy.mockRestore()
  })
})
