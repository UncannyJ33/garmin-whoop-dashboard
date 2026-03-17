/**
 * LimitingFactorCard — compact callout showing one limiting factor below the readiness hero.
 *
 * Design spec §3.7:
 * - Background: status color at 6% opacity
 * - Left border: 2px, status color at 35% opacity
 * - Border radius: 0 6px 6px 0 (flat left edge)
 * - Padding: 7px 12px
 * - Factor name in status color, context in text-secondary
 */

type Severity = 'alert' | 'caution'

interface LimitingFactorCardProps {
  factorName: string
  context: string
  severity?: Severity
  className?: string
}

const SEVERITY_STYLES: Record<Severity, { bg: string; border: string; nameColor: string }> = {
  alert: {
    bg:        'rgba(216, 90, 48, 0.06)',
    border:    'rgba(216, 90, 48, 0.35)',
    nameColor: 'var(--status-alert)',
  },
  caution: {
    bg:        'rgba(186, 117, 23, 0.06)',
    border:    'rgba(186, 117, 23, 0.35)',
    nameColor: 'var(--status-caution)',
  },
}

export function LimitingFactorCard({
  factorName,
  context,
  severity = 'alert',
  className = '',
}: LimitingFactorCardProps) {
  const s = SEVERITY_STYLES[severity]

  return (
    <div
      className={`flex items-baseline gap-2 ${className}`}
      style={{
        background:   s.bg,
        borderLeft:   `2px solid ${s.border}`,
        borderRadius: '0 6px 6px 0',
        padding:      '7px 12px',
      }}
    >
      <span
        className="text-xs font-medium flex-shrink-0"
        style={{ color: s.nameColor }}
      >
        {factorName}
      </span>
      <span
        className="text-xs"
        style={{ color: 'var(--text-secondary)' }}
      >
        {context}
      </span>
    </div>
  )
}
