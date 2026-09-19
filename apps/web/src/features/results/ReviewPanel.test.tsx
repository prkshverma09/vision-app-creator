import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Event } from '@vision-app/contracts'
import { ReviewPanel } from './ReviewPanel'

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
    facts: {},
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

describe('ReviewPanel', () => {
  it('renders approve, reject, and mark-unknown buttons', () => {
    render(<ReviewPanel event={makeEvent()} onReview={vi.fn()} disabled={false} />)

    expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark event unknown/i })).toBeInTheDocument()
  })

  it('calls onReview with confirmed_by_user when approve is clicked', async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    render(<ReviewPanel event={makeEvent()} onReview={onReview} disabled={false} />)

    await user.click(screen.getByRole('button', { name: /approve/i }))
    expect(onReview).toHaveBeenCalledWith({ human_review: 'confirmed_by_user', note: '' })
  })

  it('calls onReview with dismissed_by_user when reject is clicked', async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    render(<ReviewPanel event={makeEvent()} onReview={onReview} disabled={false} />)

    await user.click(screen.getByRole('button', { name: /reject/i }))
    expect(onReview).toHaveBeenCalledWith({ human_review: 'dismissed_by_user', note: '' })
  })

  it('calls onReview with unreviewed when mark-unknown is clicked', async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    render(<ReviewPanel event={makeEvent()} onReview={onReview} disabled={false} />)

    await user.click(screen.getByRole('button', { name: /mark event unknown/i }))
    expect(onReview).toHaveBeenCalledWith({ human_review: 'unreviewed', note: '' })
  })

  it('includes note text in the review payload', async () => {
    const user = userEvent.setup()
    const onReview = vi.fn()
    render(<ReviewPanel event={makeEvent()} onReview={onReview} disabled={false} />)

    await user.type(screen.getByLabelText(/note/i), 'looks correct')
    await user.click(screen.getByRole('button', { name: /approve/i }))

    expect(onReview).toHaveBeenCalledWith({ human_review: 'confirmed_by_user', note: 'looks correct' })
  })

  it('disables action buttons when disabled prop is true', () => {
    render(<ReviewPanel event={makeEvent()} onReview={vi.fn()} disabled={true} />)

    expect(screen.getByRole('button', { name: /approve/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /reject/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /mark event unknown/i })).toBeDisabled()
  })

  it('shows existing review status', () => {
    render(<ReviewPanel event={makeEvent({ human_review: 'confirmed_by_user' })} onReview={vi.fn()} disabled={false} />)

    expect(screen.getByText(/reviewed: confirmed/i)).toBeInTheDocument()
  })
})
