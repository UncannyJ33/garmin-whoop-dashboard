/**
 * Training page — replaces /workouts.
 *
 * Sections:
 *   1. Training Load Summary  — ACWRGauge + Workouts + Hours cards
 *   2. Running Analytics      — Cadence+GCT dual-line by default, Advanced toggle
 *   3. Strength               — PRs table (prominent), Volume, Strain+Duration
 *   4. Activity Breakdown     — clickable table, type-specific metric column
 *   5. Workout Log            — WorkoutRow list with recovery-impact gutter indicator
 */
import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
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
import { ACWRGauge } from '../components/ACWRGauge'
import { ErrorState } from '../components/ErrorState'
import { MetricCardSkeleton, NoDataState, WorkoutRowSkeleton } from '../components/LoadingState'
import { useDateRangeContext } from '../context/DateRangeContext'
import {
  useWorkouts,
  useWorkoutSummary,
  useStrengthMaxWeight,
  useStrengthVolume,
  useTrainingLoadRatio,
} from '../hooks/useApi'
import type { EnrichedWorkout, WorkoutTypeSummary } from '../types/api'
import { activityLabel } from '../utils/formatters'
import { colorForType } from '../utils/chartColors'

// ── constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20
const KG_TO_LB  = 2.20462

const STRENGTH_TYPES = new Set([
  'strength_training', 'weight_training', 'indoor_cardio', 'hiit', 'pilates', 'yoga',
])

// Activity types that have meaningful distance metrics
const DISTANCE_TYPES = new Set([
  'running', 'cycling', 'walking', 'hiking', 'trail_running',
  'road_cycling', 'mountain_biking', 'open_water_swimming', 'swimming',
])

const TRACKED_EXERCISES: Record<string, string> = {
  BARBELL_BACK_SQUAT:           'Back Squat',
  WEIGHTED_SQUAT:               'Back Squat',
  BARBELL_FRONT_SQUAT:          'Front Squat',
  OVERHEAD_BARBELL_PRESS:       'OHP',
  BARBELL_BENCH_PRESS:          'Bench Press',
  INCLINE_DUMBBELL_BENCH_PRESS: 'Incline Press',
  BARBELL_DEADLIFT:             'Deadlift',
  ROMANIAN_DEADLIFT:            'Romanian DL',
}

const EXERCISE_ORDER = ['Back Squat', 'Front Squat', 'OHP', 'Bench Press', 'Incline Press', 'Deadlift', 'Romanian DL']

// ── helpers ──────────────────────────────────────────────────────────────────

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

/** Type-specific metric for the activity breakdown table.
 *  Distance sports: strain/km — higher = more intense per km.
 */
function typeMetric(row: WorkoutTypeSummary): string {
  const type = row.activity_type.toLowerCase()
  const isDistance = DISTANCE_TYPES.has(type) || type.includes('run') || type.includes('cycl') || type.includes('hike') || type.includes('walk')
  if (isDistance && row.avg_distance_m !== null && row.avg_distance_m > 0 && row.avg_strain !== null) {
    const strainPerKm = row.avg_strain / (row.avg_distance_m / 1000)
    return `${strainPerKm.toFixed(2)}/km`
  }
  return '—'
}

/** Recovery-impact gutter indicator: green ↑ / red ↓ / gray – */
function RecoveryIndicator({ impact }: { impact: number | null }) {
  if (impact === null) {
    return (
      <span style={{ color: 'var(--text-tertiary)', fontSize: 13, lineHeight: 1 }}>–</span>
    )
  }
  if (impact > 2) {
    return (
      <span style={{ color: 'var(--status-excellent)', fontSize: 13, fontWeight: 600, lineHeight: 1 }}>↑</span>
    )
  }
  if (impact < -2) {
    return (
      <span style={{ color: 'var(--status-alert)', fontSize: 13, fontWeight: 600, lineHeight: 1 }}>↓</span>
    )
  }
  return (
    <span style={{ color: 'var(--text-tertiary)', fontSize: 13, lineHeight: 1 }}>–</span>
  )
}

