/**
 * Sleep Analysis page — last night hero, trends, stage distribution, consistency, correlations
 */
import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  useSleepConsistency,
  useSleepCorrelations,
  useSleepInsights,
} from '../hooks/useApi'
import { useDateRangeContext } from '../context/DateRangeContext'
import { MetricCardSkeleton } from '../components/LoadingState'
import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { SleepStageBar } from '../components/SleepStageBar'
import type { SleepInsight } from '../types/api'

// ── helpers ────────────────────────────────────────────────────────────────────

/**
 * UTC decimal hour (e.g. 22.75) → local time string (e.g. "6:45 PM" in ET).
 * avg_bedtime_hour / avg_wake_hour from the API are computed from UTC timestamps.
 */
function fmtHour(utcHour: number | null): string {
  if (utcHour === null) return '—'
  const norm = ((utcHour % 24) + 24) % 24
  // Build a Date at that UTC hour so JS can apply the local timezone offset
  const d = new Date()
  d.setUTCHours(Math.floor(norm), Math.round((norm % 1) * 60), 0, 0)
  const hh = d.getHours()
  const mm = d.getMinutes()
  const period = hh >= 12 ? 'PM' : 'AM'
  const h12 = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh
  return `${h12}:${mm.toString().padStart(2, '0')} ${period}`
}

function fmtHours(m: number | null): string {
  if (m === null) return '—'
  const h = Math.floor(m / 60)
  const min = Math.round(m % 60)
  return `${h}h ${min}m`
}

