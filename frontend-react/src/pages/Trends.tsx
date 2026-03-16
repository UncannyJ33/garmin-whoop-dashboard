/**
 * Trends page — weekly summary, metric explorer, anomaly log, metric correlations
 */
import { useMemo, useState } from 'react'
import { useAnomalies, useMetricTrend, useWeeklySummary } from '../hooks/useApi'
import { WeekComparison } from '../components/WeekComparison'
import { TrendChart } from '../components/TrendChart'
import type { TrendDataPoint } from '../components/TrendChart'
import { MetricCardSkeleton } from '../components/LoadingState'
import { ErrorState } from '../components/ErrorState'

// ── helpers ────────────────────────────────────────────────────────────────────

function toISO(d: Date): string {
  return d.toLocaleDateString('en-CA')
}

function subDays(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return toISO(d)
}

function fmtDate(iso: string): string {
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function dateShift(iso: string, days: number): string {
  const d = new Date(iso + 'T12:00:00')
  d.setDate(d.getDate() + days)
  return toISO(d)
}

/** Compute Pearson r on parallel arrays, skipping null pairs. Requires ≥7 pairs. */
function pearson(
  xs: (number | null)[],
  ys: (number | null)[],
): { r: number | null; n: number } {
  const pairs: [number, number][] = []
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i], y = ys[i]
    if (x !== null && y !== null) pairs.push([x, y])
  }
  if (pairs.length < 7) return { r: null, n: pairs.length }
  const n = pairs.length
  const mx = pairs.reduce((s, [x]) => s + x, 0) / n
  const my = pairs.reduce((s, [, y]) => s + y, 0) / n
  const num = pairs.reduce((s, [x, y]) => s + (x - mx) * (y - my), 0)
  const dx = Math.sqrt(pairs.reduce((s, [x]) => s + (x - mx) ** 2, 0))
  const dy = Math.sqrt(pairs.reduce((s, [, y]) => s + (y - my) ** 2, 0))
  return { r: dx === 0 || dy === 0 ? null : num / (dx * dy), n }
}

/** Align series A against series B by date, returning parallel value arrays. */
function alignByDate(
  datesA: string[], valuesA: (number | null)[],
  datesB: string[], valuesB: (number | null)[],
): { xs: (number | null)[]; ys: (number | null)[] } {
  const mapB = new Map(datesB.map((d, i) => [d, valuesB[i]]))
  return { xs: valuesA, ys: datesA.map(d => mapB.get(d) ?? null) }
}

/** Align A against B shifted by `shiftDays` forward (positive = next-day B). */
function alignShifted(
  datesA: string[], valuesA: (number | null)[],
  datesB: string[], valuesB: (number | null)[],
  shiftDays: number,
): { xs: (number | null)[]; ys: (number | null)[] } {
  const mapB = new Map(datesB.map((d, i) => [d, valuesB[i]]))
  return { xs: valuesA, ys: datesA.map(d => mapB.get(dateShift(d, shiftDays)) ?? null) }
}

// ── metric config ──────────────────────────────────────────────────────────────

interface MetricConfig {
  key: string
  label: string
  unit: string
  color: string
  lowerIsBetter?: boolean
  formatValue?: (v: number) => string
}

const METRICS: MetricConfig[] = [
  { key: 'recovery',        label: 'Recovery',       unit: '%',    color: '#34d399' },
  { key: 'hrv',             label: 'HRV',            unit: ' ms',  color: '#818cf8' },
  { key: 'resting_hr',     label: 'Resting HR',     unit: ' bpm', color: '#f87171', lowerIsBetter: true },
  { key: 'strain',         label: 'Strain',         unit: '',     color: '#fb923c' },
  { key: 'body_battery',   label: 'Body Battery',   unit: '',     color: '#facc15' },
  { key: 'sleep_duration', label: 'Sleep Duration', unit: 'h',    color: '#60a5fa', formatValue: v => `${v.toFixed(1)}h` },
  { key: 'deep_sleep',     label: 'Deep Sleep',     unit: 'h',    color: '#4f46e5', formatValue: v => `${v.toFixed(1)}h` },
  { key: 'readiness',      label: 'Readiness',      unit: '',     color: '#2dd4bf' },
  { key: 'training_load',  label: 'Training Load',  unit: '',     color: '#e879f9' },
]

const METRIC_BY_KEY = new Map(METRICS.map(m => [m.key, m]))

// Backend _METRIC_LABELS values → chart color for anomaly table dots
const ANOMALY_COLORS: Record<string, string> = {
  'Recovery Score': '#34d399',
  'HRV':            '#818cf8',
  'Resting HR':     '#f87171',
  'Strain (Daily)': '#fb923c',
  'Body Battery':   '#facc15',
  'Sleep Duration': '#60a5fa',
  'Deep Sleep':     '#4f46e5',
}

