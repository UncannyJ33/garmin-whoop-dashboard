/**
 * Insights page — replaces /trends.
 *
 * Sections:
 *   1. Weekly Digest       — 2–3 programmatic DigestCards from WeeklySummary
 *   2. Metric Explorer     — TrendChart for any of 9 metrics, trend badge with context
 *   3. Correlations        — HRV↔Recovery, Strain↔Next-Day, Sleep↔Body Battery
 *   4. Anomaly Feed        — card-style enriched anomaly list, last 20, date desc
 *   4. Correlations        — natural-language cards; Strain↔Recovery includes scatter
 *   5. (Future placeholder — LLM-powered personalized insights, not yet built)
 */
import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  useAnomalies,
  useMetricTrend,
  useWeeklyDigest,
  useWeeklySummary,
  useWorkouts,
} from '../hooks/useApi'
import { TrendChart } from '../components/TrendChart'
import type { TrendDataPoint } from '../components/TrendChart'
import type { WeeklySummary } from '../types/api'

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
  return new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
    .toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function dateShift(iso: string, days: number): string {
  const d = new Date(iso + 'T12:00:00')
  d.setDate(d.getDate() + days)
  return toISO(d)
}

/** Pearson r on parallel arrays. Requires ≥7 non-null pairs. */
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
  const dx  = Math.sqrt(pairs.reduce((s, [x]) => s + (x - mx) ** 2, 0))
  const dy  = Math.sqrt(pairs.reduce((s, [, y]) => s + (y - my) ** 2, 0))
  return { r: dx === 0 || dy === 0 ? null : num / (dx * dy), n }
}

function alignByDate(
  datesA: string[], valuesA: (number | null)[],
  datesB: string[], valuesB: (number | null)[],
): { xs: (number | null)[]; ys: (number | null)[] } {
  const mapB = new Map(datesB.map((d, i) => [d, valuesB[i]]))
  return { xs: valuesA, ys: datesA.map(d => mapB.get(d) ?? null) }
}

function alignShifted(
  datesA: string[], valuesA: (number | null)[],
  datesB: string[], valuesB: (number | null)[],
  shiftDays: number,
): { xs: (number | null)[]; ys: (number | null)[] } {
  const mapB = new Map(datesB.map((d, i) => [d, valuesB[i]]))
  return { xs: valuesA, ys: datesA.map(d => mapB.get(dateShift(d, shiftDays)) ?? null) }
}

function corrStrength(r: number): string {
  const abs = Math.abs(r)
  if (abs >= 0.6) return r > 0 ? 'strong' : 'strong inverse'
  if (abs >= 0.4) return r > 0 ? 'moderate' : 'moderate inverse'
  if (abs >= 0.2) return r > 0 ? 'weak' : 'weak inverse'
  return 'very weak'
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
  { key: 'recovery',       label: 'Recovery',       unit: '%',    color: '#34d399' },
  { key: 'hrv',            label: 'HRV',            unit: ' ms',  color: '#818cf8' },
  { key: 'resting_hr',     label: 'Resting HR',     unit: ' bpm', color: '#f87171', lowerIsBetter: true },
  { key: 'strain',         label: 'Strain',         unit: '',     color: '#fb923c' },
  { key: 'sleep_duration', label: 'Sleep Duration', unit: 'h',    color: '#60a5fa', formatValue: v => `${(v/60).toFixed(1)}h` },
  { key: 'deep_sleep',     label: 'Deep Sleep',     unit: 'h',    color: '#4f46e5', formatValue: v => `${(v/60).toFixed(1)}h` },
  { key: 'readiness',      label: 'Readiness',      unit: '',     color: '#2dd4bf' },
  { key: 'body_battery',   label: 'Body Battery',   unit: '',     color: '#facc15' },
  { key: 'training_load',  label: 'Training Load',  unit: '',     color: '#e879f9' },
]

const METRIC_BY_KEY = new Map(METRICS.map(m => [m.key, m]))