function fmtDate(iso: string): string {
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function rolling7d(mins: (number | null)[]): (number | null)[] {
  return mins.map((_, i) => {
    const w = mins.slice(Math.max(0, i - 6), i + 1).filter((v): v is number => v !== null)
    return w.length ? w.reduce((a, b) => a + b, 0) / w.length : null
  })
}

function avgOf(nums: number[]): number | null {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null
}

function perfStatus(v: number | null): 'good' | 'moderate' | 'poor' | 'neutral' {
  if (v === null) return 'neutral'
  if (v >= 85) return 'good'
  if (v >= 70) return 'moderate'
  return 'poor'
}

// ── sub-components ────────────────────────────────────────────────────────────

function DayButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
      }`}
    >
      {n}d
    </button>
  )
}

interface TooltipEntry { name: string; value: number | null; color: string }

function TrendsTooltip({
  active, payload, label,
}: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="text-slate-400 font-medium">{label ? fmtDate(label) : ''}</p>
      {payload.map(e =>
        e.value !== null && e.value !== undefined ? (
          <p key={e.name} style={{ color: e.color }} className="font-mono">
            {e.name}: {e.value.toFixed(1)}h
          </p>
        ) : null,
      )}
    </div>
  )
}

function StageTooltip({
  active, payload, label,
}: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, e) => s + (e.value ?? 0), 0)
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="text-slate-400 font-medium">{label ? fmtDate(label) : ''}</p>
      {[...payload].reverse().map(e =>
        (e.value ?? 0) > 0 ? (
          <p key={e.name} style={{ color: e.color }} className="font-mono">
            {e.name}: {(e.value ?? 0).toFixed(1)}h
            {total > 0 ? ` (${(((e.value ?? 0) / total) * 100).toFixed(0)}%)` : ''}
          </p>
        ) : null,
      )}
      <p className="text-slate-300 font-mono border-t border-surface-border pt-1">
        Total: {total.toFixed(1)}h
      </p>
    </div>
  )
}

function CorrelationCard({
  title,
  children,
  nSamples,
  minSamples = 7,
}: {
  title: string
  children: ReactNode
  nSamples: number
  minSamples?: number
}) {
  const insufficient = nSamples < minSamples
  return (
    <div className="card-sm space-y-2">
      <p className="text-xs font-semibold text-slate-600 dark:text-slate-300">{title}</p>
      {insufficient ? (
        <p className="text-sm text-slate-400">
          Need {minSamples - nSamples} more day{minSamples - nSamples !== 1 ? 's' : ''} to reveal this pattern
        </p>
      ) : (
        children
      )}
    </div>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export function Sleep() {
  const { days, setDays, start, end } = useDateRangeContext()
  const [showDeep, setShowDeep] = useState(false)

  const insightsQ    = useSleepInsights(start, end)
  const consistencyQ = useSleepConsistency(days)
  const correlationsQ = useSleepCorrelations(days)

  const insights = insightsQ.data ?? []

  const lastNight = useMemo(
    () => (insights.length > 0 ? insights[insights.length - 1] : null),
    [insights],
  )

  // Section 2: bar + rolling avg + deep overlay
  const trendsData = useMemo(() => {
    const totalMins = insights.map(d => d.total_sleep_minutes)
    const avg7dMins = rolling7d(totalMins)
    return insights.map((d, i) => ({
      date: d.date,
      total: d.total_sleep_minutes !== null ? +(d.total_sleep_minutes / 60).toFixed(2) : null,
      avg7d: avg7dMins[i] !== null ? +(avg7dMins[i]! / 60).toFixed(2) : null,
      deep:  d.deep_minutes !== null ? +(d.deep_minutes / 60).toFixed(2) : null,
      isAnomaly:
        d.total_sleep_minutes !== null &&
        avg7dMins[i] !== null &&
        (avg7dMins[i]! - d.total_sleep_minutes) / 60 > 1.5,
    }))
  }, [insights])

  // Section 3: stacked area — raw hours per stage
  const stageData = useMemo(
    () =>
      insights.map(d => ({
        date:  d.date,
        Deep:  d.deep_minutes  !== null ? +(d.deep_minutes  / 60).toFixed(2) : 0,
        REM:   d.rem_minutes   !== null ? +(d.rem_minutes   / 60).toFixed(2) : 0,
        Light: d.light_minutes !== null ? +(d.light_minutes / 60).toFixed(2) : 0,
        Awake: d.awake_minutes !== null ? +(d.awake_minutes / 60).toFixed(2) : 0,
      })),
    [insights],
  )

  // Section 5: derived stats for correlation cards
  const corrStats = useMemo(() => {
    const nonNull = <T,>(v: T | null | undefined): v is T => v !== null && v !== undefined

    const highStrain   = insights.filter(d => (d.previous_day_strain ?? 0) > 14)
    const normalStrain = insights.filter(d => nonNull(d.previous_day_strain) && d.previous_day_strain! <= 14)

    const hsSleep   = avgOf(highStrain.map(d => d.total_sleep_minutes).filter(nonNull))
    const normSleep = avgOf(normalStrain.map(d => d.total_sleep_minutes).filter(nonNull))

    const goodSleepNights  = insights.filter(d => (d.total_sleep_minutes ?? 0) >= 450)
    const shortSleepNights = insights.filter(d => nonNull(d.total_sleep_minutes) && d.total_sleep_minutes! < 450)
    const goodRecovery  = avgOf(goodSleepNights.map(d => d.next_day_recovery_score).filter(nonNull))
    const shortRecovery = avgOf(shortSleepNights.map(d => d.next_day_recovery_score).filter(nonNull))

    const toDeepPct = (d: SleepInsight) =>
      d.total_sleep_minutes && nonNull(d.deep_minutes)
        ? (d.deep_minutes! / d.total_sleep_minutes) * 100
        : null
    const hsDeepPct   = avgOf(highStrain.map(toDeepPct).filter(nonNull))
    const normDeepPct = avgOf(normalStrain.map(toDeepPct).filter(nonNull))

    return {
      hsSleep, normSleep, hsCount: highStrain.length,
      goodRecovery, shortRecovery,
      goodCount: goodSleepNights.length, shortCount: shortSleepNights.length,
      hsDeepPct, normDeepPct,
    }
  }, [insights])

  const cons = consistencyQ.data

  // Time in bed = all stages (includes awake periods)
  const timeInBedMinutes = useMemo(() => {
    if (!lastNight) return null
    const total = (lastNight.deep_minutes ?? 0)
      + (lastNight.light_minutes ?? 0)
      + (lastNight.rem_minutes ?? 0)
      + (lastNight.awake_minutes ?? 0)
    return total > 0 ? total : null
  }, [lastNight])

  if (insightsQ.isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Sleep</h1>
        <ErrorState
          message="Could not load sleep data. Make sure the backend is running on port 8000."
          onRetry={() => void insightsQ.refetch()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header + date range ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Sleep</h1>
        <div className="flex gap-1.5">
          {[7, 14, 30, 60].map(n => (
            <DayButton key={n} n={n} active={days === n} onClick={() => setDays(n)} />
          ))}
        </div>
      </div>

      {/* ── SECTION 1: Last Night ────────────────────────────────────────────── */}
      <div className="card space-y-4">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Last Night</p>

        {insightsQ.isLoading ? (
          <div className="space-y-3">
            <div className="skeleton h-16 w-36 rounded-xl" />
            <div className="skeleton h-6 w-full rounded-full" />
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
            </div>
          </div>
        ) : !lastNight ? (
          <p className="text-sm text-slate-400">No sleep data in this period.</p>
        ) : (
          <>
            {/* Total sleep — hero number */}
            <div className="flex items-baseline gap-2">
              <span
                className="font-bold tabular-nums leading-none text-slate-800 dark:text-slate-100"
                style={{ fontSize: 'clamp(52px, 12vw, 80px)' }}
              >
                {lastNight.total_sleep_minutes !== null
                  ? (lastNight.total_sleep_minutes / 60).toFixed(1)
                  : '—'}
              </span>
              <span className="text-xl text-slate-400">h</span>
              <span className="text-sm text-slate-400 ml-1">{fmtDate(lastNight.date)}</span>
            </div>

            {/* Stage bar */}
            <SleepStageBar
              deepMinutes={lastNight.deep_minutes}
              lightMinutes={lastNight.light_minutes}
              remMinutes={lastNight.rem_minutes}
              awakeMinutes={lastNight.awake_minutes}
            />

            {/* Metric grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <MetricCard
                label="Sleep"
                value={lastNight.total_sleep_minutes !== null ? fmtHours(lastNight.total_sleep_minutes) : null}
                status="neutral"
              />
              <MetricCard
                label="Time in Bed"
                value={timeInBedMinutes !== null ? fmtHours(timeInBedMinutes) : null}
                status="neutral"
              />
              <MetricCard
                label="Sleep Performance"
                value={lastNight.sleep_performance !== null ? Math.round(lastNight.sleep_performance) : null}
                unit="%"
                status={perfStatus(lastNight.sleep_performance)}
              />
              <MetricCard
                label="Sleep Efficiency"
                value={lastNight.sleep_efficiency !== null ? Math.round(lastNight.sleep_efficiency) : null}
                unit="%"
                status={perfStatus(lastNight.sleep_efficiency)}
              />
              <MetricCard
                label="Deep Sleep"
                value={lastNight.deep_minutes !== null ? fmtHours(lastNight.deep_minutes) : null}
                status="neutral"
              />
              <MetricCard
                label="REM Sleep"
                value={lastNight.rem_minutes !== null ? fmtHours(lastNight.rem_minutes) : null}
                status="neutral"
              />
            </div>

            {/* Sleep debt banner */}
            {lastNight.sleep_debt_estimate !== null && (
              <div className={`rounded-xl px-4 py-3 text-sm border ${
                lastNight.sleep_debt_estimate < 0
                  ? 'bg-poor/5 border-poor/20 text-poor'
                  : 'bg-good/5 border-good/20 text-good'
              }`}>
                {lastNight.sleep_debt_estimate < 0 ? (
                  <>
                    <span className="font-semibold">
                      {Math.abs(Math.round(lastNight.sleep_debt_estimate))} min behind
                    </span>
                    {' '}the 8h/night target this week
                  </>
                ) : (
                  <>
                    <span className="font-semibold">
                      {Math.round(lastNight.sleep_debt_estimate)} min ahead
                    </span>
                    {' '}of the 8h/night target this week
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── SECTION 2: Sleep Duration Trends ────────────────────────────────── */}
      {(insightsQ.isLoading || trendsData.length > 0) && (
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Sleep Duration</p>
              <p className="text-2xs text-slate-500">Hours per night + 7-day rolling average</p>
            </div>
            <button
              onClick={() => setShowDeep(v => !v)}
              className={`text-2xs font-semibold px-3 py-2 rounded-md transition-colors ${
                showDeep
                  ? 'bg-indigo-500/20 text-indigo-400'
                  : 'bg-surface-overlay text-slate-500 hover:text-slate-400'
              }`}
            >
              Deep
            </button>
          </div>

          {insightsQ.isLoading ? (
            <div className="skeleton rounded-xl" style={{ height: 220 }} />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart data={trendsData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={fmtDate}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                  minTickGap={40}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={v => `${v}h`}
                  width={32}
                  domain={[0, 'auto']}
                />
                <Tooltip content={<TrendsTooltip />} labelFormatter={fmtDate} />
                <Bar dataKey="total" name="Sleep" fill="#60a5fa" fillOpacity={0.7} radius={[2, 2, 0, 0]} />
                <Line
                  type="monotone"
                  dataKey="avg7d"
                  name="7d avg"
                  stroke="#fb923c"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                {showDeep && (
                  <Line
                    type="monotone"
                    dataKey="deep"
                    name="Deep"
                    stroke="#22d3ee"
                    strokeWidth={2}
                    strokeDasharray="5 3"
                    dot={false}
                    connectNulls
                  />
                )}
                {/* Anomaly markers — unusually short nights */}
                {trendsData.filter(d => d.isAnomaly).map(d => (
                  <ReferenceDot
                    key={d.date}
                    x={d.date}
                    y={d.total ?? 0}
                    r={4}
                    fill="#ef4444"
                    stroke="none"
                  />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          )}

          {/* Legend */}
          {!insightsQ.isLoading && (
            <div className="flex flex-wrap gap-3 mt-2">
              {[
                { label: 'Sleep', color: '#60a5fa' },
                { label: '7d avg', color: '#fb923c' },
                ...(showDeep ? [{ label: 'Deep', color: '#22d3ee' }] : []),
                { label: 'Short night', color: '#ef4444' },
              ].map(({ label, color }) => (
                <span key={label} className="flex items-center gap-1.5 text-2xs text-slate-500">
                  <span
                    className="inline-block h-2 w-2 rounded-full flex-shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── SECTION 3: Sleep Stage Distribution ─────────────────────────────── */}
      {(insightsQ.isLoading || stageData.length > 0) && (
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
            Sleep Stage Distribution
          </p>
          <p className="text-2xs text-slate-500 mb-3">
            How your sleep architecture shifts over time
          </p>

          {insightsQ.isLoading ? (
            <div className="skeleton rounded-xl" style={{ height: 200 }} />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={stageData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={fmtDate}
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                    minTickGap={40}
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={v => `${v}h`}
                    width={32}
                  />
                  <Tooltip content={<StageTooltip />} labelFormatter={fmtDate} />
                  <Area type="monotone" dataKey="Deep"  stackId="a" fill="#4f46e5" stroke="none" fillOpacity={0.85} />
                  <Area type="monotone" dataKey="Light" stackId="a" fill="#60a5fa" stroke="none" fillOpacity={0.85} />
                  <Area type="monotone" dataKey="REM"   stackId="a" fill="#c084fc" stroke="none" fillOpacity={0.85} />
                  <Area type="monotone" dataKey="Awake" stackId="a" fill="#94a3b8" stroke="none" fillOpacity={0.85} />
                </AreaChart>
              </ResponsiveContainer>

              <div className="flex flex-wrap gap-3 mt-2">
                {[
                  { label: 'Deep',  color: '#4f46e5' },
                  { label: 'Light', color: '#60a5fa' },
                  { label: 'REM',   color: '#c084fc' },
                  { label: 'Awake', color: '#94a3b8' },
                ].map(({ label, color }) => (
                  <span key={label} className="flex items-center gap-1.5 text-2xs text-slate-500 whitespace-nowrap">
                    <span className="inline-block h-2 w-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                    {label}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── SECTION 4: Sleep Consistency ─────────────────────────────────────── */}
      <div className="card space-y-3">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Sleep Consistency</p>

        {consistencyQ.isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
          </div>
        ) : cons?.insufficient_data ? (
          <p className="text-sm text-slate-400">{cons.message ?? 'Not enough data yet.'}</p>
        ) : cons ? (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="Avg Bedtime"    value={fmtHour(cons.avg_bedtime_hour)} status="neutral" />
              <MetricCard label="Avg Wake Time"  value={fmtHour(cons.avg_wake_hour)} status="neutral" />
              <MetricCard
                label="Avg Sleep"
                value={cons.avg_total_sleep_minutes !== null ? fmtHours(cons.avg_total_sleep_minutes) : null}
                status="neutral"
              />
              <MetricCard
                label="Bedtime Variability"
                value={cons.bedtime_std_hours !== null
                  ? `±${Math.round(cons.bedtime_std_hours * 60)}`
                  : null}
                unit=" min"
                status={
                  cons.bedtime_std_hours === null ? 'neutral'
                  : cons.bedtime_std_hours * 60 <= 30 ? 'good'
                  : cons.bedtime_std_hours * 60 <= 60 ? 'moderate'
                  : 'poor'
                }
                subtext={
                  cons.bedtime_std_hours !== null
                    ? cons.bedtime_std_hours * 60 <= 30
                      ? 'Very consistent'
                      : cons.bedtime_std_hours * 60 <= 60
                        ? 'Moderate variability'
                        : 'High variability'
                    : undefined
                }
              />
            </div>

            {cons.sleep_debt_trend && (
              <div className="rounded-xl bg-surface-overlay px-3 py-2.5">
                <p className="text-xs text-slate-500">
                  Sleep trend:{' '}
                  <span className={`font-semibold ${
                    cons.sleep_debt_trend === 'improving' ? 'text-good'
                    : cons.sleep_debt_trend === 'declining' ? 'text-poor'
                    : 'text-moderate'
                  }`}>
                    {cons.sleep_debt_trend.charAt(0).toUpperCase() + cons.sleep_debt_trend.slice(1)}
                  </span>
                  {cons.sleep_debt_trend_slope_min_per_day !== null && (
                    <span className="text-slate-400 font-mono ml-1">
                      ({cons.sleep_debt_trend_slope_min_per_day > 0 ? '+' : ''}
                      {cons.sleep_debt_trend_slope_min_per_day.toFixed(1)} min/day)
                    </span>
                  )}
                </p>
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* ── SECTION 5: Training ↔ Sleep Connections ──────────────────────────── */}
      <div className="card space-y-3">
        <div>
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            Training ↔ Sleep Connections
          </p>
          <p className="text-2xs text-slate-500 mt-0.5">How your training load shapes your sleep</p>
        </div>

        {(insightsQ.isLoading || correlationsQ.isLoading) ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => <MetricCardSkeleton key={i} />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">

            {/* Card 1: Strain → Sleep Duration */}
            <CorrelationCard
              title="High Strain → Sleep Duration"
              nSamples={corrStats.hsCount}
              minSamples={5}
            >
              {corrStats.hsSleep !== null && corrStats.normSleep !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  After high-strain days (›14):{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {fmtHours(corrStats.hsSleep)}
                  </span>
                  {' '}vs{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {fmtHours(corrStats.normSleep)}
                  </span>
                  {' '}normally
                  <span className="block text-2xs text-slate-500 mt-0.5">
                    {corrStats.hsCount} high-strain nights
                  </span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">
                  Not enough high-strain days yet.
                </p>
              )}
            </CorrelationCard>

            {/* Card 2: Sleep Duration → Recovery */}
            <CorrelationCard
              title="7.5h+ Sleep → Next-Day Recovery"
              nSamples={corrStats.goodCount}
              minSamples={5}
            >
              {corrStats.goodRecovery !== null && corrStats.shortRecovery !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  With 7.5+ hours:{' '}
                  <span className="font-semibold text-good">
                    {Math.round(corrStats.goodRecovery)}%
                  </span>
                  {' '}recovery vs{' '}
                  <span className="font-semibold text-poor">
                    {Math.round(corrStats.shortRecovery)}%
                  </span>
                  {' '}on shorter nights
                  <span className="block text-2xs text-slate-500 mt-0.5">
                    {corrStats.goodCount} nights with recovery data
                  </span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">
                  Need more nights with recovery data.
                </p>
              )}
            </CorrelationCard>

            {/* Card 3: High Strain → Deep Sleep */}
            <CorrelationCard
              title="High Strain → Deep Sleep"
              nSamples={corrStats.hsCount}
              minSamples={5}
            >
              {corrStats.hsDeepPct !== null && corrStats.normDeepPct !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  High-strain nights:{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {corrStats.hsDeepPct.toFixed(1)}%
                  </span>
                  {' '}deep vs{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {corrStats.normDeepPct.toFixed(1)}%
                  </span>
                  {' '}normally
                  <span className="block text-2xs text-slate-500 mt-0.5">
                    {corrStats.hsCount} high-strain nights
                  </span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">
                  Need more high-strain nights with stage data.
                </p>
              )}
            </CorrelationCard>

          </div>
        )}
      </div>

    </div>
  )
}
