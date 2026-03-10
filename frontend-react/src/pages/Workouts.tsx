/**
 * Workout Analysis page — enriched Whoop + Garmin workout data.
 */
import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { WorkoutRow } from '../components/WorkoutRow'
import { MetricCard } from '../components/MetricCard'
import { ErrorState } from '../components/ErrorState'
import { MetricCardSkeleton, WorkoutRowSkeleton } from '../components/LoadingState'
import { useDateRangeContext } from '../context/DateRangeContext'
import { useWorkouts, useWorkoutSummary, useStrengthMaxWeight, useStrengthVolume } from '../hooks/useApi'
import type { EnrichedWorkout } from '../types/api'

// ── constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20
const KG_TO_LB = 2.20462

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

const FALLBACK_COLORS = [
  '#a78bfa', '#34d399', '#fbbf24', '#f87171', '#38bdf8', '#fb7185', '#4ade80',
]

const STRENGTH_TYPES = new Set([
  'strength_training', 'weight_training', 'indoor_cardio', 'hiit', 'pilates', 'yoga',
])

const TRACKED_EXERCISES: Record<string, string> = {
  BARBELL_DEADLIFT:             'Deadlift',
  STRAIGHT_LEG_DEADLIFT:        'Romanian DL',
  BARBELL_FRONT_SQUAT:          'Front Squat',
  BARBELL_SQUAT:                'Squat',
  INCLINE_DUMBBELL_BENCH_PRESS: 'Incline DB Press',
  BARBELL_BENCH_PRESS:          'Bench Press',
  LAT_PULLDOWN:                 'Lat Pulldown',
}

const EXERCISE_COLORS = ['#60a5fa', '#c084fc', '#34d399', '#fb923c', '#f87171', '#facc15', '#2dd4bf']

type DynField =
  | 'avg_cadence'
  | 'avg_vertical_ratio_pct'
  | 'avg_vertical_oscillation_cm'
  | 'avg_ground_contact_time_ms'
  | 'avg_stride_length'

interface DynMetricConfig {
  field: DynField
  label: string
  band: [number, number] | null
  caption: string | null
}

const DYN_METRICS: DynMetricConfig[] = [
  { field: 'avg_cadence',                  label: 'Cadence (spm)',           band: [170, 185], caption: 'Green band = optimal cadence zone (170–185 spm).' },
  { field: 'avg_vertical_ratio_pct',       label: 'Vertical Ratio (%)',      band: null, caption: 'Lower is better — less energy lost to vertical movement.' },
  { field: 'avg_vertical_oscillation_cm',  label: 'Vertical Oscillation (cm)', band: null, caption: 'Lower is better — less bounce means more forward propulsion.' },
  { field: 'avg_ground_contact_time_ms',   label: 'Ground Contact (ms)',     band: null, caption: 'Lower is better — shorter contact time indicates more elastic running.' },
  { field: 'avg_stride_length',            label: 'Stride Length (m)',       band: null, caption: null },
]

// ── helpers ──────────────────────────────────────────────────────────────────

function colorForType(type: string, allTypes: string[]): string {
  if (TYPE_COLORS[type]) return TYPE_COLORS[type]
  const idx = allTypes.filter(t => !TYPE_COLORS[t]).indexOf(type)
  return FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
}

function activityLabel(type: string): string {
  return type.split('_').map(s => s[0].toUpperCase() + s.slice(1)).join(' ')
}

function fmtNull(v: number | null, digits = 1, suffix = ''): string {
  return v !== null && v !== undefined ? `${v.toFixed(digits)}${suffix}` : '—'
}

