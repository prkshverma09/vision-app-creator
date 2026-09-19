import type { ReactNode } from 'react'
import { theme } from './theme'

export interface CardProps {
  title?: string
  children: ReactNode
}

const cardStyle: React.CSSProperties = {
  backgroundColor: theme.colors.surface,
  border: `1px solid ${theme.colors.surfaceBorder}`,
  borderRadius: theme.radii.md,
  padding: theme.spacing.md,
  boxShadow: theme.shadows.sm,
}

const titleStyle: React.CSSProperties = {
  margin: 0,
  marginBottom: theme.spacing.sm,
  fontSize: theme.fontSizes.lg,
  fontWeight: 600,
  color: theme.colors.text,
}

export function Card({ title, children }: CardProps) {
  return (
    <section role="region" aria-label={title} style={cardStyle}>
      {title && <h3 style={titleStyle}>{title}</h3>}
      <div>{children}</div>
    </section>
  )
}
