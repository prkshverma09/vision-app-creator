import { useState } from 'react'
import type { Event } from '@vision-app/contracts'
import { Button } from '../../ui/Button'
import { theme } from '../../ui/theme'
import { EventCard } from './EventCard'

export interface EventListProps {
  events: Event[]
  selectedEventId: string | null
  onSelectEvent: (id: string) => void
  pageSize?: number
  compact?: boolean
}

export function EventList({ events, selectedEventId, onSelectEvent, pageSize = 10 }: EventListProps) {
  const [page, setPage] = useState(0)

  const pageCount = Math.max(1, Math.ceil(events.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const pagedEvents = events.slice(safePage * pageSize, (safePage + 1) * pageSize)

  return (
    <div>
      {pagedEvents.length === 0 ? (
        <p style={{ color: theme.colors.textSecondary }}>No events.</p>
      ) : (
        <ul
          role="list"
          aria-label="Events"
          style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: theme.spacing.md }}
        >
          {pagedEvents.map((event) => (
            <EventCard
              key={event.id}
              event={event}
              isSelected={event.id === selectedEventId}
              onSelect={() => onSelectEvent(event.id)}
            />
          ))}
        </ul>
      )}

      {pageCount > 1 && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: theme.spacing.md,
          }}
        >
          <Button
            variant="secondary"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
          >
            Previous
          </Button>
          <span style={{ fontSize: theme.fontSizes.sm, color: theme.colors.textSecondary }}>
            Page {safePage + 1} of {pageCount}
          </span>
          <Button
            variant="secondary"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={safePage >= pageCount - 1}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
