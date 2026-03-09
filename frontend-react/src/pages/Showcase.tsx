/**
 * Component showcase — visit /showcase to verify all components render correctly.
 * Delete this file after Task 4.2 sign-off.
 */
import { DataSourceBadge } from '../components/DataSourceBadge'
import { ErrorState } from '../components/ErrorState'
import {
  ChartSkeleton,
  MetricCardSkeleton,
  WorkoutRowSkeleton,
} from '../components/LoadingState'
import { MetricCard } from '../components/MetricCard'
import { SleepStageBar } from '../components/SleepStageBar'
import { StatusBadge } from '../components/StatusBadge'
import { TrendChart } from '../components/TrendChart'
import { WeekComparison } from '../components/WeekComparison'
import { WorkoutRow } from '../components/WorkoutRow'
import type { EnrichedWorkout } from '../types/api'

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const TREND_DATA = Array.from({ length: 30 }, (_, i) => {
  const base = 65 + Math.sin(i / 4) * 12
  const value = Math.round(base + (Math.random() - 0.5) * 8)
  return {
    date: new Date(Date.now() - (29 - i) * 86400000).toISOString().split('T')[0],
    value,
    avg7d: Math.round(base + 2),
    avg30d: Math.round(base - 1),
    isAnomaly: i === 10 || i === 22,
  }
})

const MOCK_WORKOUT: EnrichedWorkout = {
  id: 'w1',
  date: '2026-03-08',
  start_time: '2026-03-08T07:00:00Z',
  activity_type: 'running',
  duration_minutes: 52,
  primary_source: 'whoop',
  matched: true,
  strain: 14.2,
  avg_hr: 158,
  max_hr: 181,
  calories_kj: 1540,
  hr_zone_minutes: { zone1: 4, zone2: 12, zone3: 18, zone4: 14, zone5: 4 },
  distance_m: 9200,
  avg_pace_min_per_km: 5.65,
  elevation_gain_m: 95,
  avg_cadence: 174,
  avg_stride_length: 1.18,
  training_effect_aerobic: 3.8,
  training_effect_anaerobic: 1.4,
  training_load: 88,
  vo2_max: 53.2,
  avg_ground_contact_time_ms: 248,
  avg_vertical_oscillation_cm: 8.9,
  avg_vertical_ratio_pct: 7.6,
  strain_per_minute: 0.273,
  efficiency_score: 648,
  next_day_recovery: 74,
  recovery_impact: 6.2,
}

