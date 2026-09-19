import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { theme } from './theme'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'style'> {
  variant?: ButtonVariant
  children: ReactNode
}

const variantStyles: Record<ButtonVariant, React.CSSProperties> = {
  primary: {
    backgroundColor: theme.colors.primary,
    color: theme.colors.textInverse,
    border: 'none',
  },
  secondary: {
    backgroundColor: 'transparent',
    color: theme.colors.secondary,
    border: `1px solid ${theme.colors.surfaceBorder}`,
  },
  danger: {
    backgroundColor: theme.colors.danger,
    color: theme.colors.textInverse,
    border: 'none',
  },
}

const baseStyle: React.CSSProperties = {
  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
  borderRadius: theme.radii.md,
  fontSize: theme.fontSizes.md,
  fontWeight: 500,
  cursor: 'pointer',
  transition: theme.transitions.fast,
  lineHeight: 1.5,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
}

const disabledStyle: React.CSSProperties = {
  backgroundColor: theme.colors.disabled,
  color: theme.colors.disabledText,
  cursor: 'not-allowed',
  border: 'none',
}

export function Button({
  variant = 'primary',
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const style: React.CSSProperties = {
    ...baseStyle,
    ...variantStyles[variant],
    ...(disabled ? disabledStyle : {}),
  }

  return (
    <button
      style={style}
      disabled={disabled}
      data-variant={variant}
      {...rest}
    >
      {children}
    </button>
  )
}
