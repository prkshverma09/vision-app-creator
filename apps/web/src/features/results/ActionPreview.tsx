import type { CSSProperties } from 'react'
import { Button } from '../../ui/Button'
import { theme } from '../../ui/theme'
import type { WebhookDestination } from '@vision-app/contracts'

export interface ActionPreviewProps {
  enabled: boolean
  destination: WebhookDestination
  payload: unknown
  safetyNotice: string
  onToggleEnabled: (enabled: boolean) => void
  onSend: () => void
}

export function ActionPreview({
  enabled,
  destination,
  payload,
  safetyNotice,
  onToggleEnabled,
  onSend,
}: ActionPreviewProps) {
  const containerStyle: CSSProperties = {
    border: `1px solid ${theme.colors.surfaceBorder}`,
    borderRadius: theme.radii.md,
    padding: theme.spacing.md,
    backgroundColor: theme.colors.surface,
  }

  const noticeStyle: CSSProperties = {
    padding: theme.spacing.sm,
    borderRadius: theme.radii.sm,
    backgroundColor: theme.colors.warning + '22',
    color: theme.colors.text,
    fontSize: theme.fontSizes.sm,
    marginBottom: theme.spacing.md,
  }

  const payloadStyle: CSSProperties = {
    backgroundColor: theme.colors.background,
    padding: theme.spacing.md,
    borderRadius: theme.radii.sm,
    fontFamily: 'monospace',
    fontSize: theme.fontSizes.sm,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    marginBottom: theme.spacing.md,
  }

  const switchId = 'action-enable-toggle'

  return (
    <div style={containerStyle}>
      <div style={{ marginBottom: theme.spacing.md }}>
        <strong>Destination:</strong>{' '}
        <code>{destination.url}</code>
      </div>

      <div style={{ marginBottom: theme.spacing.md }}>
        <label htmlFor={switchId} style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm, cursor: 'pointer' }}>
          <input
            id={switchId}
            type="checkbox"
            role="switch"
            checked={enabled}
            onChange={(e) => onToggleEnabled(e.target.checked)}
          />
          <span>Enable external action</span>
        </label>
      </div>

      <div style={noticeStyle} role="note">
        {safetyNotice}
      </div>

      <div style={payloadStyle} aria-label="Dry-run payload">
        {JSON.stringify(payload, null, 2)}
      </div>

      {enabled && (
        <Button variant="primary" onClick={onSend} aria-label="Send action">
          Send
        </Button>
      )}
    </div>
  )
}
