interface MetricCardProps {
  label: string
  value: string | number | null
  unit?: string
  delta?: number | null        // e.g. +5.2 or -3.1
  deltaLabel?: string          // e.g. "vs yesterday"
  status?: 'good' | 'moderate' | 'poor' | 'neutral'
  subtext?: string             // secondary line below value
  className?: string
}

const STATUS_COLORS = {
  good:     { value: 'text-good',     delta: 'text-good',     badge: 'bg-good/10 border-good/30' },
  moderate: { value: 'text-moderate', delta: 'text-moderate', badge: 'bg-moderate/10 border-moderate/30' },
  poor:     { value: 'text-poor',     delta: 'text-poor',     badge: 'bg-poor/10 border-poor/30' },
  neutral:  { value: 'text-slate-800 dark:text-slate-100',delta: 'text-slate-400',badge: 'bg-surface-overlay border-surface-border' },
}

function deltaArrow(delta: number): string {
  return delta > 0 ? '↑' : '↓'
}

export function MetricCard({
  label,
  value,
  unit,
  delta,
  deltaLabel = 'vs yesterday',
  status = 'neutral',
  subtext,
  className = '',
}: MetricCardProps) {
  const colors = STATUS_COLORS[status]

  return (
    <div className={`card-sm flex flex-col gap-1.5 ${colors.badge} border ${className}`}>
      <p className="metric-label">{label}</p>

      <div className="flex items-baseline gap-1">
        {value !== null && value !== undefined ? (
          <>
            <span className={`metric-value ${colors.value}`}>{value}</span>
            {unit && <span className="text-sm text-slate-400">{unit}</span>}
          </>
        ) : (
          <span className="metric-value text-slate-400">—</span>
        )}
      </div>

      {delta !== null && delta !== undefined && (
        <p className={`text-xs font-medium ${colors.delta}`}>
          {deltaArrow(delta)} {Math.abs(delta).toFixed(1)}{unit ?? ''} {deltaLabel}
        </p>
      )}

      {subtext && <p className="text-2xs text-slate-500 leading-tight">{subtext}</p>}
    </div>
  )
}