// Metrics where higher = worse (a high anomaly is bad, a low anomaly is good)
const LOWER_IS_BETTER_ANOMALY = new Set(['Resting HR'])

// ── severity classification ────────────────────────────────────────────────────

function severityLabel(s: number): { label: string; color: string } {
  if (s >= 3.5) return { label: 'Significant', color: 'text-poor' }
  if (s >= 2.5) return { label: 'Moderate',    color: 'text-moderate' }
  return            { label: 'Mild',          color: 'text-slate-400' }
}

// ── sub-components ─────────────────────────────────────────────────────────────

function DayButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface-overlay text-slate-500 hover:text-slate-400'
      }`}
    >
      {n}d
    </button>
  )
}

function TrendBadge({ direction, metricLabel }: { direction: string; metricLabel: string }) {
  if (!direction || direction === 'insufficient_data') {
    return (
      <p className="text-2xs text-slate-500">Not enough data to determine trend direction.</p>
    )
  }
  if (direction === 'stable') {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold bg-moderate/10 border-moderate/30 text-moderate">
        <span>→</span>
        <span>{metricLabel} is stable</span>
      </div>
    )
  }
  const improving = direction === 'improving'
  return (
    <div className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${
      improving ? 'bg-good/10 border-good/30 text-good' : 'bg-poor/10 border-poor/30 text-poor'
    }`}>
      <span>{improving ? '↑' : '↓'}</span>
      <span>{metricLabel} is {direction} over the past 7 days</span>
    </div>
  )
}

interface CorrResult { r: number | null; n: number }

