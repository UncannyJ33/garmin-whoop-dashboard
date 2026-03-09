interface MetricRow {
  label: string
  value: string | null    // formatted current week value
  pctChange: number | null  // e.g. +5.2 or -3.1
  lowerIsBetter?: boolean
}

interface WeekComparisonProps {
  metrics: MetricRow[]
  weekLabel?: string
  prevWeekLabel?: string
}

function ChangeIndicator({ pct, lowerIsBetter }: { pct: number; lowerIsBetter?: boolean }) {
  const isGood = lowerIsBetter ? pct < 0 : pct > 0
  const color = Math.abs(pct) < 1 ? 'text-slate-400' : isGood ? 'text-good' : 'text-poor'
  const arrow = pct > 0 ? '↑' : '↓'

  return (
    <span className={`font-mono text-xs font-semibold ${color}`}>
      {arrow} {Math.abs(pct).toFixed(1)}%
    </span>
  )
}

export function WeekComparison({
  metrics,
  weekLabel = 'This week',
  prevWeekLabel = 'vs last week',
}: WeekComparisonProps) {
  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-3">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{weekLabel}</p>
        <p className="text-2xs text-slate-500">{prevWeekLabel}</p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {metrics.map(({ label, value, pctChange, lowerIsBetter }) => (
          <div key={label} className="bg-surface-overlay rounded-xl p-3 space-y-1">
            <p className="metric-label">{label}</p>
            <p className="font-mono text-lg font-semibold text-slate-800 dark:text-slate-100 leading-none">
              {value ?? '—'}
            </p>
            {pctChange !== null && pctChange !== undefined ? (
              <ChangeIndicator pct={pctChange} lowerIsBetter={lowerIsBetter} />
            ) : (
              <span className="text-xs text-slate-400">no prior data</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
