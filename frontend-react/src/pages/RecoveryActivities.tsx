/**
 * Recovery Activities page — Whoop recovery modalities and their impact on
 * next-day recovery, HRV, and sleep quality.
 */
import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { MetricCard } from '../components/MetricCard'
import { MetricCardSkeleton } from '../components/LoadingState'
import { ErrorState } from '../components/ErrorState'
import { useDateRangeContext } from '../context/DateRangeContext'
import { useRecovery, useRecoveryWithWithout } from '../hooks/useApi'
import type { RecoveryActivity } from '../types/api'

// ── constants ─────────────────────────────────────────────────────────────────

const TYPE_COLORS = [
  '#4472CA', '#70AD47', '#FFC000', '#FF7A00', '#DC143C', '#9467BD', '#8C564B',
]

// ── helpers ───────────────────────────────────────────────────────────────────

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

function DayButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
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

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-3">
      <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</p>
      {subtitle && <p className="text-2xs text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return <p className="text-sm text-slate-400 py-4 text-center">{message}</p>
}

// ── page ─────────────────────────────────────────────────────────────────────

export function RecoveryActivities() {
  const { days, setDays, start, end } = useDateRangeContext()

  const activitiesQ   = useRecovery(start, end)
  const withWithoutQ  = useRecoveryWithWithout(start, end)

  const activities = activitiesQ.data ?? []

  // All unique activity types (for color assignment)
  const allActivityTypes = useMemo(
    () => [...new Set(activities.map(a => a.activity))].sort(),
    [activities],
  )

  // Summary stats
  const summary = useMemo(() => {
    if (!activities.length) return null
    const counts: Record<string, number> = {}
    for (const a of activities) counts[a.activity] = (counts[a.activity] ?? 0) + 1
    const mostCommon = Object.entries(counts).sort((x, y) => y[1] - x[1])[0]?.[0] ?? '—'
    const validDur = activities.filter(a => a.dur_min !== null)
    const avgDur = validDur.length ? validDur.reduce((s, a) => s + (a.dur_min ?? 0), 0) / validDur.length : null
    const validRec = activities.filter(a => a.next_day_recovery !== null)
    const avgRec = validRec.length ? validRec.reduce((s, a) => s + (a.next_day_recovery ?? 0), 0) / validRec.length : null
    return { total: activities.length, mostCommon, avgDur, avgRec }
  }, [activities])

  // Weekly breakdown — pivot by week × activity type
  const weeklyData = useMemo((): Array<Record<string, unknown>> => {
    const byWeek = new Map<string, Record<string, unknown>>()
    for (const a of activities) {
      const wk = isoWeek(a.date)
      if (!byWeek.has(wk)) byWeek.set(wk, { week: wk })
      const entry = byWeek.get(wk)!
      entry[a.activity] = ((entry[a.activity] as number) ?? 0) + 1
    }
    return Array.from(byWeek.values()).sort((a, b) => (a.week as string) < (b.week as string) ? -1 : 1)
  }, [activities])

  // Duration over time (for scatter)
  const durScatterData = useMemo(() =>
    activities
      .filter(a => a.dur_min !== null)
      .map(a => ({ date: a.date, dur: a.dur_min!, activity: a.activity })),
    [activities],
  )

  // Duration vs next-day recovery scatter
  const durRecoveryData = useMemo(() =>
    activities
      .filter(a => a.dur_min !== null && a.next_day_recovery !== null)
      .map(a => ({ dur: a.dur_min!, recovery: a.next_day_recovery!, activity: a.activity, date: a.date })),
    [activities],
  )

  // Next-day recovery by activity type
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

  // Sleep performance by activity type
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

  if (activitiesQ.isError) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Recovery Activities</h1>
        <ErrorState
          message="Could not load recovery activities."
          onRetry={() => void activitiesQ.refetch()}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-16">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Recovery Activities</h1>
        <div className="flex gap-1.5">
          {[14, 30, 60, 90].map(n => (
            <DayButton key={n} n={n} active={days === n} onClick={() => setDays(n)} />
          ))}
        </div>
      </div>

      {/* ── SECTION 1: Summary ─────────────────────────────────────────────── */}
      {activitiesQ.isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => <MetricCardSkeleton key={i} />)}
        </div>
      ) : !summary ? (
        <div className="card text-center text-sm text-slate-400 py-8">
          No recovery activities found for this period.
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard label="Sessions" value={summary.total} status="neutral" />
          <MetricCard label="Most Common" value={summary.mostCommon} status="neutral" />
          <MetricCard
            label="Avg Duration"
            value={summary.avgDur !== null ? `${summary.avgDur.toFixed(0)}` : null}
            unit=" min"
            status="neutral"
          />
          <MetricCard
            label="Avg Next-Day Recovery"
            value={summary.avgRec !== null ? `${summary.avgRec.toFixed(0)}` : null}
            status="neutral"
          />
        </div>
      )}

      {/* Only render charts if we have data */}
      {!activitiesQ.isLoading && activities.length > 0 && (
        <>
          {/* ── SECTION 2: Weekly Session Breakdown ──────────────────────── */}
          <div className="card">
            <SectionHeader title="Weekly Session Breakdown" />
            {weeklyData.length === 0 ? (
              <EmptyState message="Not enough data" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={weeklyData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="week"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    angle={-20}
                    textAnchor="end"
                    height={36}
                  />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    content={({ active, payload, label }) => (
                      active && payload?.length ? (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{label}</p>
                          {payload.map((p, i) => (
                            <p key={i} className="text-slate-400" style={{ color: p.color }}>
                              {p.name}: <span className="font-mono font-semibold">{p.value}</span>
                            </p>
                          ))}
                        </div>
                      ) : null
                    )}
                  />
                  {allActivityTypes.map((act, i) => (
                    <Bar
                      key={act}
                      dataKey={act}
                      stackId="a"
                      fill={TYPE_COLORS[i % TYPE_COLORS.length]}
                      radius={i === allActivityTypes.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
            {/* Legend */}
            {allActivityTypes.length > 0 && (
              <div className="flex flex-wrap gap-3 mt-2">
                {allActivityTypes.map((act, i) => (
                  <span key={act} className="flex items-center gap-1.5 text-2xs text-slate-500">
                    <span
                      className="inline-block h-2 w-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: TYPE_COLORS[i % TYPE_COLORS.length] }}
                    />
                    {act}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* ── SECTION 3: Duration Over Time ──────────────────────────────── */}
          <div className="card">
            <SectionHeader title="Session Duration Over Time" />
            {durScatterData.length < 2 ? (
              <EmptyState message="Not enough data" />
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <ScatterChart margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    type="category"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={fmtDate}
                  />
                  <YAxis
                    dataKey="dur"
                    type="number"
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                    label={{ value: 'min', angle: -90, position: 'insideLeft', offset: 12, fontSize: 10, fill: '#64748b' }}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null
                      const d = payload[0].payload as { date: string; dur: number; activity: string }
                      return (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{fmtDate(d.date)}</p>
                          <p className="text-slate-400">{d.activity}</p>
                          <p className="text-slate-400">Duration: <span className="font-mono font-semibold">{d.dur.toFixed(0)} min</span></p>
                        </div>
                      )
                    }}
                    cursor={{ strokeDasharray: '3 3' }}
                  />
                  {allActivityTypes.map((act, i) => {
                    const pts = durScatterData.filter(d => d.activity === act)
                    return pts.length > 0 ? (
                      <Scatter
                        key={act}
                        name={act}
                        data={pts}
                        fill={TYPE_COLORS[i % TYPE_COLORS.length]}
                        fillOpacity={0.8}
                        r={5}
                      />
                    ) : null
                  })}
                </ScatterChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* ── SECTION 4: With vs Without Comparison ──────────────────────── */}
          <div className="card">
            <SectionHeader
              title="Next-Day Recovery: With vs Without Prior Recovery Activity"
              subtitle="Does doing a recovery activity the day before improve your next-day recovery score?"
            />
            {withWithoutQ.isLoading ? (
              <div className="grid grid-cols-2 gap-3">
                <MetricCardSkeleton />
                <MetricCardSkeleton />
              </div>
            ) : !withWithoutQ.data || (withWithoutQ.data.with_count === 0 && withWithoutQ.data.without_count === 0) ? (
              <EmptyState message="Not enough data to compare recovery vs non-recovery days." />
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
                      <p className="text-2xs text-slate-500">{d.with_count} days</p>
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
                      <p className="text-2xs text-slate-500">{d.without_count} days</p>
                    </div>
                  </div>
                  {diff !== null && (
                    <p className="text-xs text-slate-500">
                      Next-day recovery is{' '}
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

          {/* ── SECTION 5: Duration vs Next-Day Recovery ───────────────────── */}
          {durRecoveryData.length >= 3 && (
            <div className="card">
              <SectionHeader
                title="Duration vs Next-Day Recovery"
                subtitle="Each dot is one session. Look for an upward trend."
              />
              <ResponsiveContainer width="100%" height={240}>
                <ScatterChart margin={{ top: 4, right: 8, bottom: 12, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="dur"
                    type="number"
                    name="Duration"
                    label={{ value: 'Duration (min)', position: 'insideBottom', offset: -6, fontSize: 10, fill: '#64748b' }}
                    tick={{ fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    dataKey="recovery"
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
                      const d = payload[0].payload as { dur: number; recovery: number; activity: string; date: string }
                      return (
                        <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
                          <p className="font-medium text-slate-500">{fmtDate(d.date)}</p>
                          <p className="text-slate-400">{d.activity}</p>
                          <p className="text-slate-400">Duration: <span className="font-mono font-semibold">{d.dur.toFixed(0)} min</span></p>
                          <p className="text-slate-400">Next-day recovery: <span className="font-mono font-semibold">{d.recovery.toFixed(0)}</span></p>
                        </div>
                      )
                    }}
                    cursor={{ strokeDasharray: '3 3' }}
                  />
                  {allActivityTypes.map((act, i) => {
                    const pts = durRecoveryData.filter(d => d.activity === act)
                    return pts.length > 0 ? (
                      <Scatter
                        key={act}
                        name={act}
                        data={pts}
                        fill={TYPE_COLORS[i % TYPE_COLORS.length]}
                        fillOpacity={0.8}
                        r={5}
                      />
                    ) : null
                  })}
                </ScatterChart>
              </ResponsiveContainer>
              {/* Legend */}
              {allActivityTypes.length > 1 && (
                <div className="flex flex-wrap gap-3 mt-2">
                  {allActivityTypes.map((act, i) => (
                    <span key={act} className="flex items-center gap-1.5 text-2xs text-slate-500">
                      <span
                        className="inline-block h-2 w-2 rounded-full flex-shrink-0"
                        style={{ backgroundColor: TYPE_COLORS[i % TYPE_COLORS.length] }}
                      />
                      {act}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── SECTION 6: Next-Day Recovery by Activity Type ──────────────── */}
          {byTypeRecovery.length > 0 && (
            <div className="card">
              <SectionHeader
                title="Next-Day Recovery by Activity Type"
                subtitle="Average next-day recovery score following each activity type."
              />
              <ResponsiveContainer width="100%" height={Math.max(160, byTypeRecovery.length * 36)}>
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
                          <p className="text-slate-400">
                            Avg recovery: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)}</span>
                          </p>
                          <p className="text-slate-400">
                            Sessions: <span className="font-mono font-semibold">{(payload[0].payload as { n: number }).n}</span>
                          </p>
                        </div>
                      ) : null
                    )}
                  />
                  <Bar
                    dataKey="avg"
                    name="Avg Next-Day Recovery"
                    radius={[0, 3, 3, 0]}
                    fill="#4472CA"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── SECTION 7: Sleep Performance by Activity Type ──────────────── */}
          {byTypeSleep.length > 0 && (
            <div className="card">
              <SectionHeader
                title="Next-Day Sleep Performance by Activity Type"
                subtitle="Whoop sleep performance score on the night following each activity type."
              />
              <ResponsiveContainer width="100%" height={Math.max(160, byTypeSleep.length * 36)}>
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
                          <p className="text-slate-400">
                            Avg sleep perf: <span className="font-mono font-semibold">{(payload[0].value as number).toFixed(1)}%</span>
                          </p>
                          <p className="text-slate-400">
                            Sessions: <span className="font-mono font-semibold">{(payload[0].payload as { n: number }).n}</span>
                          </p>
                        </div>
                      ) : null
                    )}
                  />
                  <Bar
                    dataKey="avg"
                    name="Avg Sleep Performance"
                    radius={[0, 3, 3, 0]}
                    fill="#70AD47"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── SECTION 8: Activity Log ─────────────────────────────────────── */}
          <div className="card space-y-3">
            <SectionHeader title="Activity Log" />
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left border-b border-surface-border">
                    {['Date', 'Activity', 'Duration', 'Same-Day Recovery', 'Next-Day Recovery', 'Sleep %'].map(h => (
                      <th key={h} className="pb-2 pr-4 text-slate-500 font-medium whitespace-nowrap last:pr-0">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {activities.map((a: RecoveryActivity, i) => (
                    <tr key={i} className="border-b border-surface-border last:border-0 text-slate-600 dark:text-slate-400">
                      <td className="py-2 pr-4 font-mono text-slate-500 whitespace-nowrap">{fmtDate(a.date)}</td>
                      <td className="py-2 pr-4 font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap">{a.activity}</td>
                      <td className="py-2 pr-4 font-mono">{a.dur_min !== null ? `${a.dur_min.toFixed(0)} min` : '—'}</td>
                      <td className="py-2 pr-4 font-mono">{a.same_day_recovery !== null ? a.same_day_recovery.toFixed(0) : '—'}</td>
                      <td className="py-2 pr-4 font-mono font-semibold text-slate-700 dark:text-slate-300">
                        {a.next_day_recovery !== null ? a.next_day_recovery.toFixed(0) : '—'}
                      </td>
                      <td className="py-2 font-mono">
                        {a.next_day_sleep_perf !== null ? `${a.next_day_sleep_perf.toFixed(0)}%` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
