import { useMemo, useState } from 'react'
import type { Event, HumanReview, MachineDecision } from '@vision-app/contracts'
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

const filters: { key: 'all' | HumanReview | MachineDecision; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'unreviewed', label: 'Unreviewed' },
  { key: 'confirmed_by_user', label: 'Confirmed' },
  { key: 'dismissed_by_user', label: 'Dismissed' },
  { key: 'supported', label: 'Supported' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'inconclusive', label: 'Inconclusive' },
  { key: 'candidate', label: 'Candidate' },
]

export function EventList({ events, selectedEventId, onSelectEvent, pageSize = 10 }: EventListProps) {
  const [activeFilter, setActiveFilter] = useState<'all' | HumanReview | MachineDecision>('all')
  const [page, setPage] = useState(0)

  const filteredEvents = useMemo(() => {
    if (activeFilter === 'all') return events
    return events.filter(
      (e) => e.human_review === activeFilter || e.machine_decision === activeFilter
    )
  }, [events, activeFilter])

  const pageCount = Math.max(1, Math.ceil(filteredEvents.length / pageSize))
  const safePage = Math.min(page, pageCount - 1)
  const pagedEvents = filteredEvents.slice(safePage * pageSize, (safePage + 1) * pageSize)

  const counts = useMemo(() => {
    return {
      total: events.length,
      unreviewed: events.filter((e) => e.human_review === 'unreviewed').length,
      confirmed: events.filter((e) => e.human_review === 'confirmed_by_user').length,
      dismissed: events.filter((e) => e.human_review === 'dismissed_by_user').length,
      supported: events.filter((e) => e.machine_decision === 'supported').length,
      rejected: events.filter((e) => e.machine_decision === 'rejected').length,
    }
  }, [events])

  const handleFilter = (key: typeof activeFilter) => {
    setActiveFilter(key)
    setPage(0)
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: theme.spacing.sm,
          marginBottom: theme.spacing.md,
          alignItems: 'center',
        }}
      >
        {filters.map((f) => {
          const isActive = activeFilter === f.key
          return (
            <Button
              key={f.key}
              variant={isActive ? 'primary' : 'secondary'}
              onClick={() => handleFilter(f.key)}
              aria-pressed={isActive}
            >
              {f.label}
            </Button>
          )
        })}
      </div>

      <div
        style={{
          display: 'flex',
          gap: theme.spacing.md,
          marginBottom: theme.spacing.md,
          fontSize: theme.fontSizes.sm,
          color: theme.colors.textSecondary,
        }}
      >
        <span>Total: {counts.total}</span>
        <span>Unreviewed: {counts.unreviewed}</span>
        <span>Confirmed: {counts.confirmed}</span>
        <span>Dismissed: {counts.dismissed}</span>
        <span>Supported: {counts.supported}</span>
        <span>Rejected: {counts.rejected}</span>
      </div>

      {pagedEvents.length === 0 ? (
        <p style={{ color: theme.colors.textSecondary }}>No events match the current filter.</p>
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
    </div>
  )
}