// Context sentences for each metric × direction
const TREND_CONTEXT: Record<string, { improving: string; declining: string; stable: string }> = {
  hrv:           { improving: 'A rising HRV signals your body is adapting well to training.', declining: 'Often coincides with elevated training load, poor sleep, or accumulated fatigue.', stable: 'Your autonomic nervous system is in a consistent state.' },
  recovery:      { improving: 'Your body is responding well to training and rest.', declining: 'Consider adding recovery activities or an extra rest day.', stable: 'Recovery is holding steady — maintain current training and sleep habits.' },
  resting_hr:    { improving: 'A falling resting HR indicates improving cardiovascular fitness.', declining: 'Rising resting HR often signals fatigue, illness, or insufficient recovery.', stable: 'Your cardiovascular baseline is consistent.' },
  strain:        { improving: 'Training load is building — keep an eye on recovery metrics.', declining: 'Load is tapering — expect recovery and HRV improvements to follow.', stable: 'Consistent training volume across the period.' },
  body_battery:  { improving: 'Energy reserves are rebuilding — good time to push training.', declining: 'Garmin is registering sustained energy depletion. Consider lighter days.', stable: 'Steady energy balance.' },
  sleep_duration:{ improving: 'More sleep is fuelling better recovery and performance.', declining: 'Short sleep is likely suppressing recovery scores and HRV.', stable: 'Consistent sleep schedule.' },
  deep_sleep:    { improving: 'More deep sleep means more physical restoration.', declining: 'Reduced deep sleep affects hormone release and muscle repair.', stable: 'Consistent deep sleep architecture.' },
  readiness:     { improving: 'Your body is in an increasingly good state to train hard.', declining: 'Fatigue is accumulating — pace yourself and prioritise recovery.', stable: 'Readiness is consistent with your recent training load.' },
  training_load: { improving: 'Load is building — ensure recovery metrics keep pace.', declining: 'A deload phase is underway — good for long-term adaptation.', stable: 'Steady training load.' },
}

// Anomaly display
const ANOMALY_COLORS: Record<string, string> = {
  'Recovery Score': '#34d399',
  'HRV':            '#818cf8',
  'Resting HR':     '#f87171',
  'Strain (Daily)': '#fb923c',
  'Body Battery':   '#facc15',
  'Sleep Duration': '#60a5fa',
  'Deep Sleep':     '#4f46e5',
}
const LOWER_IS_BETTER_ANOMALY = new Set(['Resting HR'])

function severityStyle(s: number): { label: string; bg: string; text: string; border: string } {
  if (s >= 3.5) return { label: 'Significant', bg: 'bg-poor/8',     text: 'text-poor',     border: 'border-poor/20' }
  if (s >= 2.5) return { label: 'Moderate',    bg: 'bg-moderate/8', text: 'text-moderate', border: 'border-moderate/20' }
  return              { label: 'Mild',         bg: 'bg-surface-overlay', text: 'text-slate-400', border: 'border-surface-border' }
}

/** Contextual one-liner for each anomaly without the enriched endpoint. */
function anomalyContext(metric: string, direction: string, value: number): string {
  const hi = direction === 'high'
  const ctx: Record<string, [string, string]> = {
    'Recovery Score': [`Recovery hit ${value.toFixed(0)}% — well above your baseline.`,           `Recovery dropped to ${value.toFixed(0)}% — well below your baseline.`],
    'HRV':            [`HRV spiked to ${value.toFixed(0)}ms — unusually high for you.`,            `HRV dipped to ${value.toFixed(0)}ms — may reflect accumulated fatigue.`],
    'Resting HR':     [`Resting HR reached ${value.toFixed(0)}bpm — elevated, often a sign of stress.`, `Resting HR dropped to ${value.toFixed(0)}bpm — unusually low for you.`],
    'Strain (Daily)': [`Strain hit ${value.toFixed(1)} — a very high training load day.`,           `Strain was only ${value.toFixed(1)} — unusually light activity.`],
    'Body Battery':   [`Body Battery peaked at ${value.toFixed(0)} — excellent energy reserves.`,   `Body Battery dropped to ${value.toFixed(0)} — below your typical baseline.`],
    'Sleep Duration': [`Sleep reached ${(value/60).toFixed(1)}h — well above your average.`,        `Sleep was only ${(value/60).toFixed(1)}h — significantly below your average.`],
    'Deep Sleep':     [`Deep sleep hit ${(value/60).toFixed(1)}h — more restorative than usual.`,   `Deep sleep was only ${(value/60).toFixed(1)}h — less restoration than typical.`],
  }
  const pair = ctx[metric]
  if (pair) return hi ? pair[0] : pair[1]
  return `${metric} was ${hi ? 'unusually high' : 'unusually low'} at ${value.toFixed(1)}.`
}

