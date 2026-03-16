/**
 * API integration test page — exercises every hook against the live backend.
 * Visit /api-test to run all checks. Delete after sign-off.
 */
import {
  useAnomalies,
  useMetricTrend,
  useReadinessHistory,
  useReadinessToday,
  useSleepConsistency,
  useSleepCorrelations,
  useSleepInsights,
  useSyncStatus,
  useWeeklySummary,
  useWorkoutDetail,
  useWorkouts,
  useWorkoutSummary,
} from '../hooks/useApi'
import { useDateRange } from '../hooks/useDateRange'
import { useDateRangeContext } from '../context/DateRangeContext'
import { todayISO } from '../hooks/useDateRange'

// ── helpers ────────────────────────────────────────────────────────────────

type Status = 'loading' | 'ok' | 'error' | 'empty'

function Row({
  name,
  status,
  detail,
}: {
  name: string
  status: Status
  detail?: string
}) {
  const icon = { loading: '⏳', ok: '✅', error: '❌', empty: '⚠️' }[status]
  const color = {
    loading: 'text-slate-400',
    ok: 'text-good',
    error: 'text-poor',
    empty: 'text-moderate',
  }[status]

  return (
    <div className="flex items-start gap-3 py-2 border-b border-surface-border last:border-0">
      <span className="text-base w-5 flex-shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <span className="font-mono text-sm text-slate-700 dark:text-slate-200">{name}</span>
        {detail && (
          <p className={`text-xs mt-0.5 font-mono break-all ${color}`}>{detail}</p>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <p className="metric-label mb-3">{title}</p>
      {children}
    </div>
  )
}

function hookStatus<T>(
  isLoading: boolean,
  error: unknown,
  data: T | undefined,
  isEmpty?: (d: T) => boolean,
): { status: Status; detail: string } {
  if (isLoading) return { status: 'loading', detail: 'fetching…' }
  if (error) return { status: 'error', detail: String(error) }
  if (!data) return { status: 'error', detail: 'no data returned' }
  if (isEmpty?.(data)) return { status: 'empty', detail: 'returned empty — no data in DB?' }
  return { status: 'ok', detail: JSON.stringify(data).slice(0, 120) + '…' }
}

// ── test component ──────────────────────────────────────────────────────────

export function ApiTest() {
  const { start, end, days, setDays } = useDateRangeContext()
  const localRange = useDateRange(7)

  // Readiness
  const readinessToday = useReadinessToday()
  const readinessHistory = useReadinessHistory(start, end)

  // Workouts
  const workouts = useWorkouts(start, end)
  const firstWorkoutId = workouts.data?.[0]?.id ?? ''
  const workoutDetail = useWorkoutDetail(firstWorkoutId)
  const workoutSummary = useWorkoutSummary(start, end)

  // Sleep
  const sleepInsights = useSleepInsights(start, end)
  const sleepCorrelations = useSleepCorrelations(days)
  const sleepConsistency = useSleepConsistency(days)

  // Trends
  const metricTrend = useMetricTrend('recovery', start, end)
  const weeklySummary = useWeeklySummary(todayISO())
  const anomalies = useAnomalies(start, end)

  // Sync
  const syncStatus = useSyncStatus()
  const whoopSync = syncStatus.data?.find(s => s.source === 'whoop')
  const garminSync = syncStatus.data?.find(s => s.source === 'garmin')

  return (
    <div className="max-w-3xl mx-auto space-y-4 pb-16">
      <div className="mb-2">
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">API Hook Tests</h1>
        <p className="text-sm text-slate-500 mt-1">
          Live checks against the FastAPI backend. All hooks should show ✅.
        </p>
      </div>

      {/* Date range context */}
      <Section title="Date Range Context">
        <div className="space-y-1 text-sm font-mono">
          <p className="text-slate-600 dark:text-slate-400">
            Shared context: <span className="text-slate-800 dark:text-slate-200">{start} → {end}</span>{' '}
            <span className="text-slate-500">({days} days)</span>
          </p>
          <p className="text-slate-600 dark:text-slate-400">
            Local 7-day hook: <span className="text-slate-800 dark:text-slate-200">{localRange.start} → {localRange.end}</span>
          </p>
          <div className="flex gap-2 mt-2">
            {[7, 14, 30, 60].map(n => (
              <button
                key={n}
                onClick={() => setDays(n)}
                className={`px-2 py-1 rounded text-xs font-semibold transition-colors ${
                  days === n
                    ? 'bg-brand text-white'
                    : 'bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                }`}
              >
                {n}d
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Changing days above updates shared context → all date-dependent hooks below refetch.
          </p>
        </div>
      </Section>

      {/* Readiness */}
      <Section title="Readiness">
        <Row
          name="useReadinessToday()"
          {...hookStatus(readinessToday.isLoading, readinessToday.error, readinessToday.data, d =>
            d.score === undefined,
          )}
        />
        {readinessToday.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            score={readinessToday.data.score != null ? readinessToday.data.score.toFixed(1) : 'null'}, factors={Object.keys(readinessToday.data.contributing_factors).length}, confidence={readinessToday.data.confidence.toFixed(2)}
          </div>
        )}
        <Row
          name={`useReadinessHistory(${start}, ${end})`}
          {...hookStatus(readinessHistory.isLoading, readinessHistory.error, readinessHistory.data, d =>
            d.length === 0,
          )}
        />
        {readinessHistory.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            {readinessHistory.data.length} items, first has confidence={readinessHistory.data[0]?.confidence?.toFixed(2) ?? 'missing'}
          </div>
        )}
      </Section>

      {/* Workouts */}
      <Section title="Workouts">
        <Row
          name={`useWorkouts(${start}, ${end})`}
          {...hookStatus(workouts.isLoading, workouts.error, workouts.data, d => d.length === 0)}
        />
        {workouts.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            {workouts.data.length} workouts, types: {[...new Set(workouts.data.map(w => w.activity_type))].filter(Boolean).slice(0, 5).join(', ')}
          </div>
        )}
        <Row
          name={`useWorkoutDetail("${firstWorkoutId || 'none yet'}")`}
          {...(firstWorkoutId
            ? hookStatus(workoutDetail.isLoading, workoutDetail.error, workoutDetail.data)
            : { status: 'loading' as Status, detail: 'waiting for workouts to load first…' })}
        />
        <Row
          name={`useWorkoutSummary(${start}, ${end})`}
          {...hookStatus(workoutSummary.isLoading, workoutSummary.error, workoutSummary.data, d =>
            d.length === 0,
          )}
        />
        {workoutSummary.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            {workoutSummary.data.length} activity types: {workoutSummary.data.map(s => `${s.activity_type}(${s.count})`).join(', ')}
          </div>
        )}
      </Section>

      {/* Sleep */}
      <Section title="Sleep">
        <Row
          name={`useSleepInsights(${start}, ${end})`}
          {...hookStatus(sleepInsights.isLoading, sleepInsights.error, sleepInsights.data, d =>
            d.length === 0,
          )}
        />
        {sleepInsights.data?.[0] && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            First: deep_minutes={sleepInsights.data[0].deep_minutes?.toFixed(0)}, next_day_recovery_score={sleepInsights.data[0].next_day_recovery_score}, sleep_debt_estimate={sleepInsights.data[0].sleep_debt_estimate?.toFixed(0)}
          </div>
        )}
        <Row
          name={`useSleepCorrelations(${days})`}
          {...hookStatus(sleepCorrelations.isLoading, sleepCorrelations.error, sleepCorrelations.data)}
        />
        {sleepCorrelations.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            strain_vs_total: r={sleepCorrelations.data.strain_vs_total_sleep.r?.toFixed(3)}, sufficient={String(sleepCorrelations.data.strain_vs_total_sleep.sufficient_data)}, days_analyzed={sleepCorrelations.data.days_analyzed}
          </div>
        )}
        <Row
          name={`useSleepConsistency(${days})`}
          {...hookStatus(sleepConsistency.isLoading, sleepConsistency.error, sleepConsistency.data)}
        />
        {sleepConsistency.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            insufficient={String(sleepConsistency.data.insufficient_data)}, bedtime_std_hours={sleepConsistency.data.bedtime_std_hours}, sleep_debt_trend={sleepConsistency.data.sleep_debt_trend}
          </div>
        )}
      </Section>

      {/* Trends */}
      <Section title="Trends">
        <Row
          name={`useMetricTrend("recovery", ${start}, ${end})`}
          {...hookStatus(metricTrend.isLoading, metricTrend.error, metricTrend.data, d =>
            d.dates.length === 0,
          )}
        />
        {metricTrend.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            {metricTrend.data.dates.length} pts, has rolling_std_7d={String(Array.isArray(metricTrend.data.rolling_std_7d))}, trend={metricTrend.data.trend_direction}
          </div>
        )}
        <Row
          name="useWeeklySummary(today)"
          {...hookStatus(weeklySummary.isLoading, weeklySummary.error, weeklySummary.data)}
        />
        {weeklySummary.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            period={weeklySummary.data.period_start}→{weeklySummary.data.period_end}, avg_rhr={weeklySummary.data.avg_rhr?.toFixed(1)}, avg_deep={weeklySummary.data.avg_deep_sleep?.toFixed(0)}min
          </div>
        )}
        <Row
          name={`useAnomalies(${start}, ${end})`}
          {...hookStatus(anomalies.isLoading, anomalies.error, anomalies.data, d => d.length === 0)}
        />
        {anomalies.data && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            {anomalies.data.length} anomalies detected
          </div>
        )}
      </Section>

      {/* Sync */}
      <Section title="Sync Status">
        <Row
          name="useSyncStatus() — array shape"
          {...hookStatus(syncStatus.isLoading, syncStatus.error, syncStatus.data, d => d.length === 0)}
        />
        {whoopSync && (
          <div className="ml-8 mb-1 text-xs text-slate-500 font-mono">
            whoop: last_sync_at={whoopSync.last_sync_at?.slice(0, 19)}, status={whoopSync.status}
          </div>
        )}
        {garminSync && (
          <div className="ml-8 mb-2 text-xs text-slate-500 font-mono">
            garmin: last_sync_at={garminSync.last_sync_at?.slice(0, 19)}, status={garminSync.status}
          </div>
        )}
      </Section>

      {/* Stale time / caching */}
      <Section title="Caching Behaviour">
        <div className="text-xs font-mono space-y-1 text-slate-600 dark:text-slate-400">
          <p>Open DevTools → Network tab, then navigate away and back to this page.</p>
          <p>No new requests should fire within the stale window:</p>
          <div className="mt-2 space-y-0.5 text-slate-500">
            <p>readiness/today → 5 min stale + refetchOnWindowFocus</p>
            <p>readiness/history, workouts → 5 min stale</p>
            <p>sleep/*, trends/* → 15 min stale</p>
            <p>sync/status → 1 min stale + refetchOnWindowFocus</p>
          </div>
        </div>
      </Section>
    </div>
  )
}