const MOCK_WORKOUT_STRENGTH: EnrichedWorkout = {
  ...MOCK_WORKOUT,
  id: 'w2',
  date: '2026-03-07',
  activity_type: 'strength_training',
  duration_minutes: 68,
  strain: 10.8,
  distance_m: null,
  avg_pace_min_per_km: null,
  avg_cadence: null,
  avg_ground_contact_time_ms: null,
  avg_vertical_oscillation_cm: null,
  avg_vertical_ratio_pct: null,
  recovery_impact: -3.1,
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xs font-bold uppercase tracking-widest text-slate-500 border-b border-surface-border pb-2">
        {title}
      </h2>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Showcase page
// ---------------------------------------------------------------------------

export function Showcase() {
  return (
    <div className="max-w-4xl mx-auto space-y-10 pb-16">
      <div>
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Component Showcase</h1>
        <p className="text-sm text-slate-400 mt-1">
          All components rendered with realistic mock data. Use the theme toggle (top right) to verify dark/light mode.
        </p>
      </div>

      {/* ── MetricCard ─────────────────────────────────────────────────── */}
      <Section title="MetricCard — status variants">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard
            label="Recovery Score"
            value={78}
            unit="%"
            delta={5.2}
            status="good"
          />
          <MetricCard
            label="HRV"
            value={62}
            unit=" ms"
            delta={-3.1}
            status="moderate"
          />
          <MetricCard
            label="Resting HR"
            value={58}
            unit=" bpm"
            delta={2.0}
            status="poor"
          />
          <MetricCard
            label="Body Battery"
            value={71}
            delta={null}
            status="neutral"
            subtext="Peaked at 88 yesterday"
          />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCard label="No Data" value={null} unit="%" status="neutral" />
          <MetricCard
            label="Sleep Duration"
            value="7h 42m"
            delta={-18}
            deltaLabel="vs 7d avg"
            status="moderate"
          />
          <MetricCard
            label="Daily Strain"
            value={15.4}
            delta={3.2}
            status="good"
            subtext="3 workouts"
          />
          <MetricCard
            label="Deep Sleep"
            value={94}
            unit=" min"
            delta={12}
            status="good"
          />
        </div>
      </Section>

      {/* ── StatusBadge ────────────────────────────────────────────────── */}
      <Section title="StatusBadge — all readiness levels">
        <div className="flex flex-wrap gap-3 items-center">
          <StatusBadge level="Push hard" score={88} size="lg" />
          <StatusBadge level="Train normally" score={72} size="lg" />
          <StatusBadge level="Go easy" score={51} size="lg" />
          <StatusBadge level="Rest day" score={28} size="lg" />
        </div>
        <div className="flex flex-wrap gap-3 items-center">
          <StatusBadge level="Push hard" score={88} size="md" />
          <StatusBadge level="Train normally" score={72} size="sm" />
        </div>
      </Section>

      {/* ── TrendChart ─────────────────────────────────────────────────── */}
      <Section title="TrendChart — with rolling averages and anomaly markers">
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">Recovery Score (30 days)</p>
          <TrendChart
            data={TREND_DATA}
            metricName="Recovery"
            unit="%"
            showRollingAvg
            height={220}
            color="#22c55e"
          />
          <p className="text-2xs text-slate-500 mt-2">
            Blue dots = raw · Orange = 7d avg · Dashed = 30d avg · Red dots = anomalies
          </p>
        </div>
        <div className="card">
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3">HRV — rolling averages hidden</p>
          <TrendChart
            data={TREND_DATA.map(d => ({ ...d, value: d.value !== null ? d.value * 0.9 : null }))}
            metricName="HRV"
            unit=" ms"
            showRollingAvg={false}
            height={160}
            color="#818cf8"
          />
        </div>
      </Section>

      {/* ── SleepStageBar ──────────────────────────────────────────────── */}
      <Section title="SleepStageBar — hover segments to highlight">
        <div className="card space-y-4">
          <div>
            <p className="text-xs text-slate-400 mb-2">Good night (7h 42m)</p>
            <SleepStageBar deepMinutes={94} lightMinutes={248} remMinutes={96} awakeMinutes={24} />
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-2">Short night (5h 10m)</p>
            <SleepStageBar deepMinutes={42} lightMinutes={168} remMinutes={58} awakeMinutes={42} />
          </div>
          <div>
            <p className="text-xs text-slate-400 mb-2">No data</p>
            <SleepStageBar deepMinutes={null} lightMinutes={null} remMinutes={null} awakeMinutes={null} />
          </div>
        </div>
      </Section>

      {/* ── DataSourceBadge ────────────────────────────────────────────── */}
      <Section title="DataSourceBadge">
        <div className="flex items-center gap-3">
          <DataSourceBadge source="whoop" size="xs" />
          <DataSourceBadge source="garmin" size="xs" />
          <DataSourceBadge source="both" size="xs" />
          <DataSourceBadge source="whoop" size="sm" />
          <DataSourceBadge source="garmin" size="sm" />
          <DataSourceBadge source="both" size="sm" />
        </div>
      </Section>

      {/* ── WorkoutRow ─────────────────────────────────────────────────── */}
      <Section title="WorkoutRow — click to expand">
        <div className="space-y-2">
          <WorkoutRow workout={MOCK_WORKOUT} />
          <WorkoutRow workout={MOCK_WORKOUT_STRENGTH} />
        </div>
      </Section>

      {/* ── WeekComparison ─────────────────────────────────────────────── */}
      <Section title="WeekComparison — week-over-week grid">
        <WeekComparison
          weekLabel="Week of Mar 3–9"
          prevWeekLabel="vs Feb 24–Mar 2"
          metrics={[
            { label: 'Readiness', value: '71', pctChange: 4.2 },
            { label: 'Recovery', value: '68%', pctChange: -3.1 },
            { label: 'Avg HRV', value: '61 ms', pctChange: 8.5 },
            { label: 'Total Strain', value: '87.4', pctChange: 12.0 },
            { label: 'Avg Sleep', value: '7.3 h', pctChange: -5.2 },
            { label: 'Workouts', value: '5', pctChange: 0.0 },
          ]}
        />
      </Section>

      {/* ── Loading states ─────────────────────────────────────────────── */}
      <Section title="Loading states — skeleton shimmer">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricCardSkeleton />
          <MetricCardSkeleton />
          <MetricCardSkeleton />
          <MetricCardSkeleton />
        </div>
        <ChartSkeleton height={180} />
        <div className="space-y-2">
          <WorkoutRowSkeleton />
          <WorkoutRowSkeleton />
        </div>
      </Section>

      {/* ── Error state ────────────────────────────────────────────────── */}
      <Section title="ErrorState">
        <div className="grid sm:grid-cols-2 gap-4">
          <ErrorState
            message="Could not reach the API. Make sure the backend is running on port 8000."
            onRetry={() => alert('retry clicked')}
          />
          <ErrorState message="No retry action (e.g. permanent data gap)." />
        </div>
      </Section>
    </div>
  )
}