// ── activity colors (for scatter) ─────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  running:           '#60a5fa',
  strength_training: '#c084fc',
  cycling:           '#fb923c',
  walking:           '#22c55e',
  swimming:          '#2dd4bf',
  yoga:              '#f59e0b',
  hiit:              '#ef4444',
  pilates:           '#e879f9',
  indoor_cardio:     '#818cf8',
}
const FALLBACK_COLORS = ['#a78bfa', '#34d399', '#fbbf24', '#f87171', '#38bdf8']
function colorForType(type: string, allTypes: string[]): string {
  if (TYPE_COLORS[type]) return TYPE_COLORS[type]
  const idx = allTypes.filter(t => !TYPE_COLORS[t]).indexOf(type)
  return FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
}

// ── weekly digest ─────────────────────────────────────────────────────────────

interface DigestItem {
  category: string
  insight: string
  color: string
  icon: ReactNode
}

const Icons = {
  Heart: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
    </svg>
  ),
  Activity: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>
  ),
  Moon: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  ),
  Zap: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  ),
}

function buildDigest(s: WeeklySummary): DigestItem[] {
  const items: DigestItem[] = []
  const c = s.comparison ?? {}

  const pctStr = (pct: number | null | undefined, positiveIsGood = true): string => {
    if (pct === null || pct === undefined) return ''
    const sign = pct > 0 ? '+' : ''
    void positiveIsGood
    return ` (${sign}${pct.toFixed(0)}% vs last week)`
  }

  if (s.avg_recovery !== null) {
    const pct = c['avg_recovery'] as number | null | undefined
    const val = Math.round(s.avg_recovery)
    const qualifier = val >= 67 ? 'solid' : val >= 34 ? 'moderate' : 'low'
    items.push({
      category: 'Recovery',
      insight:  `Avg recovery ${val}% — ${qualifier}${pctStr(pct)}.`,
      color:    '#34d399',
      icon:     Icons.Heart,
    })
  }

  if (s.workout_count > 0) {
    const hours = s.total_training_minutes !== null
      ? ` · ${(s.total_training_minutes / 60).toFixed(1)}h training`
      : ''
    const pct = c['workout_count'] as number | null | undefined
    items.push({
      category: 'Training',
      insight:  `${s.workout_count} workout${s.workout_count !== 1 ? 's' : ''} this week${hours}${pctStr(pct)}.`,
      color:    '#fb923c',
      icon:     Icons.Activity,
    })
  }

  if (s.avg_sleep_duration !== null) {
    const hrs = (s.avg_sleep_duration / 60).toFixed(1)
    const pct = c['avg_sleep_duration'] as number | null | undefined
    items.push({
      category: 'Sleep',
      insight:  `Avg sleep ${hrs}h/night${pctStr(pct)}.`,
      color:    '#60a5fa',
      icon:     Icons.Moon,
    })
  }

  if (items.length < 3 && s.avg_hrv !== null) {
    const pct = c['avg_hrv'] as number | null | undefined
    items.push({
      category: 'HRV',
      insight:  `Avg HRV ${Math.round(s.avg_hrv)}ms this week${pctStr(pct)}.`,
      color:    '#818cf8',
      icon:     Icons.Zap,
    })
  }

  return items.slice(0, 3)
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

function DigestCard({ item }: { item: DigestItem }) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl px-4 py-3"
      style={{ background: 'var(--bg-card-elevated)', border: '0.5px solid var(--border-subtle)' }}
    >
      <div
        className="flex-shrink-0 mt-0.5 rounded-lg p-1.5"
        style={{ background: `${item.color}18`, color: item.color }}
      >
        {item.icon}
      </div>
      <div>
        <p className="text-2xs font-semibold uppercase tracking-wide mb-0.5" style={{ color: item.color }}>
          {item.category}
        </p>
        <p className="text-sm" style={{ color: 'var(--text-primary)', lineHeight: 1.45 }}>
          {item.insight}
        </p>
      </div>
    </div>
  )
}

