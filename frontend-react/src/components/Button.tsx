/**
 * Button — unified button component with variants, sizes, and states.
 *
 * Variants: primary (brand fill) | secondary (outline) | ghost (no border)
 * Sizes:    sm | md | lg
 * States:   loading (spinner + disabled) | disabled
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize    = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:  ButtonVariant
  size?:     ButtonSize
  loading?:  boolean
  children:  ReactNode
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:   'bg-brand text-white border-transparent hover:bg-brand/90',
  secondary: 'bg-transparent text-[var(--text-primary)] border-[var(--border-hover)] hover:border-[var(--border-hover)] hover:bg-white/5',
  ghost:     'bg-transparent text-[var(--text-secondary)] border-transparent hover:text-[var(--text-primary)] hover:bg-white/5',
  danger:    'bg-transparent text-[var(--status-alert)] border-[var(--status-alert)]/30 hover:bg-[var(--status-alert)]/10',
}

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs rounded-lg gap-1.5',
  md: 'px-4 py-2 text-sm rounded-xl gap-2',
  lg: 'px-5 py-2.5 text-sm rounded-xl gap-2',
}

function Spinner() {
  return (
    <svg
      className="animate-spin"
      width="14" height="14"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  )
}

export function Button({
  variant  = 'secondary',
  size     = 'md',
  loading  = false,
  disabled,
  children,
  className = '',
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading

  return (
    <button
      disabled={isDisabled}
      className={[
        'inline-flex items-center justify-center font-semibold border',
        'transition-colors duration-150',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50',
        'disabled:opacity-40 disabled:cursor-not-allowed',
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      ].join(' ')}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  )
}