function CorrRow({ label, result }: { label: string; result: CorrResult | null }) {
  return (
    <tr className="border-b border-surface-border last:border-0">
      <td className="py-2.5 pr-6 text-xs font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
        {label}
      </td>
      <td className="py-2.5">
        {!result ? (
          <span className="text-xs text-slate-400">—</span>
        ) : result.r === null ? (
          <span className="text-xs text-slate-400">
            Need {Math.max(0, 7 - result.n)} more days of paired data
          </span>
        ) : (() => {
          const abs = Math.abs(result.r)
          const isPos = result.r > 0
          const color = abs >= 0.5 ? (isPos ? 'text-good' : 'text-poor')
            : abs >= 0.3 ? 'text-moderate'
            : 'text-slate-400'
          const strength = abs >= 0.5 ? (isPos ? 'Strong positive' : 'Strong negative')
            : abs >= 0.3 ? (isPos ? 'Moderate positive' : 'Moderate negative')
            : 'Weak'
          return (
            <div className="flex items-center gap-2">
              <span className={`text-xs font-semibold ${color}`}>{strength}</span>
              <span className={`font-mono text-xs ${color}`}>{result.r.toFixed(2)}</span>
              <span className="text-2xs text-slate-500 font-mono">n={result.n}</span>
            </div>
          )
        })()}
      </td>
    </tr>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export function Trends() {
  const [selectedMetric, setSelectedMetric] = useState('recovery')
  const [explorerDays, setExplorerDays] = useState(60)

  const today   = toISO(new Date())
  const exStart = subDays(explorerDays)
  const exEnd   = today

  const summaryQ   = useWeeklySummary(today)
  const trendQ     = useMetricTrend(selectedMetric, exStart, exEnd)
  const anomaliesQ = useAnomalies(exStart, exEnd)

  // Correlation source metrics — TanStack Query deduplicates if explorer uses same key
  const hrvQ      = useMetricTrend('hrv',           exStart, exEnd)
  const recoveryQ = useMetricTrend('recovery',       exStart, exEnd)
  const strainQ   = useMetricTrend('strain',         exStart, exEnd)
  const batteryQ  = useMetricTrend('body_battery',   exStart, exEnd)
  const sleepQ    = useMetricTrend('sleep_duration', exStart, exEnd)

  const selectedCfg = METRIC_BY_KEY.get(selectedMetric) ?? METRICS[0]

  // Map MetricTrend → TrendDataPoint[]
  const trendData = useMemo((): TrendDataPoint[] => {
    const t = trendQ.data
    if (!t) return []
    const anomalyDates = new Set(t.anomalies.map(a => a.date))
    return t.dates.map((date, i) => ({
      date,
      value:    t.values[i],
      avg7d:    t.rolling_avg_7d[i],
      avg30d:   t.rolling_avg_30d[i],
      isAnomaly: anomalyDates.has(date),
    }))
  }, [trendQ.data])

  // Section 1: weekly comparison rows
  const weekMetrics = useMemo(() => {
    const s = summaryQ.data
    if (!s) return []
    const c = s.comparison ?? {}
    return [
      {
        label: 'Avg Readiness',
        value: s.avg_readiness != null ? String(Math.round(s.avg_readiness)) : null,
        pctChange: c['avg_readiness'] ?? null,
      },
      {
        label: 'Avg Recovery',
        value: s.avg_recovery != null ? `${Math.round(s.avg_recovery)}%` : null,
        pctChange: c['avg_recovery'] ?? null,
      },
      {
        label: 'Avg HRV',
        value: s.avg_hrv != null ? `${Math.round(s.avg_hrv)} ms` : null,
        pctChange: c['avg_hrv'] ?? null,
      },
      {
        label: 'Total Strain',
        value: s.total_strain != null ? s.total_strain.toFixed(1) : null,
        pctChange: c['total_strain'] ?? null,
      },
      {
        label: 'Avg Sleep',
        value: s.avg_sleep_duration != null
          ? `${(s.avg_sleep_duration / 60).toFixed(1)}h`
          : null,
        pctChange: c['avg_sleep_duration'] ?? null,
      },
      {
        label: 'Workouts',
        value: String(s.workout_count),
        pctChange: c['workout_count'] ?? null,
      },
    ]
  }, [summaryQ.data])

  // Section 4: Pearson correlations computed client-side
  const correlations = useMemo(() => {
    const hrv = hrvQ.data
    const rec = recoveryQ.data
    const str = strainQ.data
    const bat = batteryQ.data
    const slp = sleepQ.data

    const hrvRecovery = hrv && rec
      ? (() => {
          const { xs, ys } = alignByDate(hrv.dates, hrv.values, rec.dates, rec.values)
          return pearson(xs, ys)
        })()
      : null

    const strainNextRecovery = str && rec
      ? (() => {
          const { xs, ys } = alignShifted(str.dates, str.values, rec.dates, rec.values, 1)
          return pearson(xs, ys)
        })()
      : null

    const sleepBattery = slp && bat
      ? (() => {
          const { xs, ys } = alignByDate(slp.dates, slp.values, bat.dates, bat.values)
          return pearson(xs, ys)
        })()
      : null

    return { hrvRecovery, strainNextRecovery, sleepBattery }
  }, [hrvQ.data, recoveryQ.data, strainQ.data, batteryQ.data, sleepQ.data])

  const corrLoading = hrvQ.isLoading || recoveryQ.isLoading || strainQ.isLoading
    || batteryQ.isLoading || sleepQ.isLoading

  const anyCorrData = !corrLoading && (
    correlations.hrvRecovery?.r !== null ||
    correlations.strainNextRecovery?.r !== null ||
    correlations.sleepBattery?.r !== null
  )

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Trends</h1>

      {/* ── SECTION 1: Weekly Summary ────────────────────────────────────────── */}
      {summaryQ.isLoading ? (
        <div className="card">
          <div className="skeleton h-4 w-32 mb-3 rounded" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Array.from({ length: 6 }).map((_, i) => <MetricCardSkeleton key={i} />)}
          </div>
        </div>
      ) : summaryQ.isError ? (
        <ErrorState
          message="Could not load weekly summary."
          onRetry={() => void summaryQ.refetch()}
        />
      ) : summaryQ.data ? (
        <WeekComparison metrics={weekMetrics} />
      ) : null}

      {/* ── SECTION 2: Metric Explorer ───────────────────────────────────────── */}
      <div className="card space-y-3">

        {/* Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 flex-1">
            Metric Explorer
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              value={selectedMetric}
              onChange={e => setSelectedMetric(e.target.value)}
              className="text-xs rounded-lg border border-surface-border bg-surface-overlay px-2.5 py-1.5 text-slate-700 dark:text-slate-200 focus:outline-none cursor-pointer"
            >
              {METRICS.map(m => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
            <div className="flex gap-1">
              {[30, 60, 90, 180].map(n => (
                <DayButton key={n} n={n} active={explorerDays === n} onClick={() => setExplorerDays(n)} />
              ))}
            </div>
          </div>
        </div>

        {/* Chart */}
        {trendQ.isLoading ? (
          <div className="skeleton rounded-xl" style={{ height: 240 }} />
        ) : trendQ.isError ? (
          <div className="flex items-center justify-center rounded-xl bg-surface-overlay text-sm text-slate-400" style={{ height: 240 }}>
            Could not load metric data.
          </div>
        ) : (
          <TrendChart
            data={trendData}
            metricName={selectedCfg.label}
            unit={selectedCfg.unit}
            color={selectedCfg.color}
            formatValue={selectedCfg.formatValue}
            height={240}
          />
        )}

        {/* Legend + trend badge */}
        {!trendQ.isLoading && !trendQ.isError && (
          <>
            <div className="flex flex-wrap gap-3">
              {[
                { label: selectedCfg.label, color: selectedCfg.color },
                { label: '7d avg',          color: '#fb923c' },
                { label: '30d avg',         color: '#94a3b8' },
                { label: 'Anomaly',         color: '#ef4444' },
              ].map(({ label, color }) => (
                <span key={label} className="flex items-center gap-1.5 text-2xs text-slate-500">
                  <span className="inline-block h-2 w-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                  {label}
                </span>
              ))}
            </div>
            {trendQ.data && (
              <TrendBadge direction={trendQ.data.trend_direction} metricLabel={selectedCfg.label} />
            )}
          </>
        )}
      </div>

      {/* ── SECTION 3: Anomaly Log ───────────────────────────────────────────── */}
      <div className="card space-y-3">
        <div>
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Anomaly Log</p>
          <p className="text-2xs text-slate-500 mt-0.5">
            Days that deviated significantly (≥2σ) from your rolling baseline
          </p>
        </div>

        {anomaliesQ.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-9 rounded-lg" />
            ))}
          </div>
        ) : anomaliesQ.isError ? (
          <p className="text-sm text-slate-400">Could not load anomaly data.</p>
        ) : !anomaliesQ.data?.length ? (
          <p className="text-sm text-slate-400">
            No anomalies detected in the last {explorerDays} days — your metrics are consistent.
          </p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left border-b border-surface-border">
                <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Date</th>
                <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Metric</th>
                <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Value</th>
                <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap hidden sm:table-cell">Direction</th>
                <th className="pb-2 text-slate-500 font-medium whitespace-nowrap">Severity</th>
              </tr>
            </thead>
            <tbody>
              {anomaliesQ.data.map((a, i) => {
                const { label: sLabel, color: sColor } = severityLabel(a.severity)
                const dotColor = ANOMALY_COLORS[a.metric] ?? '#94a3b8'
                const isLowerBetter = LOWER_IS_BETTER_ANOMALY.has(a.metric)
                const isGoodDirection = isLowerBetter ? a.direction === 'low' : a.direction === 'high'
                const dirArrow = a.direction === 'high' ? '↑' : '↓'
                return (
                  <tr key={i} className="border-b border-surface-border last:border-0 text-slate-600 dark:text-slate-400">
                    <td className="py-2.5 pr-4 font-mono text-slate-500 whitespace-nowrap">
                      {fmtDate(a.date)}
                    </td>
                    <td className="py-2.5 pr-4 whitespace-nowrap">
                      <span className="flex items-center gap-1.5">
                        <span
                          className="h-1.5 w-1.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: dotColor }}
                        />
                        {a.metric}
                      </span>
                    </td>
                    <td className={`py-2.5 pr-4 font-mono text-right ${isGoodDirection ? 'text-good' : 'text-poor'}`}>
                      <span className="sm:hidden mr-0.5">{dirArrow}</span>
                      {a.value.toFixed(1)}
                    </td>
                    <td className={`py-2.5 pr-4 font-medium hidden sm:table-cell ${isGoodDirection ? 'text-good' : 'text-poor'}`}>
                      {a.direction === 'high' ? '↑ High' : '↓ Low'}
                    </td>
                    <td className={`py-2.5 font-medium ${sColor}`}>{sLabel}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── SECTION 4: Metric Correlations (only if ≥7 paired days available) ── */}
      {(corrLoading || anyCorrData) && (
        <div className="card space-y-3">
          <div>
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Metric Correlations
            </p>
            <p className="text-2xs text-slate-500 mt-0.5">
              Pearson r over the {explorerDays}-day window — how strongly these metrics move together
            </p>
          </div>

          {corrLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="skeleton h-10 rounded-lg" />
              ))}
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-surface-border">
                  <th className="pb-2 text-left text-xs font-medium text-slate-500">Metric Pair</th>
                  <th className="pb-2 text-left text-xs font-medium text-slate-500">Correlation</th>
                </tr>
              </thead>
              <tbody>
                <CorrRow label="HRV ↔ Recovery"               result={correlations.hrvRecovery} />
                <CorrRow label="Strain ↔ Next-Day Recovery"   result={correlations.strainNextRecovery} />
                <CorrRow label="Sleep Duration ↔ Body Battery" result={correlations.sleepBattery} />
              </tbody>
            </table>
          )}
        </div>
      )}

    </div>
  )
}
