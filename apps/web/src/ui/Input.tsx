import { useId, type InputHTMLAttributes } from 'react'
import { theme } from './theme'

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'style'> {
  label: string
  error?: string
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  marginBottom: theme.spacing.xs,
  fontSize: theme.fontSizes.sm,
  fontWeight: 500,
  color: theme.colors.text,
}

const inputBaseStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
  fontSize: theme.fontSizes.md,
  borderRadius: theme.radii.md,
  border: `1px solid ${theme.colors.surfaceBorder}`,
  outline: 'none',
  transition: theme.transitions.fast,
  lineHeight: 1.5,
  boxSizing: 'border-box',
}

const errorInputStyle: React.CSSProperties = {
  borderColor: theme.colors.error,
}

const errorTextStyle: React.CSSProperties = {
  color: theme.colors.error,
  fontSize: theme.fontSizes.sm,
  marginTop: theme.spacing.xs,
}

export function Input({ label, error, id: providedId, ...rest }: InputProps) {
  const generatedId = useId()
  const inputId = providedId ?? generatedId
  const errorId = error ? `${inputId}-error` : undefined

  return (
    <div>
      <label htmlFor={inputId} style={labelStyle}>
        {label}
      </label>
      <input
        id={inputId}
        style={{ ...inputBaseStyle, ...(error ? errorInputStyle : {}) }}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={errorId}
        {...rest}
      />
      {error && (
        <div id={errorId} style={errorTextStyle} role="alert">
          {error}
        </div>
      )}
    </div>
  )
}
