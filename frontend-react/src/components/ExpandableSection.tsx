/**
 * ExpandableSection — shared collapsible card section.
 *
 * Renders a card with a clickable header (SectionLabel + Chevron) and
 * animated expand/collapse via CSS max-height transition.
 *
 * Usage:
 *   <ExpandableSection label="Training Load" right={<span>ACWR 0.9</span>}>
 *     <ACWRGauge ... />
 *   </ExpandableSection>
 */

import { type ReactNode, useId, useState } from 'react'

// ── Chevron ──────────────────────────────────────────────────────────────────

export function Chevron({ open, size = 14 }: { open: boolean; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{
        color:      'var(--text-tertiary)',
        transform:  open ? 'rotate(180deg)' : 'none',
        transition: 'transform 250ms ease',
        flexShrink: 0,
      }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ── SectionLabel ─────────────────────────────────────────────────────────────

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        fontSize:      11,
        textTransform: 'uppercase' as const,
        letterSpacing: '0.08em',
        color:         'var(--text-secondary)',
        fontWeight:    500,
      }}
    >
      {children}
    </span>
  )
}

// ── ExpandableSection ─────────────────────────────────────────────────────────

interface ExpandableSectionProps {
  /** Section header label text */
  label: ReactNode
  /** Optional content displayed to the right of the label in the header */
  right?: ReactNode
  /** Content shown when expanded */
  children: ReactNode
  /** Always-visible content shown below the header (before the expandable body) */
  preview?: ReactNode
  /** Control from outside — pass open + onToggle for controlled mode */
  open?: boolean
  onToggle?: () => void
  /** Default open state in uncontrolled mode */
  defaultOpen?: boolean
  /** Card padding for the header area */
  headerPadding?: string
  /** Card padding for the expanded body area */
  bodyPadding?: string
  /** Extra className on the outer card div */
  className?: string
}

export function ExpandableSection({
  label,
  right,
  children,
  preview,
  open: controlledOpen,
  onToggle: controlledToggle,
  defaultOpen = false,
  headerPadding = '14px 16px',
  bodyPadding = '12px 16px 16px',
  className = '',
}: ExpandableSectionProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen)
  const id = useId()

  const isOpen  = controlledOpen !== undefined ? controlledOpen : internalOpen
  const toggle  = controlledToggle ?? (() => setInternalOpen(v => !v))

  return (
    <div
      className={className}
      style={{
        background:   'var(--bg-card)',
        borderRadius: 12,
        border:       '0.5px solid var(--border-subtle)',
        overflow:     'hidden',
        transition:   'border-color 150ms ease',
      }}
    >
      {/* Toggle header */}
      <button
        onClick={toggle}
        aria-expanded={isOpen}
        aria-controls={id}
        style={{
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'space-between',
          width:          '100%',
          padding:        headerPadding,
          background:     'transparent',
          border:         'none',
          cursor:         'pointer',
          textAlign:      'left',
        }}
        className="focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand/50"
      >
        <SectionLabel>{label}</SectionLabel>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {right}
          <Chevron open={isOpen} />
        </div>
      </button>

      {/* Always-visible preview content */}
      {preview && (
        <div style={{ padding: '0 16px 14px' }}>
          {preview}
        </div>
      )}

      {/* Animated expandable body */}
      <div
        id={id}
        style={{
          display:        'grid',
          gridTemplateRows: isOpen ? '1fr' : '0fr',
          transition:     'grid-template-rows 250ms ease',
        }}
      >
        <div style={{ overflow: 'hidden' }}>
          <div
            style={{
              padding:   bodyPadding,
              borderTop: isOpen ? '0.5px solid var(--border-subtle)' : 'none',
            }}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
