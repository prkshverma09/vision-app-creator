import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ActionPreview } from './ActionPreview'

describe('ActionPreview', () => {
  it('shows webhook destination and safety notice', () => {
    render(
      <ActionPreview
        enabled={false}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1', decision: 'supported' }}
        safetyNotice="External actions are disabled in preview mode."
        onToggleEnabled={vi.fn()}
        onSend={vi.fn()}
      />
    )

    expect(screen.getByText(/https:\/\/example.com\/webhook/)).toBeInTheDocument()
    expect(screen.getByText(/External actions are disabled in preview mode./)).toBeInTheDocument()
  })

  it('shows enable toggle and calls onToggleEnabled', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    render(
      <ActionPreview
        enabled={false}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1' }}
        safetyNotice="External sends require explicit opt-in."
        onToggleEnabled={onToggle}
        onSend={vi.fn()}
      />
    )

    await user.click(screen.getByRole('switch', { name: /enable/i }))
    expect(onToggle).toHaveBeenCalledWith(true)
  })

  it('renders a send button only when enabled', () => {
    const { rerender } = render(
      <ActionPreview
        enabled={false}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1' }}
        safetyNotice="Disabled."
        onToggleEnabled={vi.fn()}
        onSend={vi.fn()}
      />
    )

    expect(screen.queryByRole('button', { name: /send/i })).not.toBeInTheDocument()

    rerender(
      <ActionPreview
        enabled={true}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1' }}
        safetyNotice="Disabled."
        onToggleEnabled={vi.fn()}
        onSend={vi.fn()}
      />
    )

    expect(screen.getByRole('button', { name: /send/i })).toBeInTheDocument()
  })

  it('calls onSend when the send button is clicked', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(
      <ActionPreview
        enabled={true}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1', decision: 'supported' }}
        safetyNotice="Ready."
        onToggleEnabled={vi.fn()}
        onSend={onSend}
      />
    )

    await user.click(screen.getByRole('button', { name: /send/i }))
    expect(onSend).toHaveBeenCalledOnce()
  })

  it('displays the dry-run payload', () => {
    render(
      <ActionPreview
        enabled={false}
        destination={{ kind: 'webhook', url: 'https://example.com/webhook' }}
        payload={{ event_id: 'evt-1', facts: { signal: 'red' } }}
        safetyNotice="Preview only."
        onToggleEnabled={vi.fn()}
        onSend={vi.fn()}
      />
    )

    expect(screen.getByText(/"event_id": "evt-1"/)).toBeInTheDocument()
    expect(screen.getByText(/"signal": "red"/)).toBeInTheDocument()
  })
})
