/**
 * Design tokens for Vision App Creator UI.
 *
 * These tokens define the visual vocabulary used by all UI primitives
 * and feature components. Feature agents consume these unchanged (per U01 card).
 */

export const theme = {
  colors: {
    primary: '#2563eb',        // Blue-600
    primaryHover: '#1d4ed8',   // Blue-700
    secondary: '#6b7280',      // Gray-500
    secondaryHover: '#4b5563', // Gray-600
    danger: '#dc2626',         // Red-600
    dangerHover: '#b91c1c',    // Red-700
    error: '#dc2626',          // Red-600 (alias for semantic use)
    success: '#16a34a',        // Green-600
    warning: '#d97706',        // Amber-600
    background: '#f9fafb',     // Gray-50
    surface: '#ffffff',        // White
    surfaceBorder: '#e5e7eb',  // Gray-200
    text: '#111827',           // Gray-900
    textSecondary: '#6b7280',  // Gray-500
    textInverse: '#ffffff',    // White
    disabled: '#d1d5db',       // Gray-300
    disabledText: '#9ca3af',   // Gray-400
  },
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
    xxl: '48px',
  },
  fontSizes: {
    xs: '12px',
    sm: '14px',
    md: '16px',
    lg: '20px',
    xl: '24px',
    xxl: '32px',
  },
  radii: {
    sm: '4px',
    md: '8px',
    lg: '12px',
    full: '9999px',
  },
  shadows: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px rgba(0, 0, 0, 0.07)',
    lg: '0 10px 15px rgba(0, 0, 0, 0.1)',
  },
  transitions: {
    fast: '150ms ease',
    normal: '200ms ease',
  },
} as const

export type Theme = typeof theme