// ── sub-components ────────────────────────────────────────────────────────────

function DayButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
      }`}
    >
      {n}d
    </button>
  )
}

function SectionHeader({ title, size = 'sm' }: { title: string; size?: 'sm' | 'base' }) {
  if (size === 'base') {
    return (
      <p className="text-base font-bold text-slate-800 dark:text-slate-100 mb-3">{title}</p>
    )
  }
  return (
    <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">{title}</p>
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

// ── page ─────────────────────────────────────────────────────────────────────

export function Training() {
  const { days, setDays, start, end } = useDateRangeContext()
  const [filterType, setFilterType]       = useState<string | null>(null)
  const [visibleCount, setVisibleCount]   = useState(PAGE_SIZE)
  const [advancedDyn, setAdvancedDyn]     = useState(false)
  const [dynMetricIdx, setDynMetricIdx]   = useState(0)

  const workoutsQ    = useWorkouts(start, end)
  const summaryQ     = useWorkoutSummary(start, end)
  const maxWeightQ   = useStrengthMaxWeight(start, end)
  const strengthVolQ = useStrengthVolume(start, end)
  const trainingLoadQ = useTrainingLoadRatio()

  const workouts = workoutsQ.data ?? []

  // Summary stats for header cards
  const stats = useMemo(() => {
    if (!workouts.length) return null
    const totalMins = workouts.reduce((s, w) => s + (w.duration_minutes ?? 0), 0)
    return {
      count:      workouts.length,
      totalHours: totalMins / 60,
    }
  }, [workouts])

  // Filtered + paginated list (newest first)
  const filtered = useMemo(() => {
    const list = filterType ? workouts.filter(w => w.activity_type === filterType) : workouts
    return [...list].sort((a, b) => (b.date > a.date ? 1 : -1))
  }, [workouts, filterType])
  const visible = filtered.slice(0, visibleCount)

  // Activity summary
  const summary  = summaryQ.data ?? []
  const maxCount = summary[0]?.count ?? 1
  const allTypes = useMemo(() => [...new Set(workouts.map(w => w.activity_type ?? 'unknown'))], [workouts])

  // ── Running data ───────────────────────────────────────────────────────────
  const runs = useMemo(
    () => workouts
      .filter(w => (w.activity_type ?? '').toLowerCase().includes('run'))
      .sort((a, b) => (a.date < b.date ? -1 : 1)),
    [workouts],
  )

  const weeklyVolume = useMemo(() => {
    const byWeek = new Map<string, { week: string; dist_km: number; time_h: number }>()
    for (const w of runs) {
      const wk = isoWeek(w.date)
      if (!byWeek.has(wk)) byWeek.set(wk, { week: wk, dist_km: 0, time_h: 0 })
      const entry = byWeek.get(wk)!
      if (w.distance_m)       entry.dist_km += w.distance_m / 1000
      if (w.duration_minutes) entry.time_h  += w.duration_minutes / 60
    }
    return Array.from(byWeek.values()).sort((a, b) => (a.week < b.week ? -1 : 1))
  }, [runs])

  // Default dynamics: Cadence + Ground Contact Time (dual Y-axis)
  const dynDualData = useMemo(() =>
    runs
      .map(w => ({
        date:    w.date,
        cadence: w.avg_cadence,
        gct:     w.avg_ground_contact_time_ms,
      }))
      .filter(r => r.cadence !== null || r.gct !== null),
    [runs],
  )

  // Advanced dynamics metric options (vert osc / vert ratio / stride length)
  const ADVANCED_METRICS = [
    { field: 'avg_vertical_oscillation_cm' as keyof EnrichedWorkout, label: 'Vertical Oscillation (cm)', caption: 'Lower is better — less bounce means more forward propulsion.' },
    { field: 'avg_vertical_ratio_pct'      as keyof EnrichedWorkout, label: 'Vertical Ratio (%)',        caption: 'Lower is better — less energy lost to vertical movement.' },
    { field: 'avg_stride_length'           as keyof EnrichedWorkout, label: 'Stride Length (m)',         caption: null },
  ]
  const selectedAdv = ADVANCED_METRICS[dynMetricIdx]
  const dynAdvData = useMemo(() =>
    runs
      .map(w => {
        const raw = w[selectedAdv.field] as number | null
        const value = raw !== null && selectedAdv.field === 'avg_stride_length' ? raw / 100 : raw
        return { date: w.date, value }
      })
      .filter((r): r is { date: string; value: number } => r.value !== null),
    [runs, selectedAdv.field],
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

  // ── Strength data ──────────────────────────────────────────────────────────
  const strengthWorkouts = useMemo(
    () => workouts
      .filter(w => STRENGTH_TYPES.has((w.activity_type ?? '').toLowerCase()))
      .sort((a, b) => (a.date < b.date ? -1 : 1)),
    [workouts],
  )

  const strengthProgression = useMemo(() => {
    const raw = maxWeightQ.data ?? []
    const byExercise = new Map<string, { date: string; weight_lb: number }[]>()
    for (const r of raw) {
      const label = TRACKED_EXERCISES[r.exercise_name]
      if (!label) continue
      if (!byExercise.has(label)) byExercise.set(label, [])
      byExercise.get(label)!.push({ date: r.date, weight_lb: r.max_weight_kg * KG_TO_LB })
    }
    return EXERCISE_ORDER
      .filter(ex => byExercise.has(ex))
      .map(ex => {
        const entries = byExercise.get(ex)!.sort((a, b) => (a.date < b.date ? -1 : 1))
        return { exercise: ex, entries: entries.slice(-4) }
      })
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
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Training</h1>
        <ErrorState
          message="Could not load workouts. Make sure the backend is running on port 8000."
          onRetry={() => void workoutsQ.refetch()}
        />
      </div>
    )
  }

  if (workoutsQ.isSuccess && workouts.length === 0 && !summaryQ.isLoading) {
    return <NoDataState message="No workouts found for this period. Connect Garmin or Whoop to start tracking." />
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── HEADER: date range selector ───────────────────────────────────── */}
      <div className="flex items-center justify-between animate-fade-in">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Training</h1>
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

      {/* ── SECTION 1: Training Load Summary ─────────────────────────────── */}
      <div className="card space-y-4 animate-fade-in delay-1">
        <SectionHeader title="Training Load" />

        {/* ACWRGauge — full width */}
        {trainingLoadQ.isPending ? (
          <div className="space-y-2">
            <div className="skeleton h-5 w-20 rounded" />
            <div className="skeleton h-3 w-full rounded-full" />
            <div className="skeleton h-4 w-full rounded" />
          </div>
        ) : trainingLoadQ.data ? (
          <ACWRGauge
            acwr={trainingLoadQ.data.acwr}
            zone={trainingLoadQ.data.zone}
            zoneDescription={trainingLoadQ.data.zone_description}
          />
        ) : (
          <p className="text-sm text-slate-400">Not enough data to compute training load.</p>
        )}

        {/* 2-card row: Workouts + Training Hours */}
        <div className="grid grid-cols-2 gap-3">
          {workoutsQ.isPending ? (
            <>
              <MetricCardSkeleton />
              <MetricCardSkeleton />
            </>
          ) : stats ? (
            <>
              <MetricCard label="Workouts" value={stats.count} status="neutral" />
              <MetricCard label="Training Hours" value={stats.totalHours.toFixed(1)} unit="h" status="neutral" />
            </>
          ) : null}
        </div>
      </div>

      {/* ── SECTION 4: Running Analytics ─────────────────────────────────── */}
      {!workoutsQ.isLoading && runs.length > 0 && (
        <div className="space-y-3">
          <p className="text-base font-bold text-slate-800 dark:text-slate-100 px-0.5">Running</p>

          {/* 4a. Weekly Volume */}
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
                              <p className="font-medium text-slate-500">{label as string}</p>
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
                              <p className="font-medium text-slate-500">{label as string}</p>
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

          {/* 4b. Running Dynamics — Cadence + GCT dual-line (default), Advanced toggle */}
          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <SectionHeader title="Running Dynamics" />
              <button
                onClick={() => setAdvancedDyn(v => !v)}
                className={`text-xs font-medium px-2.5 py-1 rounded-lg border transition-colors ${
                  advancedDyn
                    ? 'border-brand text-brand bg-brand/10'
                    : 'border-surface-border text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                }`}
              >
                Advanced
              </button>
            </div>

            {advancedDyn ? (
              /* Advanced: single metric dropdown */
              <>
                <div className="mb-3">
                  <select
                    value={dynMetricIdx}
                    onChange={e => setDynMetricIdx(Number(e.target.value))}
                    className="text-xs rounded-lg border border-surface-border bg-surface-overlay px-2.5 py-1.5 text-slate-700 dark:text-slate-200 focus:outline-none cursor-pointer"
                  >
                    {ADVANCED_METRICS.map((m, i) => (
                      <option key={m.field} value={i}>{m.label}</option>
                    ))}
                  </select>
                </div>
                {dynAdvData.length < 2 ? (
                  <EmptyChart message="Not enough data for this metric in the selected period." />
                ) : (
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={dynAdvData} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                      <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={42} domain={['auto', 'auto']} />
                      <Tooltip content={<LineTooltip yLabel={selectedAdv.label} />} />
                      <Line
                        type="monotone"
                        dataKey="value"
                        name={selectedAdv.label}
                        stroke="#60a5fa"
                        dot={{ r: 3, fill: '#60a5fa' }}
                        activeDot={{ r: 5 }}
                        strokeWidth={2}
                        connectNulls={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
                {selectedAdv.caption && <ChartCaption text={selectedAdv.caption} />}
              </>
            ) : (
              /* Default: Cadence + Ground Contact Time */
              <>
                {dynDualData.length < 2 ? (
                  <EmptyChart message="Not enough running dynamics data in this period." />
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={240}>
                      <ComposedChart data={dynDualData} margin={{ top: 4, right: 36, bottom: 0, left: -8 }}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                        <YAxis
                          yAxisId="cadence"
                          tick={{ fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          width={42}
                          domain={[150, 200]}
                          label={{ value: 'spm', angle: -90, position: 'insideLeft', offset: 8, fontSize: 9, fill: '#64748b' }}
                        />
                        <YAxis
                          yAxisId="gct"
                          orientation="right"
                          tick={{ fontSize: 10 }}
                          tickLine={false}
                          axisLine={false}
                          width={36}
                          domain={['auto', 'auto']}
                          label={{ value: 'ms', angle: 90, position: 'insideRight', offset: 4, fontSize: 9, fill: '#64748b' }}
                        />
                        <Tooltip
                          content={({ active, payload, label }) => {
                            if (!active || !payload?.length) return null
                            return (
                              <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                                <p className="font-medium text-slate-500">{fmtDate(label as string)}</p>
                                {payload.map((p, i) => (
                                  p.value !== null && p.value !== undefined ? (
                                    <p key={i} className="text-slate-400" style={{ color: p.color }}>
                                      {p.name}: <span className="font-mono font-semibold">{Number(p.value).toFixed(0)}</span>
                                    </p>
                                  ) : null
                                ))}
                              </div>
                            )
                          }}
                        />
                        <ReferenceArea yAxisId="cadence" y1={170} y2={185} fill="#70AD47" fillOpacity={0.10} strokeOpacity={0} />
                        <Line
                          yAxisId="cadence"
                          type="monotone"
                          dataKey="cadence"
                          name="Cadence (spm)"
                          stroke="#60a5fa"
                          dot={{ r: 3, fill: '#60a5fa' }}
                          activeDot={{ r: 5 }}
                          strokeWidth={2}
                          connectNulls={false}
                        />
                        <Line
                          yAxisId="gct"
                          type="monotone"
                          dataKey="gct"
                          name="Ground Contact (ms)"
                          stroke="#f97316"
                          dot={{ r: 3, fill: '#f97316' }}
                          activeDot={{ r: 5 }}
                          strokeWidth={2}
                          strokeDasharray="4 2"
                          connectNulls={false}
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                    <div className="flex gap-4 mt-1.5">
                      <span className="flex items-center gap-1.5 text-2xs text-slate-500">
                        <span className="inline-block h-0.5 w-4 rounded" style={{ background: '#60a5fa' }} />
                        Cadence (spm)
                      </span>
                      <span className="flex items-center gap-1.5 text-2xs text-slate-500">
                        <span className="inline-block h-0.5 w-4 rounded" style={{ background: '#f97316', opacity: 0.85 }} />
                        Ground Contact (ms)
                      </span>
                    </div>
                    <ChartCaption text="Green band = optimal cadence zone (170–185 spm). Lower ground contact = more elastic running." />
                  </>
                )}
              </>
            )}
          </div>

          {/* 4c. Pace vs Cadence */}
          {paceCadenceData.length >= 3 && (
            <div className="card">
              <SectionHeader title="Pace vs Cadence" />
              <ResponsiveContainer width="100%" height={240}>
                <ScatterChart margin={{ top: 4, right: 8, bottom: 12, left: 0 }}>
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

          {/* 4d. Training Load */}
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

          {/* 4e. VO2 Max Trend */}
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

      {/* ── SECTION 5: Strength ───────────────────────────────────────────── */}
      {!workoutsQ.isLoading && strengthWorkouts.length > 0 && (
        <div className="space-y-3">
          <p className="text-base font-bold text-slate-800 dark:text-slate-100 px-0.5">Strength Training</p>

          {/* 5a. Strength PRs — most prominent */}
          <div className="card">
            <p className="text-base font-bold text-slate-800 dark:text-slate-100 mb-3">Strength PRs</p>
            {maxWeightQ.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton h-10 rounded-lg" />)}
              </div>
            ) : strengthProgression.length === 0 ? (
              <EmptyChart message="No tracked exercise data — run a sync to fetch strength set details." />
            ) : (
              <table className="w-full text-xs">
                <tbody>
                  {strengthProgression.map(({ exercise, entries }) => {
                    const latest = entries[entries.length - 1]
                    const prev   = entries[entries.length - 2]
                    const delta  = latest && prev ? latest.weight_lb - prev.weight_lb : null
                    return (
                      <tr key={exercise} className="border-b border-surface-border last:border-0">
                        <td className="py-3 pr-4 font-semibold text-slate-700 dark:text-slate-200 whitespace-nowrap w-28">
                          {exercise}
                        </td>
                        <td className="py-3">
                          <div className="flex items-center gap-3 flex-wrap">
                            {entries.map((e, i) => (
                              <span key={i} className="flex flex-col items-center gap-0.5">
                                <span
                                  className={`font-mono font-bold ${i === entries.length - 1 ? 'text-base text-slate-100' : 'text-sm text-slate-400'}`}
                                >
                                  {e.weight_lb.toFixed(0)} lb
                                </span>
                                <span className="text-2xs text-slate-500">{fmtDate(e.date)}</span>
                              </span>
                            ))}
                            {delta !== null && (
                              <span className={`text-sm font-bold ml-1 ${delta > 0 ? 'text-good' : delta < 0 ? 'text-poor' : 'text-slate-400'}`}>
                                {delta > 0 ? `+${delta.toFixed(0)}` : delta.toFixed(0)} lb
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            <ChartCaption text="Last 4 sessions per exercise. Delta = change from previous session." />
          </div>

          {/* 5b. Total Volume Per Session */}
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

          {/* 5c. Strain & Duration Per Session */}
          {strainDurData.length > 0 && (
            <div className="card">
              <SectionHeader title="Strain & Duration Per Session" />
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={strainDurData} margin={{ top: 4, right: 28, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                  <YAxis yAxisId="left"  tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} />
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
                  <Bar  yAxisId="left"  dataKey="strain"   name="Strain"         fill="#FF7A00" fillOpacity={0.8} radius={[3, 3, 0, 0]} />
                  <Line yAxisId="right" dataKey="duration" name="Duration (min)"
                    type="monotone" stroke="#4472CA" strokeDasharray="4 2"
                    dot={{ r: 3, fill: '#4472CA' }} activeDot={{ r: 5 }} strokeWidth={2}
                  />
                </ComposedChart>
              </ResponsiveContainer>
              <ChartCaption text="Bars = Whoop strain (left axis) · Dashed line = session duration in min (right axis)." />
            </div>
          )}
        </div>
      )}

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
              <div className="grid grid-cols-[1fr_36px_48px_48px] sm:grid-cols-[1fr_40px_56px_56px_64px] gap-2 px-2 pb-1 border-b border-surface-border">
                {['Type', 'Cnt', 'Strain', 'Dur'].map(h => (
                  <p key={h} className="metric-label text-right first:text-left">{h}</p>
                ))}
                <p className="metric-label text-right hidden sm:block">Str/km</p>
              </div>

              {summary.map(row => {
                const color    = colorForType(row.activity_type, allTypes)
                const isActive = filterType === row.activity_type
                return (
                  <button
                    key={row.activity_type}
                    onClick={() => {
                      setFilterType(prev => prev === row.activity_type ? null : row.activity_type)
                      setVisibleCount(PAGE_SIZE)
                    }}
                    className={`w-full grid grid-cols-[1fr_36px_48px_48px] sm:grid-cols-[1fr_40px_56px_56px_64px] gap-2 items-center px-2 py-2.5 rounded-lg transition-colors text-right focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
                      isActive ? 'bg-brand/10' : 'hover:bg-surface-overlay'
                    }`}
                  >
                    <div className="flex items-center gap-2 text-left min-w-0">
                      <div
                        className="h-1.5 flex-shrink-0 rounded-full"
                        style={{
                          width:           `${Math.max(8, (row.count / maxCount) * 48)}px`,
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
                      {typeMetric(row)}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ── SECTION 3: Workout Log ────────────────────────────────────────── */}
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
            {visible.map(w => (
              /* Left-gutter recovery-impact indicator */
              <div key={w.id} className="flex items-start gap-1.5">
                <div
                  className="flex items-center justify-center flex-shrink-0 pt-3.5"
                  style={{ width: 16 }}
                  title={
                    w.recovery_impact !== null
                      ? `Recovery impact: ${w.recovery_impact > 0 ? '+' : ''}${w.recovery_impact.toFixed(1)}`
                      : 'No recovery data'
                  }
                >
                  <RecoveryIndicator impact={w.recovery_impact} />
                </div>
                <div className="flex-1 min-w-0">
                  <WorkoutRow workout={w} />
                </div>
              </div>
            ))}
            {visibleCount < filtered.length && (
              <button
                onClick={() => setVisibleCount(c => c + PAGE_SIZE)}
                className="w-full py-3 rounded-xl border border-surface-border text-xs font-semibold text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-surface-overlay transition-colors"
              >
                Load more ({filtered.length - visibleCount} remaining)
              </button>
            )}
          </div>
        )}
      </div>

    </div>
  )
}
