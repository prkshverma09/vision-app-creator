import type { CSSProperties } from 'react'
import type { EvidenceManifest } from '@vision-app/contracts'
import { theme } from '../../ui/theme'

export interface EvidenceViewerProps {
  evidence: EvidenceManifest
  onSeekToSourceTime: (ms: number) => void
}

const formatSeconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`

export function EvidenceViewer({ evidence, onSeekToSourceTime }: EvidenceViewerProps) {
  const requested = evidence.requested_range
  const actual = evidence.actual_range

  const centerTime = actual
    ? Math.round((actual.start_ms + actual.end_ms) / 2)
    : Math.round((requested.start_ms + requested.end_ms) / 2)

  const containerStyle: CSSProperties = {
    border: `1px solid ${theme.colors.surfaceBorder}`,
    borderRadius: theme.radii.md,
    padding: theme.spacing.md,
    backgroundColor: theme.colors.surface,
  }

  const rangeStyle: CSSProperties = {
    display: 'flex',
    gap: theme.spacing.md,
    fontSize: theme.fontSizes.sm,
    color: theme.colors.textSecondary,
    marginBottom: theme.spacing.sm,
  }

  const thumbStyle: CSSProperties = {
    maxWidth: '100%',
    borderRadius: theme.radii.sm,
    cursor: 'pointer',
  }

  if (evidence.state === 'pending') {
    return (
      <div style={containerStyle}>
        <p>Evidence pending.</p>
        <div style={rangeStyle}>
          <span>Requested: {formatSeconds(requested.start_ms)} – {formatSeconds(requested.end_ms)}</span>
        </div>
      </div>
    )
  }

  if (evidence.state === 'failed' || !actual) {
    return (
      <div style={containerStyle}>
        <p role="alert">Evidence unavailable.</p>
        <div style={rangeStyle}>
          <span>Requested: {formatSeconds(requested.start_ms)} – {formatSeconds(requested.end_ms)}</span>
        </div>
      </div>
    )
  }

  return (
    <div style={containerStyle}>
      <div style={rangeStyle}>
        <span>Requested: {formatSeconds(requested.start_ms)} – {formatSeconds(requested.end_ms)}</span>
        <span>Actual: {formatSeconds(actual.start_ms)} – {formatSeconds(actual.end_ms)}</span>
      </div>

      {evidence.thumbnail_ref ? (
        <button
          type="button"
          onClick={() => onSeekToSourceTime(centerTime)}
          style={{ background: 'none', border: 'none', padding: 0 }}
          aria-label="Seek to evidence center"
        >
          <img
            src={`/api/v1/media/${evidence.thumbnail_ref}`}
            alt="evidence"
            style={thumbStyle}
          />
        </button>
      ) : (
        <p>No thumbnail available.</p>
      )}

      {evidence.clip_ref ? (
        <div style={{ marginTop: theme.spacing.sm, fontSize: theme.fontSizes.sm }}>
          <span>clip {evidence.clip_ref}</span>
        </div>
      ) : (
        <div style={{ marginTop: theme.spacing.sm, fontSize: theme.fontSizes.sm, color: theme.colors.textSecondary }}>
          No clip available.
        </div>
      )}

      <div style={{ marginTop: theme.spacing.sm, fontSize: theme.fontSizes.sm, color: theme.colors.warning }}>
        {evidence.clipped_start && <span>Clipped at start. </span>}
        {evidence.clipped_end && <span>Clipped at end.</span>}
      </div>
    </div>
  )
}
