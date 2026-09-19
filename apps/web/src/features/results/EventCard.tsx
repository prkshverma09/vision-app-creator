import type { CSSProperties } from 'react'
import type { Event } from '@vision-app/contracts'
import { theme } from '../../ui/theme'

export interface EventCardProps {
  event: Event
  isSelected: boolean
  onSelect: () => void
  compact?: boolean
}

const formatSeconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`

const badgeStyle = (color: string): CSSProperties => ({
  display: 'inline-block',
  padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
  borderRadius: theme.radii.full,
  backgroundColor: color,
  color: theme.colors.textInverse,
  fontSize: theme.fontSizes.xs,
  fontWeight: 600,
  marginRight: theme.spacing.sm,
  marginBottom: theme.spacing.xs,
})

const decisionColor: Record<Event['machine_decision'], string> = {
  supported: theme.colors.success,
  rejected: theme.colors.secondary,
  inconclusive: theme.colors.warning,
  candidate: theme.colors.primary,
}

export function EventCard({ event, isSelected, onSelect, compact = false }: EventCardProps) {
  const startS = formatSeconds(event.source_range.start_ms)
  const endS = formatSeconds(event.source_range.end_ms)

  const baseStyle: CSSProperties = {
    border: `1px solid ${isSelected ? theme.colors.primary : theme.colors.surfaceBorder}`,
    borderRadius: theme.radii.md,
    padding: theme.spacing.md,
    backgroundColor: theme.colors.surface,
    cursor: 'pointer',
    boxShadow: isSelected ? `0 0 0 2px ${theme.colors.primary}` : theme.shadows.sm,
  }

  const headerStyle: CSSProperties = {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: theme.spacing.sm,
  }

  const idStyle: CSSProperties = {
    fontWeight: 600,
    fontSize: theme.fontSizes.md,
    color: theme.colors.text,
  }

  const metaStyle: CSSProperties = {
    color: theme.colors.textSecondary,
    fontSize: theme.fontSizes.sm,
    marginBottom: theme.spacing.xs,
  }

  const factListStyle: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
    gap: theme.spacing.xs,
    marginTop: theme.spacing.sm,
    fontSize: theme.fontSizes.sm,
  }

  const evidenceStyle: CSSProperties = {
    marginTop: theme.spacing.sm,
    fontSize: theme.fontSizes.sm,
    color: theme.colors.textSecondary,
  }

  if (compact) return (
    <li role="listitem" aria-selected={isSelected} data-testid={`event-card-${event.id}`} data-event-id={event.id}
      style={{ ...baseStyle, display: 'grid', gridTemplateColumns: '96px minmax(0, 1fr)', gap: 12, padding: 12 }}
      tabIndex={0} onClick={onSelect} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() } }}>
      {event.evidence.thumbnail_ref ? <img src={`/api/v1/media/${event.evidence.thumbnail_ref}`} alt="evidence thumbnail" style={{ width: 96, height: 72, objectFit: 'cover', borderRadius: 6 }} />
        : <div style={{ background: '#f1f5f9', borderRadius: 6, display: 'grid', placeItems: 'center' }}>No image</div>}
      <div>
        <strong>{startS} – {endS}</strong>
        <p style={{ margin: '6px 0', fontSize: 14, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
          {String(event.facts.description ?? event.facts.object_class ?? 'Detected activity')}
        </p>
        <span style={{ fontSize: 12, color: decisionColor[event.machine_decision] }}>{event.machine_decision === 'inconclusive' ? 'Uncertain' : event.machine_decision === 'rejected' ? 'Not matched' : 'Finding'}</span>
      </div>
    </li>
  )

  return (
    <li
      role="listitem"
      aria-selected={isSelected}
      data-testid={`event-card-${event.id}`}
      data-event-id={event.id}
      style={baseStyle}
      onClick={onSelect}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <div style={headerStyle}>
        <span style={idStyle}>{event.id}</span>
        <span style={badgeStyle(decisionColor[event.machine_decision])}>{event.machine_decision}</span>
      </div>

      <div style={metaStyle}>Time: {startS} – {endS}</div>
      <div style={metaStyle}>Rule: {event.rule_id}</div>
      <div style={metaStyle}>Tracks: {event.track_refs.join(', ') || 'none'}</div>
      <div style={metaStyle}>Revision {event.revision}</div>

      <div style={factListStyle}>
        {Object.entries(event.facts).map(([key, value]) => (
          <div key={key}>
            <strong>{key}:</strong> {String(value)}
          </div>
        ))}
      </div>

      <div style={evidenceStyle}>
        {event.evidence.state === 'failed' && (
          <span role="alert" style={{ color: theme.colors.danger }}>evidence extraction failed</span>
        )}
        {event.evidence.state === 'degraded' && (
          <span style={{ color: theme.colors.warning }}>evidence degraded</span>
        )}
        {event.evidence.thumbnail_ref ? (
          <img
            src={`/api/v1/media/${event.evidence.thumbnail_ref}`}
            alt="evidence thumbnail"
            style={{ maxWidth: '120px', borderRadius: theme.radii.sm, marginRight: theme.spacing.sm }}
          />
        ) : (
          event.evidence.state !== 'failed' && event.evidence.state !== 'degraded' && <span>No thumbnail</span>
        )}
        {event.evidence.clip_ref ? (
          <span>clip available</span>
        ) : (
          <span>No clip</span>
        )}
      </div>
    </li>
  )
}
