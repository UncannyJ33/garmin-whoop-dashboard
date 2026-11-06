/**
 * Recovery + Sleep page — merged view of sleep analysis and recovery activities.
 *
 * Sections:
 *   1. Recovery Overview   — last night hero, stage bar, performance/efficiency/deep/REM, debt banner
 *   2. Sleep Trends        — duration bars + 7d avg + anomaly markers + deep toggle
 *   3. Sleep Stage Dist    — stacked AreaChart
 *   4. Sleep Consistency   — avg bedtime/wake, variability interpretation, debt trend
 *   5. Training ↔ Sleep    — 3 correlation insight cards
 *   6. Recovery Activities — with/without comparison, per-type bars, condensed log
 */
import type { ReactNode } from 'react'
import { memo, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
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
  useRecovery,
  useRecoveryWithWithout,
} from '../hooks/useApi'
import { useDateRangeContext } from '../context/DateRangeContext'
import { MetricCardSkeleton, NoDataState } from '../components/LoadingState'
import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { SleepStageBar } from '../components/SleepStageBar'
import type { SleepInsight } from '../types/api'
import { DayButton } from '../components/DayButton'
import { fmtDate } from '../utils/formatters'

// ── helpers ────────────────────────────────────────────────────────────────────

/**
 * UTC decimal hour → local time string (e.g. "10:45 PM").
 * avg_bedtime_hour / avg_wake_hour from the API are UTC.
 */
