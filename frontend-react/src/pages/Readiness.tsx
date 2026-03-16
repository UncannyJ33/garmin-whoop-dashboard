/**
 * Morning Readiness page — answers "How ready am I to train today?"
 */
import { useMemo } from 'react'
import {
  useReadinessHistory,
  useReadinessToday,
  useWeeklySummary,
} from '../hooks/useApi'
import { todayISO, useDateRange } from '../hooks/useDateRange'
import { ChartSkeleton, MetricCardSkeleton } from '../components/LoadingState'
import { ErrorState } from '../components/ErrorState'
import { MetricCard } from '../components/MetricCard'
import { StatusBadge } from '../components/StatusBadge'
import { TrendChart } from '../components/TrendChart'
import { WeekComparison } from '../components/WeekComparison'
import type { ContributingFactor } from '../types/api'

// ── helpers ──────────────────────────────────────────────────────────────────

type Status = 'good' | 'moderate' | 'poor' | 'neutral'

function normStatus(v: number | null): Status {
  if (v === null) return 'neutral'
  if (v >= 66) return 'good'
  if (v >= 33) return 'moderate'
  return 'poor'
}

function scoreColor(score: number): string {
  if (score >= 75) return 'text-good'
  if (score >= 50) return 'text-moderate'
  return 'text-poor'
}

function heroGradient(score: number): string {
  if (score >= 75)
    return 'radial-gradient(ellipse at 50% 0%, rgba(34,197,94,0.15) 0%, transparent 70%)'
  if (score >= 50)
    return 'radial-gradient(ellipse at 50% 0%, rgba(245,158,11,0.12) 0%, transparent 70%)'
  return 'radial-gradient(ellipse at 50% 0%, rgba(239,68,68,0.12) 0%, transparent 70%)'
}

function factorLabel(key: string): string {
  const MAP: Record<string, string> = {
    whoop_recovery: 'Recovery',
    hrv_trend: 'HRV Trend',
    body_battery: 'Body Battery',
    sleep_quality: 'Sleep Quality',
    training_load: 'Training Load',
  }
  return MAP[key] ?? key.replace(/_/g, ' ')
}

function formatFactor(
  key: string,
  f: ContributingFactor,
): { value: string | number | null; unit: string } {
  const v = f.raw_value
  if (v === null) return { value: null, unit: '' }
  switch (key) {
    case 'whoop_recovery': return { value: Math.round(v), unit: '%' }
    case 'hrv_trend':      return { value: Math.round(v), unit: ' ms' }
    case 'body_battery':   return { value: Math.round(v), unit: '' }
    case 'sleep_quality':  return { value: Math.round(v), unit: '%' }
    case 'training_load':  return { value: v.toFixed(2), unit: 'x' }
    default:               return { value: Math.round(v), unit: '' }
  }
}

type ReadinessLevel = 'Push hard' | 'Train normally' | 'Go easy' | 'Rest day'
const LEVELS: ReadinessLevel[] = ['Push hard', 'Train normally', 'Go easy', 'Rest day']

function extractLevel(recommendation: string): ReadinessLevel {
  return LEVELS.find(l => recommendation.startsWith(l)) ?? 'Train normally'
}

function rolling7d(values: (number | null)[]): (number | null)[] {
  return values.map((_, i) => {
    const window = values
      .slice(Math.max(0, i - 6), i + 1)
      .filter((v): v is number => v !== null)
    return window.length > 0 ? window.reduce((a, b) => a + b, 0) / window.length : null
  })
}

// ── sub-components ────────────────────────────────────────────────────────────

function HeroSkeleton() {
  return (
    <div className="card flex flex-col items-center justify-center py-16 gap-4">
      <div className="skeleton h-4 w-36 mb-2" />
      <div className="skeleton rounded-2xl" style={{ height: 108, width: 160 }} />
      <div className="skeleton h-9 w-48 rounded-full" />
      <div className="skeleton h-3 w-44" />
    </div>
  )
}

function WeekComparisonSkeleton() {
  return (
    <div className="card space-y-3">
      <div className="skeleton h-4 w-28" />
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton h-16 rounded-xl" />
        ))}
      </div>
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────