function CorrCard({
  title, r, n, interpretation, children,
}: {
  title: string
  r: number | null
  n: number
  interpretation?: string
  children?: ReactNode
}) {
  const insufficient = r === null
  return (
    <div className="card space-y-3">
      <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</p>
      {insufficient ? (
        <p className="text-sm text-slate-400">
          Need {Math.max(0, 7 - n)} more day{Math.max(0, 7 - n) !== 1 ? 's' : ''} of paired data
        </p>
      ) : (
        <>
          {interpretation && (
            <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
              {interpretation}
            </p>
          )}
          <div className="flex items-center gap-2">
            {(() => {
              const abs = Math.abs(r!)
              const color = abs >= 0.5 ? (r! > 0 ? 'text-good' : 'text-poor')
                : abs >= 0.3 ? 'text-moderate'
                : 'text-slate-400'
              return (
                <span className={`text-xs font-semibold ${color}`}>
                  {corrStrength(r!).charAt(0).toUpperCase() + corrStrength(r!).slice(1)} correlation
                </span>
              )
            })()}
          </div>
          {children}
        </>
      )}
    </div>
  )
}

// ── page ───────────────────────────────────────────────────────────────────────

export function Insights() {
  const [selectedMetric, setSelectedMetric] = useState('recovery')
  const [explorerDays,   setExplorerDays]   = useState(60)

  const today   = toISO(new Date())
  const exStart = subDays(explorerDays)
  const exEnd   = today

  const summaryQ   = useWeeklySummary(today)
  const digestQ    = useWeeklyDigest(today)
  const trendQ     = useMetricTrend(selectedMetric, exStart, exEnd)
  const anomaliesQ = useAnomalies(exStart, exEnd)

  // Correlation source metrics
  const hrvQ      = useMetricTrend('hrv',           exStart, exEnd)
  const recoveryQ = useMetricTrend('recovery',       exStart, exEnd)
  const strainQ   = useMetricTrend('strain',         exStart, exEnd)
  const batteryQ  = useMetricTrend('body_battery',   exStart, exEnd)
  const sleepQ    = useMetricTrend('sleep_duration', exStart, exEnd)

  // Scatter data: workouts for strain ↔ next-day recovery
  const workoutsQ = useWorkouts(exStart, exEnd)

  const selectedCfg = METRIC_BY_KEY.get(selectedMetric) ?? METRICS[0]

  // Section 2: TrendChart data
  const trendData = useMemo((): TrendDataPoint[] => {
    const t = trendQ.data
    if (!t) return []
    const anomalyDates = new Set(t.anomalies.map(a => a.date))
    return t.dates.map((date, i) => ({
      date,
      value:     t.values[i],
      avg7d:     t.rolling_avg_7d[i],
      avg30d:    t.rolling_avg_30d[i],
      isAnomaly: anomalyDates.has(date),
    }))
  }, [trendQ.data])

  // Section 3: anomalies sorted desc, capped at 20
  const anomalies = useMemo(
    () => [...(anomaliesQ.data ?? [])].sort((a, b) => (b.date > a.date ? 1 : -1)).slice(0, 20),
    [anomaliesQ.data],
  )

  // Section 4: correlation computations
  const correlations = useMemo(() => {
    const hrv = hrvQ.data, rec = recoveryQ.data
    const str = strainQ.data, bat = batteryQ.data, slp = sleepQ.data

    const hrvRecovery = hrv && rec
      ? pearson(...Object.values(alignByDate(hrv.dates, hrv.values, rec.dates, rec.values)) as [(number|null)[], (number|null)[]])
      : null

    const strainNextRecovery = str && rec
      ? pearson(...Object.values(alignShifted(str.dates, str.values, rec.dates, rec.values, 1)) as [(number|null)[], (number|null)[]])
      : null

    const sleepBattery = slp && bat
      ? pearson(...Object.values(alignByDate(slp.dates, slp.values, bat.dates, bat.values)) as [(number|null)[], (number|null)[]])
      : null

    return { hrvRecovery, strainNextRecovery, sleepBattery }
  }, [hrvQ.data, recoveryQ.data, strainQ.data, batteryQ.data, sleepQ.data])

  // Scatter data: workouts with strain + next-day recovery, grouped by type
  const scatterData = useMemo(() => {
    const workouts = workoutsQ.data ?? []
    const allTypes = [...new Set(workouts.map(w => w.activity_type ?? 'unknown'))]
    const byType: Record<string, Array<{ x: number; y: number; type: string }>> = {}
    for (const w of workouts) {
      if (w.strain === null || w.next_day_recovery === null) continue
      const type = w.activity_type ?? 'unknown'
      if (type === 'unknown') continue
      if (!byType[type]) byType[type] = []
      byType[type].push({ x: w.strain, y: w.next_day_recovery, type })
    }
    return { byType, allTypes }
  }, [workoutsQ.data])

  const corrLoading = hrvQ.isLoading || recoveryQ.isLoading || strainQ.isLoading
    || batteryQ.isLoading || sleepQ.isLoading

  // Section 1: digest items — prefer server takeaways, fall back to client-side buildDigest
  const digestItems = useMemo(() => {
    const serverTakeaways = digestQ.data?.takeaways
    if (serverTakeaways && serverTakeaways.length > 0) {
      // Map server strings → DigestItem shape with auto-detected category
      return serverTakeaways.slice(0, 3).map((text): DigestItem => {
        const lower = text.toLowerCase()
        if (lower.includes('hrv') || lower.includes('recovery')) return { category: 'Recovery', insight: text, color: '#34d399', icon: Icons.Heart }
        if (lower.includes('train') || lower.includes('session') || lower.includes('strain') || lower.includes('acwr')) return { category: 'Training', insight: text, color: '#fb923c', icon: Icons.Activity }
        if (lower.includes('sleep')) return { category: 'Sleep', insight: text, color: '#60a5fa', icon: Icons.Moon }
        return { category: 'This Week', insight: text, color: '#818cf8', icon: Icons.Zap }
      })
    }
    return summaryQ.data ? buildDigest(summaryQ.data) : []
  }, [digestQ.data, summaryQ.data])

  // Trend badge context sentence
  const trendContext = useMemo(() => {
    const dir = trendQ.data?.trend_direction
    if (!dir || dir === 'insufficient_data') return null
    return TREND_CONTEXT[selectedMetric]?.[dir as keyof typeof TREND_CONTEXT[string]] ?? null
  }, [trendQ.data, selectedMetric])

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Insights</h1>

      {/* ── SECTION 1: Weekly Digest ─────────────────────────────────────────── */}
      <div className="card space-y-3">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">This Week</p>

        {digestQ.isLoading || summaryQ.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="skeleton h-14 w-full rounded-xl" />
            ))}
          </div>
        ) : digestItems.length === 0 ? (
          <p className="text-sm text-slate-400">No weekly summary available yet.</p>
        ) : (
          <div className="space-y-2">
            {digestItems.map((item, i) => <DigestCard key={i} item={item} />)}
          </div>
        )}
      </div>

      {/* ── SECTION 2: Metric Explorer ───────────────────────────────────────── */}
      <div className="card space-y-3">
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
            {trendQ.data && trendQ.data.trend_direction !== 'insufficient_data' && (
              <div className="space-y-1.5">
                {/* Trend direction badge */}
                {(() => {
                  const dir = trendQ.data.trend_direction
                  if (dir === 'stable') {
                    return (
                      <div className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold bg-moderate/10 border-moderate/30 text-moderate">
                        <span>→</span>
                        <span>{selectedCfg.label} is stable</span>
                      </div>
                    )
                  }
                  const improving = dir === 'improving'
                  // For lower-is-better metrics, "improving" means declining in value
                  const isGood = selectedCfg.lowerIsBetter ? !improving : improving
                  return (
                    <div className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${
                      isGood ? 'bg-good/10 border-good/30 text-good' : 'bg-poor/10 border-poor/30 text-poor'
                    }`}>
                      <span>{improving ? '↑' : '↓'}</span>
                      <span>{selectedCfg.label} is {dir}</span>
                    </div>
                  )
                })()}
                {/* Context sentence */}
                {trendContext && (
                  <p className="text-xs text-slate-500">{trendContext}</p>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── SECTION 4: Correlations ──────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="px-0.5">
          <p className="text-base font-bold text-slate-800 dark:text-slate-100">Correlations</p>
          <p className="text-2xs text-slate-500 mt-0.5">
            How your metrics relate — computed over the {explorerDays}-day window
          </p>
        </div>

        {corrLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="card">
                <div className="skeleton h-4 w-48 mb-2 rounded" />
                <div className="skeleton h-12 w-full rounded-xl" />
              </div>
            ))}
          </div>
        ) : (
          <>
            {/* HRV ↔ Recovery */}
            <CorrCard
              title="HRV ↔ Recovery"
              r={correlations.hrvRecovery?.r ?? null}
              n={correlations.hrvRecovery?.n ?? 0}
              interpretation={
                correlations.hrvRecovery?.r !== null
                  ? `When your HRV is high, recovery tends to follow — this is a ${corrStrength(correlations.hrvRecovery!.r!)} connection in your data.`
                  : undefined
              }
            />

            {/* Strain ↔ Next-Day Recovery (with scatter) */}
            <div className="card space-y-3">
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                Strain ↔ Next-Day Recovery
              </p>
              {correlations.strainNextRecovery === null || correlations.strainNextRecovery.r === null ? (
                <p className="text-sm text-slate-400">
                  {correlations.strainNextRecovery
                    ? `Need ${Math.max(0, 7 - correlations.strainNextRecovery.n)} more day${Math.max(0, 7 - correlations.strainNextRecovery.n) !== 1 ? 's' : ''} of paired data`
                    : 'Loading…'
                  }
                </p>
              ) : (
                <>
                  <p className="text-sm text-slate-600 dark:text-slate-300 leading-snug">
                    {correlations.strainNextRecovery.r > 0.2
                      ? `Higher-strain days tend to be followed by better recovery in your data — a ${corrStrength(correlations.strainNextRecovery.r)} relationship.`
                      : correlations.strainNextRecovery.r < -0.2
                      ? `Hard days tend to suppress next-day recovery in your data — a ${corrStrength(correlations.strainNextRecovery.r)} relationship.`
                      : `No clear link between strain and next-day recovery in your data yet.`
                    }
                  </p>
                  {(() => {
                    const r = correlations.strainNextRecovery.r
                    const abs = Math.abs(r)
                    const color = abs >= 0.5 ? (r > 0 ? 'text-good' : 'text-poor') : abs >= 0.3 ? 'text-moderate' : 'text-slate-400'
                    return (
                      <span className={`text-xs font-semibold ${color}`}>
                        {corrStrength(r).charAt(0).toUpperCase() + corrStrength(r).slice(1)} correlation
                      </span>
                    )
                  })()}
                  {/* Scatter plot */}
                  {Object.keys(scatterData.byType).length >= 1 && (
                    <>
                      <ResponsiveContainer width="100%" height={220}>
                        <ScatterChart margin={{ top: 4, right: 8, bottom: 24, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} />
                          <XAxis
                            dataKey="x"
                            type="number"
                            name="Strain"
                            label={{ value: 'Strain', position: 'insideBottom', offset: -12, fontSize: 10, fill: '#64748b' }}
                            tick={{ fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                          />
                          <YAxis
                            dataKey="y"
                            type="number"
                            name="Recovery"
                            tick={{ fontSize: 10 }}
                            tickLine={false}
                            axisLine={false}
                            width={36}
                            domain={[0, 100]}
                          />
                          <Tooltip
                            content={({ active, payload }) => {
                              if (!active || !payload?.length) return null
                              const d = payload[0].payload as { x: number; y: number; type: string }
                              return (
                                <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                                  <p className="font-medium text-slate-500">
                                    {(d.type).split('_').map((s: string) => s[0].toUpperCase() + s.slice(1)).join(' ')}
                                  </p>
                                  <p className="text-slate-400">Strain: <span className="font-mono font-semibold">{d.x.toFixed(1)}</span></p>
                                  <p className="text-slate-400">Next-day recovery: <span className="font-mono font-semibold">{d.y}%</span></p>
                                </div>
                              )
                            }}
                            cursor={{ strokeDasharray: '3 3' }}
                          />
                          {Object.keys(scatterData.byType).map(type => (
                            <Scatter
                              key={type}
                              name={type.split('_').map(s => s[0].toUpperCase() + s.slice(1)).join(' ')}
                              data={scatterData.byType[type]}
                              fill={colorForType(type, scatterData.allTypes)}
                              fillOpacity={0.75}
                              r={8}
                            />
                          ))}
                        </ScatterChart>
                      </ResponsiveContainer>
                      {Object.keys(scatterData.byType).length > 1 && (
                        <div className="flex flex-wrap gap-3">
                          {Object.keys(scatterData.byType).map(type => (
                            <span key={type} className="flex items-center gap-1.5 text-2xs text-slate-500 whitespace-nowrap">
                              <span className="inline-block h-2 w-2 rounded-full flex-shrink-0" style={{ backgroundColor: colorForType(type, scatterData.allTypes) }} />
                              {type.split('_').map(s => s[0].toUpperCase() + s.slice(1)).join(' ')}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </div>

            {/* Sleep Duration ↔ Body Battery */}
            <CorrCard
              title="Sleep Duration ↔ Body Battery"
              r={correlations.sleepBattery?.r ?? null}
              n={correlations.sleepBattery?.n ?? 0}
              interpretation={
                correlations.sleepBattery?.r !== null
                  ? `Longer sleep nights tend to ${correlations.sleepBattery!.r! >= 0.2 ? 'boost' : 'not clearly affect'} your next-day Garmin Body Battery — a ${corrStrength(correlations.sleepBattery!.r!)} connection.`
                  : undefined
              }
            />
          </>
        )}
      </div>

      {/* ── SECTION 5: Anomaly Feed ───────────────────────────────────────────── */}
      <div className="card space-y-3">
        <div>
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Anomaly Feed</p>
          <p className="text-2xs text-slate-500 mt-0.5">
            Days that deviated ≥2σ from your rolling baseline — sorted by date
          </p>
        </div>

        {anomaliesQ.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-16 rounded-xl" />
            ))}
          </div>
        ) : anomaliesQ.isError ? (
          <p className="text-sm text-slate-400">Could not load anomaly data.</p>
        ) : anomalies.length === 0 ? (
          <p className="text-sm text-slate-400">
            No anomalies in the last {explorerDays} days — your metrics are consistent.
          </p>
        ) : (
          <div className="space-y-2">
            {anomalies.map((a, i) => {
              const sty = severityStyle(a.severity)
              const dotColor = ANOMALY_COLORS[a.metric] ?? '#94a3b8'
              const isLIB    = LOWER_IS_BETTER_ANOMALY.has(a.metric)
              const isGood   = isLIB ? a.direction === 'low' : a.direction === 'high'
              return (
                <div
                  key={i}
                  className={`rounded-xl px-4 py-3 border ${sty.bg} ${sty.border}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className="h-2 w-2 rounded-full flex-shrink-0 mt-0.5"
                        style={{ backgroundColor: dotColor }}
                      />
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-slate-700 dark:text-slate-300 truncate">
                          {a.metric}
                          <span className={`ml-1.5 font-semibold ${isGood ? 'text-good' : 'text-poor'}`}>
                            {a.direction === 'high' ? '↑' : '↓'} {a.value.toFixed(1)}
                          </span>
                        </p>
                        <p className="text-xs text-slate-500 mt-0.5 leading-snug">
                          {anomalyContext(a.metric, a.direction, a.value)}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1 flex-shrink-0">
                      <span className="font-mono text-2xs text-slate-500">{fmtDate(a.date)}</span>
                      <span className={`text-2xs font-semibold ${sty.text}`}>{sty.label}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* ── SECTION 6: Future — LLM-powered personalized insights ─────────────── */}
      {/* TODO: When /api/insights/weekly-digest endpoint is available, render
          an AI-generated insight feed here. Each item will include a headline,
          supporting evidence from the user's data, and a recommended action.
          This section intentionally left empty for now. */}

    </div>
  )
}