function fmtDate(iso: string): string {
  return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function isoWeek(iso: string): string {
  const d = new Date(iso + 'T12:00:00')
  d.setDate(d.getDate() + 4 - (d.getDay() || 7))
  const yearStart = new Date(d.getFullYear(), 0, 1)
  const wk = Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
  return `${d.getFullYear()}-W${String(wk).padStart(2, '0')}`
}

// ── sub-components ────────────────────────────────────────────────────────────

function DayButton({
  n, active, onClick,
}: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
      }`}
    >
      {n}d
    </button>
  )
}

function SummarySkeletons() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
    </div>
  )
}

function SectionHeader({ title }: { title: string }) {
  return (
    <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">{title}</p>
  )
}

// Scatter chart tooltip (strain vs recovery)
function ScatterTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: { x: number; y: number; type: string } }>
}) {
  if (!active || !payload?.length) return null
  const { x, y, type } = payload[0].payload
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="font-medium text-slate-500">{activityLabel(type)}</p>
      <p className="text-slate-400">
        Strain: <span className="font-mono text-slate-200">{x.toFixed(1)}</span>
      </p>
      <p className="text-slate-400">
        Next-day recovery: <span className="font-mono text-slate-200">{y}%</span>
      </p>
    </div>
  )
}

// Common line chart tooltip
function LineTooltip({
  active, payload, label, yLabel, formatter,
}: {
  active?: boolean
  payload?: Array<{ value: number; color?: string; name?: string }>
  label?: string
  yLabel?: string
  formatter?: (v: number) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="font-medium text-slate-500">{label ? fmtDate(label) : ''}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-slate-400" style={{ color: p.color }}>
          {p.name ?? yLabel}: <span className="font-mono font-semibold">
            {formatter ? formatter(p.value) : p.value.toFixed(1)}
          </span>
        </p>
      ))}
    </div>
  )
}

function BarTooltip({
  active, payload, label,
}: {
  active?: boolean
  payload?: Array<{ value: number; name: string; color?: string }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="font-medium text-slate-500">{label ? fmtDate(label) : ''}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-slate-400">
          {p.name}: <span className="font-mono font-semibold" style={{ color: p.color }}>{p.value.toFixed(1)}</span>
        </p>
      ))}
    </div>
  )
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div
      className="flex items-center justify-center rounded-xl bg-surface-overlay text-sm text-slate-400"
      style={{ height: 200 }}
    >
      {message}
    </div>
  )
}

function ChartCaption({ text }: { text: string }) {
  return <p className="text-2xs text-slate-500 mt-1">{text}</p>
}

// ── page ─────────────────────────────────────────────────────────────────────

export function Workouts() {
  const { days, setDays, start, end } = useDateRangeContext()
  const [filterType, setFilterType] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [dynMetricIdx, setDynMetricIdx] = useState(0)

  const workoutsQ     = useWorkouts(start, end)
  const summaryQ      = useWorkoutSummary(start, end)
  const maxWeightQ    = useStrengthMaxWeight(start, end)
  const strengthVolQ  = useStrengthVolume(start, end)

  const workouts = workoutsQ.data ?? []

  // Summary stats
  const stats = useMemo(() => {
    if (!workouts.length) return null
    const withStrain = workouts.filter(w => w.strain !== null)
    const totalStrain = withStrain.reduce((s, w) => s + (w.strain ?? 0), 0)
    const totalMins = workouts.reduce((s, w) => s + (w.duration_minutes ?? 0), 0)
    return {
      count: workouts.length,
      totalStrain,
      totalHours: totalMins / 60,
      avgStrain: withStrain.length ? totalStrain / withStrain.length : null,
    }
  }, [workouts])

  // Filtered + paginated list (newest first)
  const filtered = useMemo(() => {
    const list = filterType ? workouts.filter(w => w.activity_type === filterType) : workouts
    return [...list].sort((a, b) => (b.date > a.date ? 1 : -1))
  }, [workouts, filterType])
  const visible = filtered.slice(0, visibleCount)

  // Scatter data grouped by type
  const allTypes = useMemo(() => [...new Set(workouts.map(w => w.activity_type ?? 'unknown'))], [workouts])
  const scatterByType = useMemo(() => {
    const result: Record<string, Array<{ x: number; y: number; type: string }>> = {}
    for (const w of workouts) {
      if (w.strain === null || w.next_day_recovery === null) continue
      const type = w.activity_type ?? 'unknown'
      if (type === 'unknown') continue
      if (!result[type]) result[type] = []
      result[type].push({ x: w.strain, y: w.next_day_recovery, type })
    }
    return result
  }, [workouts])
  const scatterTypes = Object.keys(scatterByType)
  const totalScatterPoints = scatterTypes.reduce((s, t) => s + scatterByType[t].length, 0)

  // Activity summary for breakdown table
  const summary = summaryQ.data ?? []
  const maxCount = summary[0]?.count ?? 1

  // ── Running data ─────────────────────────────────────────────────────────
  const runs = useMemo(
    () => workouts
      .filter(w => (w.activity_type ?? '').toLowerCase().includes('run'))
      .sort((a, b) => a.date < b.date ? -1 : 1),
    [workouts],
  )

  const weeklyVolume = useMemo(() => {
    const byWeek = new Map<string, { week: string; dist_km: number; time_h: number }>()
    for (const w of runs) {
      const wk = isoWeek(w.date)
      if (!byWeek.has(wk)) byWeek.set(wk, { week: wk, dist_km: 0, time_h: 0 })
      const entry = byWeek.get(wk)!
      if (w.distance_m) entry.dist_km += w.distance_m / 1000
      if (w.duration_minutes) entry.time_h += w.duration_minutes / 60
    }
    return Array.from(byWeek.values()).sort((a, b) => a.week < b.week ? -1 : 1)
  }, [runs])

  const selectedDyn = DYN_METRICS[dynMetricIdx]
  const dynData = useMemo(() =>
    runs
      .map(w => {
        const raw = w[selectedDyn.field as keyof EnrichedWorkout] as number | null
        // avg_stride_length is stored in cm — convert to metres for display
        const value = raw !== null && selectedDyn.field === 'avg_stride_length' ? raw / 100 : raw
        return { date: w.date, value }
      })
      .filter((r): r is { date: string; value: number } => r.value !== null),
    [runs, selectedDyn.field],
  )

  const paceCadenceData = useMemo(() =>
    runs
      .filter(w => w.avg_pace_min_per_km !== null && w.avg_cadence !== null)
      .map(w => ({ cadence: w.avg_cadence!, pace: w.avg_pace_min_per_km!, date: w.date })),
    [runs],
  )

  const trainingLoadData = useMemo(() =>
    runs.filter(w => w.training_load !== null).map(w => ({ date: w.date, load: w.training_load! })),
    [runs],
  )

  const vo2Data = useMemo(() =>
    runs.filter(w => w.vo2_max !== null).map(w => ({ date: w.date, vo2: w.vo2_max! })),
    [runs],
  )

  // ── Strength data ─────────────────────────────────────────────────────────
  const strengthWorkouts = useMemo(
    () => workouts
      .filter(w => STRENGTH_TYPES.has((w.activity_type ?? '').toLowerCase()))
      .sort((a, b) => a.date < b.date ? -1 : 1),
    [workouts],
  )

  const maxWeightPivot = useMemo(() => {
    const raw = maxWeightQ.data ?? []
    if (!raw.length) return { rows: [], exercises: [] as string[] }
    const pivot = new Map<string, Record<string, unknown>>()
    const exercises = new Set<string>()
    for (const r of raw) {
      const label = TRACKED_EXERCISES[r.exercise_name]
      if (!label) continue
      exercises.add(label)
      if (!pivot.has(r.date)) pivot.set(r.date, { date: r.date })
      pivot.get(r.date)![label] = r.max_weight_kg * KG_TO_LB
    }
    return {
      rows: Array.from(pivot.values()).sort((a, b) => (a.date as string) < (b.date as string) ? -1 : 1),
      exercises: Array.from(exercises),
    }
  }, [maxWeightQ.data])

  const volumeData = useMemo(() =>
    (strengthVolQ.data ?? []).map(r => ({ date: r.date, volume_lb: Math.round(r.total_volume_kg * KG_TO_LB) })),
    [strengthVolQ.data],
  )

  const strainDurData = useMemo(() =>
    strengthWorkouts
      .filter(w => w.strain !== null || w.duration_minutes !== null)
      .map(w => ({ date: w.date, strain: w.strain, duration: w.duration_minutes })),
    [strengthWorkouts],
  )

  // Error
  if (workoutsQ.isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Workouts</h1>
        <ErrorState
          message="Could not load workouts. Make sure the backend is running on port 8000."
          onRetry={() => void workoutsQ.refetch()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── SECTION 1: Date range + summary ──────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Workouts</h1>
          <div className="flex gap-1.5">
            {[7, 14, 30, 60].map(n => (
              <DayButton
                key={n}
                n={n}
                active={days === n}
                onClick={() => { setDays(n); setVisibleCount(PAGE_SIZE) }}
              />
            ))}
          </div>
        </div>

        {workoutsQ.isLoading ? (
          <SummarySkeletons />
        ) : stats ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard label="Workouts" value={stats.count} status="neutral" />
            <MetricCard
              label="Total Strain"
              value={stats.totalStrain.toFixed(1)}
              status="neutral"
            />
            <MetricCard
              label="Training Hours"
              value={stats.totalHours.toFixed(1)}
              unit="h"
              status="neutral"
            />
            <MetricCard
              label="Avg Strain"
              value={stats.avgStrain !== null ? stats.avgStrain.toFixed(1) : null}
              status="neutral"
            />
          </div>
        ) : null}
      </div>

      {/* ── SECTION 2: Activity type breakdown ───────────────────────────── */}
      {(summaryQ.isLoading || summary.length > 0) && (
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">
            Activity Breakdown
            {filterType && (
              <button
                onClick={() => setFilterType(null)}
                className="ml-2 text-xs font-normal text-brand hover:underline"
              >
                Clear filter ×
              </button>
            )}
          </p>

          {summaryQ.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="skeleton h-8 w-full rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="space-y-1">
              <div className="grid grid-cols-[1fr_36px_48px_48px] sm:grid-cols-[1fr_40px_56px_56px_56px] gap-2 px-2 pb-1 border-b border-surface-border">
                {['Type', 'Cnt', 'Strain', 'Dur'].map(h => (
                  <p key={h} className="metric-label text-right first:text-left">{h}</p>
                ))}
                <p className="metric-label text-right hidden sm:block">Effic</p>
              </div>

              {summary.map(row => {
                const color = colorForType(row.activity_type, allTypes)
                const isActive = filterType === row.activity_type
                return (
                  <button
                    key={row.activity_type}
                    onClick={() => {
                      setFilterType(prev => prev === row.activity_type ? null : row.activity_type)
                      setVisibleCount(PAGE_SIZE)
                    }}
                    className={`w-full grid grid-cols-[1fr_36px_48px_48px] sm:grid-cols-[1fr_40px_56px_56px_56px] gap-2 items-center px-2 py-1.5 rounded-lg transition-colors text-right ${
                      isActive ? 'bg-brand/10' : 'hover:bg-surface-overlay'
                    }`}
                  >
                    <div className="flex items-center gap-2 text-left min-w-0">
                      <div
                        className="h-1.5 flex-shrink-0 rounded-full"
                        style={{
                          width: `${Math.max(8, (row.count / maxCount) * 48)}px`,
                          backgroundColor: color,
                        }}
                      />
                      <span className="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">
                        {activityLabel(row.activity_type)}
                      </span>
                    </div>
                    <span className="font-mono text-xs text-slate-400">{row.count}</span>
                    <span className="font-mono text-xs text-slate-400">{fmtNull(row.avg_strain)}</span>
                    <span className="font-mono text-xs text-slate-400">
                      {row.avg_duration_minutes !== null ? `${Math.round(row.avg_duration_minutes)}m` : '—'}
                    </span>
                    <span className="font-mono text-xs text-slate-400 hidden sm:block">
                      {fmtNull(row.avg_efficiency_score, 0)}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── SECTION 3: Workout list ───────────────────────────────────────── */}
      <div>
        <p className="metric-label mb-2 px-0.5">
          {filterType ? `${activityLabel(filterType)} workouts` : 'All workouts'}
          {!workoutsQ.isLoading && (
            <span className="ml-1 normal-case font-normal text-slate-500">
              ({filtered.length})
            </span>
          )}
        </p>

        {workoutsQ.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => <WorkoutRowSkeleton key={i} />)}
          </div>
        ) : filtered.length === 0 ? (
          <div className="card text-center text-sm text-slate-400 py-8">
            No workouts in this period{filterType ? ` for ${activityLabel(filterType)}` : ''}.
          </div>
        ) : (
          <div className="space-y-2">
            {visible.map(w => <WorkoutRow key={w.id} workout={w} />)}
            {visibleCount < filtered.length && (
              <button
                onClick={() => setVisibleCount(c => c + PAGE_SIZE)}
                className="w-full py-2.5 rounded-xl border border-surface-border text-xs font-semibold text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-surface-overlay transition-colors"
              >
                Load more ({filtered.length - visibleCount} remaining)
              </button>
            )}
          </div>
        )}
      </div>

      {/* ── SECTION 4: Strain vs Recovery scatter ────────────────────────── */}
      {(workoutsQ.isLoading || totalScatterPoints >= 3) && (
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
            Strain vs Next-Day Recovery
          </p>
          <p className="text-2xs text-slate-500 mb-3">
            How your body responds to workout intensity
          </p>

          {workoutsQ.isLoading ? (
            <div className="skeleton rounded-xl" style={{ height: 220 }} />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart margin={{ top: 4, right: 8, bottom: 20, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="x"
                    type="number"
                    name="Strain"
                    label={{ value: 'Strain', position: 'insideBottom', offset: -8, fontSize: 10, fill: '#64748b' }}
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    name="Recovery"
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                    domain={[0, 100]}
                  />
                  <Tooltip content={<ScatterTooltip />} cursor={{ strokeDasharray: '3 3' }} />
                  {scatterTypes.map(type => (
                    <Scatter
                      key={type}
                      name={activityLabel(type)}
                      data={scatterByType[type]}
                      fill={colorForType(type, allTypes)}
                      fillOpacity={0.75}
                      r={8}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>

              {scatterTypes.length > 1 && (
                <div className="flex flex-wrap gap-3 mt-2">
                  {scatterTypes.map(type => (
                    <span key={type} className="flex items-center gap-1.5 text-2xs text-slate-500">
                      <span
                        className="inline-block h-2 w-2 rounded-full flex-shrink-0"
                        style={{ backgroundColor: colorForType(type, allTypes) }}
                      />
                      {activityLabel(type)}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── SECTION 5: Running ────────────────────────────────────────────── */}
      {!workoutsQ.isLoading && runs.length > 0 && (
        <div className="space-y-3">
          <p className="text-base font-bold text-slate-800 dark:text-slate-100 px-0.5">Running</p>

          {/* 5a. Weekly Volume */}
          <div className="card">
            <SectionHeader title="Weekly Volume" />
            {weeklyVolume.length < 1 ? (
              <EmptyChart message="Not enough data" />
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <p className="text-2xs text-slate-500 mb-1">Distance (km)</p>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={weeklyVolume} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="week" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                      <Tooltip
                        content={({ active, payload, label }) => (
                          active && payload?.length ? (
                            <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs">
                              <p className="font-medium text-slate-500">{label}</p>
                              <p className="text-slate-400">Distance: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)} km</span></p>
                            </div>
                          ) : null
                        )}
                      />
                      <Bar dataKey="dist_km" name="Distance (km)" fill="#4472CA" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div>
                  <p className="text-2xs text-slate-500 mb-1">Time on Foot (h)</p>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={weeklyVolume} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="week" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
                      <Tooltip
                        content={({ active, payload, label }) => (
                          active && payload?.length ? (
                            <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs">
                              <p className="font-medium text-slate-500">{label}</p>
                              <p className="text-slate-400">Time: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)} h</span></p>
                            </div>
                          ) : null
                        )}
                      />
                      <Bar dataKey="time_h" name="Time (h)" fill="#70AD47" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
            <ChartCaption text="Weekly totals across all runs in the selected period." />
          </div>

          {/* 5b. Running Dynamics Trend */}
          <div className="card">
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 mb-3">
              <SectionHeader title="Running Dynamics" />
              <select
                value={dynMetricIdx}
                onChange={e => setDynMetricIdx(Number(e.target.value))}
                className="text-xs rounded-lg border border-surface-border bg-surface-overlay px-2.5 py-1.5 text-slate-700 dark:text-slate-200 focus:outline-none cursor-pointer sm:ml-auto"
              >
                {DYN_METRICS.map((m, i) => (
                  <option key={m.field} value={i}>{m.label}</option>
                ))}
              </select>
            </div>

            {dynData.length < 2 ? (
              <EmptyChart message="Not enough running dynamics data in this period." />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={dynData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={fmtDate}
                  />
                  <YAxis
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    width={42}
                    domain={selectedDyn.band ? [Math.min(selectedDyn.band[0] - 10, 155), selectedDyn.band[1] + 10] : ['auto', 'auto']}
                  />
                  <Tooltip content={<LineTooltip yLabel={selectedDyn.label} />} />
                  {selectedDyn.band && (
                    <ReferenceArea
                      y1={selectedDyn.band[0]}
                      y2={selectedDyn.band[1]}
                      fill="#70AD47"
                      fillOpacity={0.12}
                      strokeOpacity={0}
                    />
                  )}
                  <Line
                    type="monotone"
                    dataKey="value"
                    name={selectedDyn.label}
                    stroke="#60a5fa"
                    dot={{ r: 3, fill: '#60a5fa' }}
                    activeDot={{ r: 5 }}
                    strokeWidth={2}
                    connectNulls={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            )}
            {selectedDyn.caption && <ChartCaption text={selectedDyn.caption} />}
          </div>

          {/* 5c. Pace vs Cadence */}
          {paceCadenceData.length >= 3 && (
            <div className="card">
              <SectionHeader title="Pace vs Cadence" />
              <ResponsiveContainer width="100%" height={240}>
                <ScatterChart margin={{ top: 4, right: 8, bottom: 12, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="cadence"
                    type="number"
                    name="Cadence"
                    label={{ value: 'Cadence (spm)', position: 'insideBottom', offset: -6, fontSize: 10, fill: '#64748b' }}
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    domain={['auto', 'auto']}
                  />
                  <YAxis
                    dataKey="pace"
                    type="number"
                    name="Pace"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                    domain={['auto', 'auto']}
                    tickFormatter={v => v.toFixed(1)}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null
                      const d = payload[0].payload as { cadence: number; pace: number; date: string }
                      return (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{fmtDate(d.date)}</p>
                          <p className="text-slate-400">Cadence: <span className="font-mono font-semibold">{d.cadence.toFixed(0)} spm</span></p>
                          <p className="text-slate-400">Pace: <span className="font-mono font-semibold">{d.pace.toFixed(2)} min/km</span></p>
                        </div>
                      )
                    }}
                    cursor={{ strokeDasharray: '3 3' }}
                  />
                  <Scatter data={paceCadenceData} fill="#4472CA" fillOpacity={0.75} r={8} />
                </ScatterChart>
              </ResponsiveContainer>
              <ChartCaption text="Higher cadence + lower pace value = faster, more efficient running." />
            </div>
          )}

          {/* 5d. Training Load */}
          {trainingLoadData.length >= 2 && (
            <div className="card">
              <SectionHeader title="Training Load Over Time" />
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={trainingLoadData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} />
                  <Tooltip content={<BarTooltip />} />
                  <Bar dataKey="load" name="Training Load" fill="#4472CA" fillOpacity={0.85} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <ChartCaption text="Garmin training load per run. Higher = more physiological stress." />
            </div>
          )}

          {/* 5e. VO2 Max Trend */}
          {vo2Data.length >= 2 && (
            <div className="card">
              <SectionHeader title="VO2 Max Trend" />
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={vo2Data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} domain={['auto', 'auto']} />
                  <Tooltip content={<LineTooltip yLabel="VO2 Max" formatter={v => `${v.toFixed(1)} mL/kg/min`} />} />
                  <Line
                    type="monotone"
                    dataKey="vo2"
                    name="VO2 Max"
                    stroke="#FFC000"
                    dot={{ r: 3, fill: '#FFC000' }}
                    activeDot={{ r: 5 }}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
              <ChartCaption text="Garmin estimated VO2 max. Upward trend indicates improving aerobic fitness." />
            </div>
          )}
        </div>
      )}

      {/* ── SECTION 6: Strength ───────────────────────────────────────────── */}
      {!workoutsQ.isLoading && strengthWorkouts.length > 0 && (
        <div className="space-y-3">
          <p className="text-base font-bold text-slate-800 dark:text-slate-100 px-0.5">Strength Training</p>

          {/* 6a. Max Weight Per Session */}
          <div className="card">
            <SectionHeader title="Max Weight Per Session" />
            {maxWeightQ.isLoading ? (
              <div className="skeleton rounded-xl" style={{ height: 200 }} />
            ) : maxWeightPivot.exercises.length === 0 ? (
              <EmptyChart message="No tracked exercise data — run a sync to fetch strength set details." />
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={maxWeightPivot.rows as Record<string, unknown>[]} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={v => fmtDate(v as string)}
                  />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={42} domain={['auto', 'auto']} />
                  <Tooltip
                    content={({ active, payload, label }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{fmtDate(label as string)}</p>
                          {payload.map((p, i) => (
                            <p key={i} className="text-slate-400" style={{ color: p.color }}>
                              {p.name}: <span className="font-mono font-semibold">{(p.value as number).toFixed(1)} lb</span>
                            </p>
                          ))}
                        </div>
                      ) : null
                    )}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                  {maxWeightPivot.exercises.map((ex, i) => (
                    <Line
                      key={ex}
                      type="monotone"
                      dataKey={ex}
                      stroke={EXERCISE_COLORS[i % EXERCISE_COLORS.length]}
                      dot={{ r: 3 }}
                      activeDot={{ r: 5 }}
                      strokeWidth={2}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
            <ChartCaption text="Max weight per session in lbs. Tracked exercises only." />
          </div>

          {/* 6b. Total Volume Per Session */}
          <div className="card">
            <SectionHeader title="Total Volume Per Session" />
            {strengthVolQ.isLoading ? (
              <div className="skeleton rounded-xl" style={{ height: 200 }} />
            ) : volumeData.length === 0 ? (
              <EmptyChart message="No volume data — run a sync to fetch strength set details." />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={volumeData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={52} tickFormatter={v => `${(v / 1000).toFixed(0)}k`} />
                  <Tooltip
                    content={({ active, payload, label }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs">
                          <p className="font-medium text-slate-500">{fmtDate(label as string)}</p>
                          <p className="text-slate-400">Volume: <span className="font-mono font-semibold">{(payload[0].value as number).toLocaleString()} lb</span></p>
                        </div>
                      ) : null
                    )}
                  />
                  <Bar dataKey="volume_lb" name="Volume (lb)" fill="#4472CA" fillOpacity={0.85} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
            <ChartCaption text="Total volume = sum of (weight × reps) across all sets in the session." />
          </div>

          {/* 6c. Strain & Duration Per Session */}
          {strainDurData.length > 0 && (
            <div className="card">
              <SectionHeader title="Strain & Duration Per Session" />
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={strainDurData} margin={{ top: 4, right: 28, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                  <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} />
                  <Tooltip
                    content={({ active, payload, label }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{fmtDate(label as string)}</p>
                          {payload.map((p, i) => (
                            p.value !== null && p.value !== undefined ? (
                              <p key={i} className="text-slate-400" style={{ color: p.color }}>
                                {p.name}: <span className="font-mono font-semibold">{(p.value as number).toFixed(1)}</span>
                              </p>
                            ) : null
                          ))}
                        </div>
                      ) : null
                    )}
                  />
                  <Bar yAxisId="left" dataKey="strain" name="Strain" fill="#FF7A00" fillOpacity={0.8} radius={[3, 3, 0, 0]} />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="duration"
                    name="Duration (min)"
                    stroke="#4472CA"
                    strokeDasharray="4 2"
                    dot={{ r: 3, fill: '#4472CA' }}
                    activeDot={{ r: 5 }}
                    strokeWidth={2}
                  />
                </ComposedChart>
              </ResponsiveContainer>
              <ChartCaption text="Bars = Whoop strain (left axis) · Dashed line = session duration in min (right axis)." />
            </div>
          )}
        </div>
      )}

    </div>
  )
}
