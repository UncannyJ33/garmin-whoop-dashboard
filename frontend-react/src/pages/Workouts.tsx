/**
 * Workout Analysis page — enriched Whoop + Garmin workout data.
 */
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
import { WorkoutRow } from '../components/WorkoutRow'
import { MetricCard } from '../components/MetricCard'
import { ErrorState } from '../components/ErrorState'
import { MetricCardSkeleton, WorkoutRowSkeleton } from '../components/LoadingState'
import { useDateRangeContext } from '../context/DateRangeContext'
import { useWorkouts, useWorkoutSummary } from '../hooks/useApi'

// ── constants ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20

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

// Scatter chart tooltip
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

// ── page ─────────────────────────────────────────────────────────────────────

export function Workouts() {
  const { days, setDays, start, end } = useDateRangeContext()
  const [filterType, setFilterType] = useState<string | null>(null)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  const workoutsQ = useWorkouts(start, end)
  const summaryQ  = useWorkoutSummary(start, end)

  // Reset pagination when date range or filter changes
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

  // Filtered + paginated list
  const filtered = useMemo(
    () => filterType ? workouts.filter(w => w.activity_type === filterType) : workouts,
    [workouts, filterType],
  )
  const visible = filtered.slice(0, visibleCount)

  // Scatter data grouped by type
  const allTypes = useMemo(() => [...new Set(workouts.map(w => w.activity_type ?? 'unknown'))], [workouts])
  const scatterByType = useMemo(() => {
    const result: Record<string, Array<{ x: number; y: number; type: string }>> = {}
    for (const w of workouts) {
      if (w.strain === null || w.next_day_recovery === null) continue
      const type = w.activity_type ?? 'unknown'
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
              {/* Header */}
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
                    {/* Type + bar */}
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
                <ScatterChart margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="x"
                    type="number"
                    name="Strain"
                    label={{ value: 'Strain', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#64748b' }}
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
                      r={5}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>

              {/* Legend */}
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

    </div>
  )
}
