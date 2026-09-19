import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Event } from '@vision-app/contracts'
import { EventCard } from './EventCard'

function makeEvent(overrides: Partial<Event> = {}): Event {
  return {
    id: 'evt-1',
    run_id: 'run-1',
    attempt_id: 'attempt-1',
    spec_version_id: 'ver-1',
    calibration_id: 'cal-1',
    source_range: { start_ms: 12000, end_ms: 15000 },
    rule_id: 'rule-red-light',
    track_refs: ['track-1', 'track-2'],
    facts: { signal_state: 'red', vehicle_class: 'car' },
    evidence: {
      requested_range: { start_ms: 9000, end_ms: 18000 },
      actual_range: { start_ms: 9000, end_ms: 18000 },
      clip_ref: 'clip-1',
      thumbnail_ref: 'thumb-1',
      clipped_start: false,
      clipped_end: false,
      state: 'available',
    },
    machine_decision: 'supported',
    human_review: 'unreviewed',
    revision: 3,
    ...overrides,
  }
}

describe('EventCard', () => {
  it('renders event id, source timestamp and rule', () => {
    render(<EventCard event={makeEvent()} isSelected={false} onSelect={vi.fn()} />)

    expect(screen.getByText(/evt-1/)).toBeInTheDocument()
    expect(screen.getByText(/12\.0s/)).toBeInTheDocument()
    expect(screen.getByText(/rule-red-light/)).toBeInTheDocument()
  })

  it('shows track refs and facts', () => {
    render(<EventCard event={makeEvent()} isSelected={false} onSelect={vi.fn()} />)

    expect(screen.getByText(/track-1/)).toBeInTheDocument()
    expect(screen.getByText(/track-2/)).toBeInTheDocument()
    expect(screen.getByText(/signal_state/)).toBeInTheDocument()
    expect(screen.getByText(/vehicle_class/)).toBeInTheDocument()
  })

  it('indicates selected state', () => {
    render(<EventCard event={makeEvent()} isSelected={true} onSelect={vi.fn()} />)

    expect(screen.getByRole('listitem')).toHaveAttribute('aria-selected', 'true')
  })

  it('calls onSelect when clicked', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<EventCard event={makeEvent()} isSelected={false} onSelect={onSelect} />)

    await user.click(screen.getByRole('listitem'))
    expect(onSelect).toHaveBeenCalledOnce()
  })

  it('shows evidence thumbnails/clips when available', () => {
    render(<EventCard event={makeEvent()} isSelected={false} onSelect={vi.fn()} />)

    expect(screen.getByAltText(/evidence thumbnail/i)).toBeInTheDocument()
    expect(screen.getByText(/clip available/i)).toBeInTheDocument()
  })

  it('shows degraded evidence notice when evidence state is degraded', () => {
    const event = makeEvent({ evidence: { ...makeEvent().evidence, state: 'degraded', thumbnail_ref: null } })
    render(<EventCard event={event} isSelected={false} onSelect={vi.fn()} />)

    expect(screen.getByText(/evidence degraded/i)).toBeInTheDocument()
  })

  it('shows revision', () => {
    render(<EventCard event={makeEvent()} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText(/revision 3/i)).toBeInTheDocument()
  })
})
