import { useState, type CSSProperties } from 'react'
import type { Event, ReviewRequest } from '@vision-app/contracts'
import { Button } from '../../ui/Button'
import { Input } from '../../ui/Input'
import { theme } from '../../ui/theme'

export interface ReviewPanelProps {
  event: Event
  onReview: (review: ReviewRequest) => void
  disabled?: boolean
}

const reviewButtonStyle: CSSProperties = {
  display: 'flex',
  gap: theme.spacing.sm,
  marginBottom: theme.spacing.md,
}

export function ReviewPanel({ event, onReview, disabled = false }: ReviewPanelProps) {
  const [note, setNote] = useState('')

  const handleReview = (human_review: ReviewRequest['human_review']) => {
    onReview({ human_review, note })
    setNote('')
  }

  return (
    <div>
      <div style={{ marginBottom: theme.spacing.sm, color: theme.colors.textSecondary }}>
        {event.human_review === 'unreviewed'
          ? 'Review status: unreviewed'
          : `Reviewed: ${event.human_review.replace('_by_user', '')}`}
      </div>

      <div style={reviewButtonStyle}>
        <Button
          variant="primary"
          onClick={() => handleReview('confirmed_by_user')}
          disabled={disabled}
          aria-label="Approve event"
        >
          Approve
        </Button>
        <Button
          variant="danger"
          onClick={() => handleReview('dismissed_by_user')}
          disabled={disabled}
          aria-label="Reject event"
        >
          Reject
        </Button>
        <Button
          variant="secondary"
          onClick={() => handleReview('unreviewed')}
          disabled={disabled}
          aria-label="Mark event unknown"
        >
          Mark unknown
        </Button>
      </div>

      <Input
        label="Note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Add a note..."
        disabled={disabled}
      />
    </div>
  )
}
