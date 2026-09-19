import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Event } from '@vision-app/contracts'
import { EventList } from './EventList'

function makeEvent(overrides: Partial<Event> = {}): Event {
  return {
    id: 'evt-1',
    run_id: 'run-1',
    attempt_id: 'attempt-1',
    spec_version_id: 'ver-1',
    calibration_id: 'cal-1',
    source_range: { start_ms: 12000, end_ms: 15000 },
    rule_id: 'rule-1',
    track_refs: ['track-1'],
    facts: { signal_state: 'red', direction: 'north' },
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
    revision: 1,
    ...overrides,
  }
}

describe('EventList', () => {
  it('renders event cards for each event', () => {
    const events = [makeEvent({ id: 'evt-1' }), makeEvent({ id: 'evt-2' })]
    render(<EventList events={events} selectedEventId={null} onSelectEvent={vi.fn()} />)

    expect(screen.getByRole('list')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('shows empty state when no events are provided', () => {
    render(<EventList events={[]} selectedEventId={null} onSelectEvent={vi.fn()} />)
    expect(screen.getByText(/no events/i)).toBeInTheDocument()
  })

  it('marks the selected event', () => {
    const events = [makeEvent({ id: 'evt-1' }), makeEvent({ id: 'evt-2' })]
    render(<EventList events={events} selectedEventId="evt-1" onSelectEvent={vi.fn()} />)

    const selected = screen.getByTestId('event-card-evt-1')
    expect(selected).toHaveAttribute('data-event-id', 'evt-1')
  })

  it('calls onSelectEvent when a card is clicked', async () => {
    const user = userEvent.setup()
    const events = [makeEvent({ id: 'evt-1' })]
    const onSelect = vi.fn()
    render(<EventList events={events} selectedEventId={null} onSelectEvent={onSelect} />)

    await user.click(screen.getByRole('listitem'))
    expect(onSelect).toHaveBeenCalledWith('evt-1')
  })

  it('paginates through events', async () => {
    const user = userEvent.setup()
    const events = Array.from({ length: 6 }, (_, i) => makeEvent({ id: `evt-${i + 1}` }))
    render(<EventList events={events} selectedEventId={null} onSelectEvent={vi.fn()} pageSize={2} />)

    expect(screen.getAllByRole('listitem')).toHaveLength(2)

    await user.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(/evt-3/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /previous/i }))
    expect(screen.getByText(/evt-1/)).toBeInTheDocument()
  })

  it('renders status badges for each event', () => {
    const events = [makeEvent({ id: 'evt-1', machine_decision: 'supported' })]
    render(<EventList events={events} selectedEventId={null} onSelectEvent={vi.fn()} />)

    expect(screen.getByText('supported')).toBeInTheDocument()
  })
})