export function Readiness() {
  const range30 = useDateRange(30)

  const todayQ  = useReadinessToday()
  const historyQ = useReadinessHistory(range30.start, range30.end)
  const weeklyQ  = useWeeklySummary(todayISO())

  // Trend data: merge history scores + 7d rolling avg
  const trendData = useMemo(() => {
    if (!historyQ.data || historyQ.data.length === 0) return []
    const scores = historyQ.data.map(p => p.score)
    const avgs = rolling7d(scores)
    return historyQ.data.map((p, i) => ({
      date: p.date,
      value: p.score,
      avg7d: avgs[i] !== null ? parseFloat(avgs[i]!.toFixed(1)) : null,
    }))
  }, [historyQ.data])

  // Weekly comparison rows
  const weekMetrics = useMemo(() => {
    if (!weeklyQ.data) return []
    const w = weeklyQ.data
    const c = w.comparison ?? {}
    return [
      {
        label: 'Readiness',
        value: w.avg_readiness !== null ? String(Math.round(w.avg_readiness)) : null,
        pctChange: (c['avg_readiness'] as number | null) ?? null,
      },
      {
        label: 'Avg HRV',
        value: w.avg_hrv !== null ? `${Math.round(w.avg_hrv)} ms` : null,
        pctChange: (c['avg_hrv'] as number | null) ?? null,
      },
      {
        label: 'Avg RHR',
        value: w.avg_rhr !== null ? `${Math.round(w.avg_rhr)} bpm` : null,
        pctChange: (c['avg_rhr'] as number | null) ?? null,
        lowerIsBetter: true,
      },
      {
        label: 'Total Strain',
        value: w.total_strain !== null ? w.total_strain.toFixed(1) : null,
        pctChange: (c['total_strain'] as number | null) ?? null,
      },
      {
        label: 'Workouts',
        value: String(w.workout_count),
        pctChange: (c['workout_count'] as number | null) ?? null,
      },
      {
        label: 'Avg Sleep',
        value: w.avg_sleep_duration !== null
          ? `${(w.avg_sleep_duration / 60).toFixed(1)}h`
          : null,
        pctChange: (c['avg_sleep_duration'] as number | null) ?? null,
      },
    ]
  }, [weeklyQ.data])

  // Full-page error if primary data fails
  if (todayQ.isError && !todayQ.isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Morning Readiness</h1>
        <ErrorState
          message="Could not reach the API. Make sure the backend is running on port 8000."
          onRetry={() => void todayQ.refetch()}
        />
      </div>
    )
  }

  // 204 No Content — user has no data yet
  if (todayQ.isSuccess && !todayQ.data) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Morning Readiness</h1>
        <div className="card flex flex-col items-center justify-center py-16 gap-3 text-center">
          <p className="text-4xl">📡</p>
          <p className="text-lg font-semibold text-slate-700 dark:text-slate-200">No readiness data yet</p>
          <p className="text-sm text-slate-500">Sync your devices to get started.</p>
        </div>
      </div>
    )
  }

  const data = todayQ.data
  const factors = data ? Object.entries(data.contributing_factors) : []
  const sourceCount = factors.filter(([, f]) => f.raw_value !== null).length

  // Per-factor cards for section 2 & key metrics for section 4
  const hrv      = data?.contributing_factors['hrv_trend']
  const recovery = data?.contributing_factors['whoop_recovery']
  const battery  = data?.contributing_factors['body_battery']
  const sleep    = data?.contributing_factors['sleep_quality']

  return (
    <div className="space-y-4 pb-16">

      {/* ── SECTION 1: Hero ──────────────────────────────────────────────── */}
      {todayQ.isLoading ? (
        <HeroSkeleton />
      ) : data ? (
        <div
          className="card relative overflow-hidden flex flex-col items-center justify-center text-center py-14 gap-3"
          style={{ backgroundImage: data.score != null ? heroGradient(data.score) : undefined }}
        >
          <p className="metric-label tracking-[0.2em]">Morning Readiness</p>

          <p
            className={`font-mono font-bold tabular-nums leading-none ${data.score != null ? scoreColor(data.score) : 'text-slate-400'}`}
            style={{ fontSize: 'clamp(72px, 16vw, 112px)' }}
          >
            {data.score != null ? Math.round(data.score) : '--'}
          </p>

          <StatusBadge
            level={extractLevel(data.recommendation)}
            size="lg"
          />

          <p className="text-xs text-slate-500 mt-1">
            Based on {sourceCount} of {factors.length} data sources
            {data.confidence < 0.95 && (
              <span className="ml-1 text-moderate">· partial data</span>
            )}
          </p>
        </div>
      ) : null}

      {/* ── SECTION 2: Contributing Factors ──────────────────────────────── */}
      <div>
        <p className="metric-label mb-2 px-0.5">Contributing Factors</p>
        {todayQ.isLoading ? (
          <div className="flex gap-3 overflow-x-auto pb-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex-shrink-0 w-40">
                <MetricCardSkeleton />
              </div>
            ))}
          </div>
        ) : data ? (
          <div className="flex gap-3 overflow-x-auto pb-1 sm:grid sm:grid-cols-5 sm:overflow-visible">
            {factors.map(([key, factor]) => {
              const { value, unit } = formatFactor(key, factor)
              return (
                <div key={key} className="flex-shrink-0 w-40 sm:w-auto">
                  <MetricCard
                    label={factorLabel(key)}
                    value={value}
                    unit={unit}
                    status={normStatus(factor.normalized_value)}
                    subtext={
                      factor.normalized_value !== null
                        ? `Score ${Math.round(factor.normalized_value)} · ${Math.round(factor.effective_weight * 100)}% wt`
                        : `${Math.round(factor.effective_weight * 100)}% weight`
                    }
                  />
                </div>
              )
            })}
          </div>
        ) : null}
      </div>

      {/* ── SECTION 3: 30-Day Trend ───────────────────────────────────────── */}
      {historyQ.isLoading ? (
        <ChartSkeleton height={200} />
      ) : historyQ.isError ? (
        <ErrorState
          message="Could not load readiness history."
          onRetry={() => void historyQ.refetch()}
        />
      ) : trendData.length > 0 ? (
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
            30-Day Readiness Trend
          </p>
          <TrendChart
            data={trendData}
            metricName="Readiness"
            unit="%"
            showRollingAvg
            height={200}
            color="#818cf8"
            formatValue={(v) => Math.round(v).toString()}
          />
          <p className="text-2xs text-slate-500 mt-2">
            Purple = daily · Orange = 7-day rolling avg
          </p>
        </div>
      ) : null}

      {/* ── SECTION 4: Key Metrics Today ─────────────────────────────────── */}
      <div>
        <p className="metric-label mb-2 px-0.5">Key Metrics Today</p>
        {todayQ.isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
          </div>
        ) : data ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              label="HRV"
              value={hrv?.raw_value !== null && hrv?.raw_value !== undefined
                ? Math.round(hrv.raw_value) : null}
              unit=" ms"
              status={normStatus(hrv?.normalized_value ?? null)}
            />
            <MetricCard
              label="Recovery"
              value={recovery?.raw_value !== null && recovery?.raw_value !== undefined
                ? Math.round(recovery.raw_value) : null}
              unit="%"
              status={normStatus(recovery?.normalized_value ?? null)}
            />
            <MetricCard
              label="Body Battery"
              value={battery?.raw_value !== null && battery?.raw_value !== undefined
                ? Math.round(battery.raw_value) : null}
              status={normStatus(battery?.normalized_value ?? null)}
              subtext={weeklyQ.data?.avg_rhr
                ? `RHR avg ${Math.round(weeklyQ.data.avg_rhr)} bpm`
                : undefined}
            />
            <MetricCard
              label="Sleep Quality"
              value={sleep?.raw_value !== null && sleep?.raw_value !== undefined
                ? Math.round(sleep.raw_value) : null}
              unit="%"
              status={normStatus(sleep?.normalized_value ?? null)}
              subtext={weeklyQ.data?.avg_sleep_duration
                ? `${(weeklyQ.data.avg_sleep_duration / 60).toFixed(1)}h avg / night`
                : undefined}
            />
          </div>
        ) : null}
      </div>

      {/* ── SECTION 5: Weekly Comparison ─────────────────────────────────── */}
      {weeklyQ.isLoading ? (
        <WeekComparisonSkeleton />
      ) : weeklyQ.data ? (
        <WeekComparison
          weekLabel={`${weeklyQ.data.period_start} → ${weeklyQ.data.period_end}`}
          prevWeekLabel="vs prev week"
          metrics={weekMetrics}
        />
      ) : weeklyQ.isError ? (
        <ErrorState
          message="Could not load weekly summary."
          onRetry={() => void weeklyQ.refetch()}
        />
      ) : null}

    </div>
  )
}