function fmtHour(utcHour: number | null): string {
  if (utcHour === null) return '—'
  const norm = ((utcHour % 24) + 24) % 24
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

/** Format a debt/surplus in minutes into a readable string (e.g. "1h 20m" or "45 min"). */
function fmtDebt(absMinutes: number): string {
  if (absMinutes >= 60) {
    const h = Math.floor(absMinutes / 60)
    const m = Math.round(absMinutes % 60)
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${Math.round(absMinutes)} min`
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

/** Stable color per activity name. */
const ACTIVITY_COLORS = ['#4472CA', '#70AD47', '#FFC000', '#FF7A00', '#DC143C', '#9467BD', '#8C564B']
function colorForActivity(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0
  return ACTIVITY_COLORS[Math.abs(hash) % ACTIVITY_COLORS.length]
}

// ── sub-components ─────────────────────────────────────────────────────────────

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</p>
      {subtitle && <p className="text-2xs text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

interface TooltipEntry { name: string; value: number | null; color: string }

const TrendsTooltip = memo(function TrendsTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="text-slate-400 font-medium">{label ? fmtDate(label) : ''}</p>
      {payload.map(e =>
        e.value !== null && e.value !== undefined ? (
          <p key={e.name} style={e.color ? { color: e.color } : undefined} className="font-mono">
            {e.name}: {e.value.toFixed(1)}h
          </p>
        ) : null,
      )}
    </div>
  )
})

const StageTooltip = memo(function StageTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipEntry[]; label?: string }) {
  if (!active || !payload?.length) return null
  const total = payload.reduce((s, e) => s + (e.value ?? 0), 0)
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="text-slate-400 font-medium">{label ? fmtDate(label) : ''}</p>
      {[...payload].reverse().map(e =>
        (e.value ?? 0) > 0 ? (
          <p key={e.name} style={e.color ? { color: e.color } : undefined} className="font-mono">
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
})

function CorrelationCard({
  title, children, nSamples, minSamples = 7,
}: { title: string; children: ReactNode; nSamples: number; minSamples?: number }) {
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

// ── page ───────────────────────────────────────────────────────────────────────

export function Recovery() {
  const { days, setDays, start, end } = useDateRangeContext()
  const [showDeep, setShowDeep] = useState(false)

  const insightsQ     = useSleepInsights(start, end)
  const consistencyQ  = useSleepConsistency(days)
  const correlationsQ = useSleepCorrelations(days)
  const activitiesQ   = useRecovery(start, end)
  const withWithoutQ  = useRecoveryWithWithout(start, end)

  const insights   = insightsQ.data ?? []
  const activities = activitiesQ.data ?? []

  const lastNight = useMemo(
    () => (insights.length > 0 ? insights[insights.length - 1] : null),
    [insights],
  )

  // ── Sleep trends data ──────────────────────────────────────────────────────
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

  // ── Stage distribution data ────────────────────────────────────────────────
  const stageData = useMemo(
    () => insights.map(d => ({
      date:  d.date,
      Deep:  d.deep_minutes  !== null ? +(d.deep_minutes  / 60).toFixed(2) : 0,
      REM:   d.rem_minutes   !== null ? +(d.rem_minutes   / 60).toFixed(2) : 0,
      Light: d.light_minutes !== null ? +(d.light_minutes / 60).toFixed(2) : 0,
      Awake: d.awake_minutes !== null ? +(d.awake_minutes / 60).toFixed(2) : 0,
    })),
    [insights],
  )

  // ── Correlation stats ──────────────────────────────────────────────────────
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
      goodCount: goodSleepNights.length,
      hsDeepPct, normDeepPct,
    }
  }, [insights])

  // ── Recovery activity stats ────────────────────────────────────────────────
  const byTypeRecovery = useMemo((): Array<{ activity: string; avg: number; n: number }> => {
    const acc: Record<string, { sum: number; n: number }> = {}
    for (const a of activities) {
      if (a.next_day_recovery === null) continue
      if (!acc[a.activity]) acc[a.activity] = { sum: 0, n: 0 }
      acc[a.activity].sum += a.next_day_recovery
      acc[a.activity].n += 1
    }
    return Object.entries(acc)
      .map(([activity, { sum, n }]) => ({ activity, avg: sum / n, n }))
      .sort((a, b) => b.avg - a.avg)
  }, [activities])

  const byTypeSleep = useMemo((): Array<{ activity: string; avg: number; n: number }> => {
    const acc: Record<string, { sum: number; n: number }> = {}
    for (const a of activities) {
      if (a.next_day_sleep_perf === null) continue
      if (!acc[a.activity]) acc[a.activity] = { sum: 0, n: 0 }
      acc[a.activity].sum += a.next_day_sleep_perf
      acc[a.activity].n += 1
    }
    return Object.entries(acc)
      .map(([activity, { sum, n }]) => ({ activity, avg: sum / n, n }))
      .sort((a, b) => b.avg - a.avg)
  }, [activities])

  const cons = consistencyQ.data

  if (insightsQ.isError) {
    return (
      <div className="space-y-4">
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 32, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>Recovery</h1>
        <ErrorState
          message="Could not load sleep data. Make sure the backend is running on port 8000."
          onRetry={() => void insightsQ.refetch()}
        />
      </div>
    )
  }

  if (insightsQ.isSuccess && insights.length === 0 && activitiesQ.isSuccess) {
    return <NoDataState message="No sleep or recovery data found. Connect Whoop to start tracking." />
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header + date range ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between animate-fade-in">
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 32, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>Recovery</h1>
        <div className="flex gap-1.5">
          {[7, 14, 30, 60].map(n => (
            <DayButton key={n} n={n} active={days === n} onClick={() => setDays(n)} />
          ))}
        </div>
      </div>

      {/* ── SECTION 1: Recovery Overview ─────────────────────────────────────── */}
      <div className="card space-y-4 animate-fade-in delay-1">
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

            {/* Metric grid — performance, efficiency, deep, REM */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
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

            {/* Sleep debt banner — detailed with hours + trend */}
            {lastNight.sleep_debt_estimate !== null && (
              <div className={`rounded-xl px-4 py-3 border ${
                lastNight.sleep_debt_estimate < 0
                  ? 'bg-poor/5 border-poor/20'
                  : 'bg-good/5 border-good/20'
              }`}>
                <p className={`text-sm font-semibold ${
                  lastNight.sleep_debt_estimate < 0 ? 'text-poor' : 'text-good'
                }`}>
                  {lastNight.sleep_debt_estimate < 0
                    ? `${fmtDebt(Math.abs(lastNight.sleep_debt_estimate))} behind`
                    : `${fmtDebt(lastNight.sleep_debt_estimate)} ahead`
                  }{' '}
                  <span className="font-normal opacity-80">
                    of the 8h/night target this week
                  </span>
                </p>
                {cons?.sleep_debt_trend && (
                  <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>
                    Trend:{' '}
                    <span className={`font-medium ${
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
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── SECTION 2: Sleep Duration Trends ─────────────────────────────────── */}
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

          {!insightsQ.isLoading && (
            <div className="flex flex-wrap gap-3 mt-2">
              {[
                { label: 'Sleep', color: '#60a5fa' },
                { label: '7d avg', color: '#fb923c' },
                ...(showDeep ? [{ label: 'Deep', color: '#22d3ee' }] : []),
                { label: 'Short night', color: '#ef4444' },
              ].map(({ label, color }) => (
                <span key={label} className="flex items-center gap-1.5 text-2xs text-slate-500">
                  <span className="inline-block h-2 w-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── SECTION 3: Sleep Stage Distribution ──────────────────────────────── */}
      {(insightsQ.isLoading || stageData.length > 0) && (
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
            Sleep Stage Distribution
          </p>
          <p className="text-2xs text-slate-500 mb-3">How your sleep architecture shifts over time</p>

          {insightsQ.isLoading ? (
            <div className="skeleton rounded-xl" style={{ height: 200 }} />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={stageData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <defs>
                    <linearGradient id="gradDeep"  x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#1e7a5a" stopOpacity={0.9} />
                      <stop offset="95%" stopColor="#1e7a5a" stopOpacity={0.15} />
                    </linearGradient>
                    <linearGradient id="gradLight" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#3d6b9e" stopOpacity={0.9} />
                      <stop offset="95%" stopColor="#3d6b9e" stopOpacity={0.15} />
                    </linearGradient>
                    <linearGradient id="gradREM"   x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#7a5ea0" stopOpacity={0.9} />
                      <stop offset="95%" stopColor="#7a5ea0" stopOpacity={0.15} />
                    </linearGradient>
                    <linearGradient id="gradAwake" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#4a4a4a" stopOpacity={0.9} />
                      <stop offset="95%" stopColor="#4a4a4a" stopOpacity={0.15} />
                    </linearGradient>
                  </defs>
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
                  <Area type="monotone" dataKey="Deep"  stackId="a" fill="url(#gradDeep)"  stroke="none" />
                  <Area type="monotone" dataKey="Light" stackId="a" fill="url(#gradLight)" stroke="none" />
                  <Area type="monotone" dataKey="REM"   stackId="a" fill="url(#gradREM)"   stroke="none" />
                  <Area type="monotone" dataKey="Awake" stackId="a" fill="url(#gradAwake)" stroke="none" />
                </AreaChart>
              </ResponsiveContainer>

              <div className="flex flex-wrap gap-3 mt-2">
                {[
                  { label: 'Deep',  color: '#1e7a5a' },
                  { label: 'Light', color: '#3d6b9e' },
                  { label: 'REM',   color: '#7a5ea0' },
                  { label: 'Awake', color: '#4a4a4a' },
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

      {/* ── SECTION 4: Sleep Consistency ──────────────────────────────────────── */}
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
              <MetricCard label="Avg Bedtime"   value={fmtHour(cons.avg_bedtime_hour)} status="neutral" />
              <MetricCard label="Avg Wake Time" value={fmtHour(cons.avg_wake_hour)}    status="neutral" />
              <MetricCard
                label="Avg Sleep"
                value={cons.avg_total_sleep_minutes !== null ? fmtHours(cons.avg_total_sleep_minutes) : null}
                status="neutral"
              />
              <MetricCard
                label="Bedtime Variability"
                value={cons.bedtime_std_hours !== null ? `±${Math.round(cons.bedtime_std_hours * 60)}` : null}
                unit=" min"
                status={
                  cons.bedtime_std_hours === null ? 'neutral'
                  : cons.bedtime_std_hours * 60 <= 30 ? 'good'
                  : cons.bedtime_std_hours * 60 <= 60 ? 'moderate'
                  : 'poor'
                }
              />
            </div>

            {/* Bedtime variability interpretation */}
            {cons.bedtime_std_hours !== null && (
              <div className="rounded-xl bg-surface-overlay px-3 py-2.5">
                <p className="text-xs text-slate-500">
                  {cons.bedtime_std_hours * 60 <= 30 ? (
                    <>Your bedtime varies by <span className="font-semibold text-good">±{Math.round(cons.bedtime_std_hours * 60)} min</span> — great consistency.</>
                  ) : cons.bedtime_std_hours * 60 <= 60 ? (
                    <>Your bedtime varies by <span className="font-semibold text-moderate">±{Math.round(cons.bedtime_std_hours * 60)} min</span> — a tighter window would help sleep quality.</>
                  ) : (
                    <>Your bedtime varies by <span className="font-semibold text-poor">±{Math.round(cons.bedtime_std_hours * 60)} min</span> — try to tighten this for better recovery.</>
                  )}
                </p>
              </div>
            )}

            {/* Sleep debt trend */}
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

      {/* ── SECTION 5: Training ↔ Sleep Connections ───────────────────────────── */}
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

            <CorrelationCard title="High Strain → Sleep Duration" nSamples={corrStats.hsCount} minSamples={5}>
              {corrStats.hsSleep !== null && corrStats.normSleep !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  After high-strain days (›14):{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{fmtHours(corrStats.hsSleep)}</span>
                  {' '}vs{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{fmtHours(corrStats.normSleep)}</span>
                  {' '}normally
                  <span className="block text-2xs text-slate-500 mt-0.5">{corrStats.hsCount} high-strain nights</span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">Not enough high-strain days yet.</p>
              )}
            </CorrelationCard>

            <CorrelationCard title="7.5h+ Sleep → Next-Day Recovery" nSamples={corrStats.goodCount} minSamples={5}>
              {corrStats.goodRecovery !== null && corrStats.shortRecovery !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  With 7.5+ hours:{' '}
                  <span className="font-semibold text-good">{Math.round(corrStats.goodRecovery)}%</span>
                  {' '}recovery vs{' '}
                  <span className="font-semibold text-poor">{Math.round(corrStats.shortRecovery)}%</span>
                  {' '}on shorter nights
                  <span className="block text-2xs text-slate-500 mt-0.5">{corrStats.goodCount} nights with recovery data</span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">Need more nights with recovery data.</p>
              )}
            </CorrelationCard>

            <CorrelationCard title="High Strain → Deep Sleep" nSamples={corrStats.hsCount} minSamples={5}>
              {corrStats.hsDeepPct !== null && corrStats.normDeepPct !== null ? (
                <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                  High-strain nights:{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{corrStats.hsDeepPct.toFixed(1)}%</span>
                  {' '}deep vs{' '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{corrStats.normDeepPct.toFixed(1)}%</span>
                  {' '}normally
                  <span className="block text-2xs text-slate-500 mt-0.5">{corrStats.hsCount} high-strain nights</span>
                </p>
              ) : (
                <p className="text-sm text-slate-400">Need more high-strain nights with stage data.</p>
              )}
            </CorrelationCard>

          </div>
        )}
      </div>

      {/* ── SECTION 6: Recovery Activities ────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="px-0.5">
          <p style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
            Do recovery activities actually work for you?
          </p>
          <p className="text-2xs text-slate-500 mt-0.5">
            Based on your last {days} days of data
          </p>
        </div>

        {/* With vs Without — most prominent */}
        <div className="card">
          <SectionHeader
            title="Recovery Days vs Non-Recovery Days"
            subtitle="Next-day recovery score following days with vs without a recovery activity"
          />
          {withWithoutQ.isLoading ? (
            <div className="grid grid-cols-2 gap-3">
              <MetricCardSkeleton />
              <MetricCardSkeleton />
            </div>
          ) : !withWithoutQ.data || (withWithoutQ.data.with_count === 0 && withWithoutQ.data.without_count === 0) ? (
            <p className="text-sm text-slate-400 py-4 text-center">
              Not enough data to compare recovery vs non-recovery days.
            </p>
          ) : (() => {
            const d = withWithoutQ.data
            const diff = d.with_avg !== null && d.without_avg !== null ? d.with_avg - d.without_avg : null
            return (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-xl bg-surface-overlay px-4 py-3 space-y-1">
                    <p className="text-2xs text-slate-500">With recovery activity</p>
                    <p className="font-mono text-2xl font-bold text-slate-800 dark:text-slate-100">
                      {d.with_avg !== null ? d.with_avg.toFixed(1) : '—'}
                    </p>
                    <p className="text-2xs text-slate-500">{d.with_count} day{d.with_count !== 1 ? 's' : ''}</p>
                    {diff !== null && (
                      <p className={`text-xs font-semibold ${diff >= 0 ? 'text-good' : 'text-poor'}`}>
                        {diff >= 0 ? '+' : ''}{diff.toFixed(1)} vs without
                      </p>
                    )}
                  </div>
                  <div className="rounded-xl bg-surface-overlay px-4 py-3 space-y-1">
                    <p className="text-2xs text-slate-500">Without recovery activity</p>
                    <p className="font-mono text-2xl font-bold text-slate-800 dark:text-slate-100">
                      {d.without_avg !== null ? d.without_avg.toFixed(1) : '—'}
                    </p>
                    <p className="text-2xs text-slate-500">{d.without_count} day{d.without_count !== 1 ? 's' : ''}</p>
                  </div>
                </div>
                {diff !== null && (
                  <p className="text-xs text-slate-500">
                    Your next-day recovery is{' '}
                    <span className={`font-semibold ${diff >= 0 ? 'text-good' : 'text-poor'}`}>
                      {Math.abs(diff).toFixed(1)} points {diff >= 0 ? 'higher' : 'lower'}
                    </span>{' '}
                    after a recovery activity day.
                  </p>
                )}
              </div>
            )
          })()}
        </div>

        {/* Next-day recovery by activity type */}
        {(activitiesQ.isLoading || byTypeRecovery.length > 0) && (
          <div className="card">
            <SectionHeader
              title="Next-Day Recovery by Activity Type"
              subtitle="Which recovery activities give you the best next-day recovery?"
            />
            {activitiesQ.isLoading ? (
              <div className="skeleton rounded-xl" style={{ height: 160 }} />
            ) : byTypeRecovery.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No recovery data yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(140, byTypeRecovery.length * 36)}>
                <BarChart
                  data={byTypeRecovery}
                  layout="vertical"
                  margin={{ top: 4, right: 32, bottom: 0, left: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} domain={[0, 100]} />
                  <YAxis
                    type="category"
                    dataKey="activity"
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={110}
                  />
                  <Tooltip
                    content={({ active, payload }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{(payload[0].payload as { activity: string }).activity}</p>
                          <p className="text-slate-400">Avg recovery: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)}</span></p>
                          <p className="text-slate-400">Sessions: <span className="font-mono font-semibold">{(payload[0].payload as { n: number }).n}</span></p>
                        </div>
                      ) : null
                    )}
                  />
                  <Bar dataKey="avg" name="Avg Next-Day Recovery" radius={[0, 3, 3, 0]} fill="#4472CA" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* Next-day sleep performance by activity type */}
        {(activitiesQ.isLoading || byTypeSleep.length > 0) && (
          <div className="card">
            <SectionHeader
              title="Next-Day Sleep Performance by Activity Type"
              subtitle="Which activities lead to the best sleep the following night?"
            />
            {activitiesQ.isLoading ? (
              <div className="skeleton rounded-xl" style={{ height: 160 }} />
            ) : byTypeSleep.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No sleep performance data yet.</p>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(140, byTypeSleep.length * 36)}>
                <BarChart
                  data={byTypeSleep}
                  layout="vertical"
                  margin={{ top: 4, right: 32, bottom: 0, left: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} domain={[0, 100]} />
                  <YAxis
                    type="category"
                    dataKey="activity"
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={110}
                  />
                  <Tooltip
                    content={({ active, payload }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{(payload[0].payload as { activity: string }).activity}</p>
                          <p className="text-slate-400">Avg sleep perf: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)}%</span></p>
                          <p className="text-slate-400">Sessions: <span className="font-mono font-semibold">{(payload[0].payload as { n: number }).n}</span></p>
                        </div>
                      ) : null
                    )}
                  />
                  <Bar dataKey="avg" name="Avg Sleep Performance" radius={[0, 3, 3, 0]} fill="#70AD47" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        )}

        {/* Condensed activity log */}
        {!activitiesQ.isLoading && activities.length > 0 && (
          <div className="card">
            <SectionHeader title="Activity Log" />
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left border-b border-surface-border">
                  <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Date</th>
                  <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Activity</th>
                  <th className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap">Dur</th>
                  <th className="pb-2 text-slate-500 font-medium whitespace-nowrap">Next-Day</th>
                </tr>
              </thead>
              <tbody>
                {activities.map((a, i) => (
                  <tr key={i} className="border-b border-surface-border last:border-0">
                    <td className="py-2.5 pr-4 font-mono text-slate-500 whitespace-nowrap">{fmtDate(a.date)}</td>
                    <td className="py-2.5 pr-4 font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">
                      <span
                        className="inline-block h-1.5 w-1.5 rounded-full mr-1.5 flex-shrink-0 align-middle"
                        style={{ backgroundColor: colorForActivity(a.activity) }}
                      />
                      {a.activity}
                    </td>
                    <td className="py-2.5 pr-4 font-mono text-slate-400">
                      {a.dur_min !== null ? `${a.dur_min.toFixed(0)}m` : '—'}
                    </td>
                    <td className={`py-2.5 font-mono font-semibold ${
                      a.next_day_recovery !== null
                        ? a.next_day_recovery >= 67 ? 'text-good'
                        : a.next_day_recovery >= 34 ? 'text-moderate'
                        : 'text-poor'
                        : 'text-slate-500'
                    }`}>
                      {a.next_day_recovery !== null ? `${a.next_day_recovery.toFixed(0)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  )
}
