/**
 * MetricCard — workhorse metric display component.
 *
 * Design spec §3.2:
 * - bg-card background, border-subtle border, 12px radius, 16px 20px padding
 * - Label: 11px uppercase tracked text-secondary
 * - Value: 28-32px weight 600 text-primary
 * - Delta: 12px, teal=improvement, coral=decline
 * - Compact variant: 12px 16px padding, 24px value
 * - Status variant: 2px left border in status color, NOT colored background
 */

export type MetricStatus = 'good' | 'moderate' | 'poor' | 'neutral'

interface MetricCardProps {
  label: string
  value: string | number | null
  unit?: string
  delta?: number | null
  deltaLabel?: string
  /** When set, adds a 2px left border in the status color */
  status?: MetricStatus
  subtext?: string
  compact?: boolean
  className?: string
}

const STATUS_BORDER: Record<MetricStatus, string> = {
  good:     'var(--status-excellent)',
  moderate: 'var(--status-caution)',
  poor:     'var(--status-alert)',
  neutral:  'transparent',
}

/** Positive delta = improvement for most metrics (teal). Negative = decline (coral). */
function DeltaLine({ delta, unit }: { delta: number; unit?: string }) {
  const isPositive = delta >= 0
  const color = isPositive ? 'var(--status-excellent)' : 'var(--status-alert)'
  const arrow = isPositive ? '↑' : '↓'
  return (
    <p style={{ fontSize: 12, color, lineHeight: 1.3 }}>
      {arrow} {Math.abs(delta).toFixed(1)}{unit ?? ''}
    </p>
  )
}

export function MetricCard({
  label,
  value,
  unit,
  delta,
  deltaLabel = 'vs yesterday',
  status = 'neutral',
  subtext,
  compact = false,
  className = '',
}: MetricCardProps) {
  const borderColor = STATUS_BORDER[status]
  const padding = compact ? '12px 16px' : '16px 20px'
  const valueSize = compact ? 24 : 28

  return (
    <div
      className={className}
      style={{
        background:   'var(--bg-card)',
        border:       '0.5px solid var(--border-subtle)',
        borderLeft:   status !== 'neutral' ? `2px solid ${borderColor}` : '0.5px solid var(--border-subtle)',
        borderRadius: status !== 'neutral' ? '0 12px 12px 0' : 12,
        padding,
        display:      'flex',
        flexDirection:'column',
        gap:          6,
        transition:   'border-color 150ms ease',
      }}
      onMouseEnter={e => {
        if (status === 'neutral') e.currentTarget.style.borderColor = 'var(--border-hover)'
      }}
      onMouseLeave={e => {
        if (status === 'neutral') e.currentTarget.style.borderColor = 'var(--border-subtle)'
      }}
    >
      {/* Label */}
      <p
        style={{
          fontSize:      11,
          fontWeight:    500,
          letterSpacing: '0.07em',
          textTransform: 'uppercase',
          color:         'var(--text-secondary)',
          lineHeight:    1.2,
        }}
      >
        {label}
      </p>

      {/* Value */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        {value !== null && value !== undefined ? (
          <>
            <span
              style={{
                fontSize:           valueSize,
                fontWeight:         600,
                color:              'var(--text-primary)',
                lineHeight:         1,
                fontFamily:         "'Geist', system-ui, sans-serif",
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {value}
            </span>
            {unit && (
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{unit}</span>
            )}
          </>
        ) : (
          <span
            style={{
              fontSize:   valueSize,
              fontWeight: 600,
              color:      'var(--text-tertiary)',
              lineHeight: 1,
            }}
          >
            —
          </span>
        )}
      </div>

      {/* Delta */}
      {delta !== null && delta !== undefined && (
        <DeltaLine delta={delta} unit={unit} />
      )}
      {deltaLabel && delta !== null && delta !== undefined && (
        <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: -4 }}>
          {deltaLabel}
        </p>
      )}

      {/* Subtext */}
      {subtext && (
        <p style={{ fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.4 }}>
          {subtext}
        </p>
      )}
    </div>
  )
}
