/**
 * Today — morning command center.
 * Answers: "How am I today, and what should I do?"
 *
 * Sections:
 *   1. Hero — ReadinessArcGauge + limiting factors (or all-clear)
 *   2. Last Night's Sleep — SleepStageBar + expandable detail
 *   3. Sparkline Row — HRV / Sleep / Strain (tap to expand 30d chart)
 *   4. Training Snapshot — ACWRGauge + last workout (expandable)
 *   5. 30-Day Readiness Trend — collapsed by default
 */

import { useMemo, useState } from 'react'
import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { ACWRGauge } from '../components/ACWRGauge'
import { LimitingFactorCard } from '../components/LimitingFactorCard'
import { ReadinessArcGauge } from '../components/ReadinessArcGauge'
import { SleepStageBar } from '../components/SleepStageBar'
import type { ReadinessLevel } from '../components/StatusBadge'
import { TrendChart } from '../components/TrendChart'
import { ConnectDevicesPanel } from '../components/ConnectDevicesPanel'
import { ExpandableSection, SectionLabel } from '../components/ExpandableSection'
import {
  useLimitingFactors,
  useMetricTrend,
  useReadinessHistory,
  useReadinessToday,
  useSleepInsights,
  useTrainingLoadRatio,
  useWorkouts,
} from '../hooks/useApi'
import { fmtDuration } from '../utils/formatters'
import { todayISO, useDateRange } from '../hooks/useDateRange'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const READINESS_LEVELS: ReadinessLevel[] = ['Push hard', 'Train normally', 'Go easy', 'Rest day']
function extractLevel(rec: string | undefined): ReadinessLevel | null {
  if (!rec) return null
  return READINESS_LEVELS.find(l => rec.startsWith(l)) ?? null
}

function stripFactorPrefix(explanation: string, factorName: string): string {
  if (explanation.startsWith(factorName)) {
    return explanation.slice(factorName.length).replace(/^[\s—\-:]+/, '')
  }
  return explanation
}

// Use shared formatter — import at top of file
// (local fmtDuration removed; using fmtDuration from utils/formatters)

function yesterdayISO(): string {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d.toLocaleDateString('en-CA')
}

function toCardSeverity(severity: string): 'alert' | 'caution' {
  return severity === 'poor' ? 'alert' : 'caution'
}

// ---------------------------------------------------------------------------
// Inline sparkline — full-width Recharts LineChart (no fixed-width hack).
// ---------------------------------------------------------------------------

interface MiniSparklineProps {
  data:   Array<{ value: number | null }>
  color?: string
  height?: number
}

function MiniSparkline({ data, color = 'var(--data-primary)', height = 40 }: MiniSparklineProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

// ---------------------------------------------------------------------------
// Today page
// ---------------------------------------------------------------------------

type SparklineKey = 'hrv' | 'sleep_duration' | 'daily_strain'

export function Today() {
  const today     = todayISO()
  const yesterday = yesterdayISO()
  const range30   = useDateRange(30)
  const range7    = useDateRange(7)
  const range3    = useDateRange(3)

  // ── Data ────────────────────────────────────────────────────────────────
  const readiness      = useReadinessToday()
  const limiters       = useLimitingFactors(2)
  const sleepData      = useSleepInsights(range3.start, today)
  const trainingLoad   = useTrainingLoadRatio()
  const recentWorkouts = useWorkouts(range7.start, range7.end)
  const readinessHist  = useReadinessHistory(range30.start, range30.end)
  const hrvTrend       = useMetricTrend('hrv',            range30.start, range30.end)
  const sleepTrend     = useMetricTrend('sleep_duration', range30.start, range30.end)
  const strainTrend    = useMetricTrend('daily_strain',   range30.start, range30.end)

  // ── UI state ──────────────────────────────────────────────────────────
  const [sleepOpen,        setSleepOpen]        = useState(false)
  const [trainingOpen,     setTrainingOpen]     = useState(false)
  const [trendOpen,        setTrendOpen]        = useState(false)
  const [expandedSparkline, setExpandedSparkline] = useState<SparklineKey | null>(null)

  // ── Derived ────────────────────────────────────────────────────────────
  const readinessData  = readiness.data
  const limitersList   = limiters.data ?? []
  const sleepArr       = (sleepData.data ?? []).filter(s => s.date <= yesterday)
  const lastSleep      = sleepArr[sleepArr.length - 1] ?? null
  const lastWorkout    = [...(recentWorkouts.data ?? [])]
    .sort((a, b) => b.date.localeCompare(a.date))[0] ?? null
  const recommendation = extractLevel(readinessData?.recommendation)

  const trendChartData = useMemo(() =>
    (readinessHist.data ?? []).map(p => ({
      date:      p.date,
      value:     p.score,
      avg7d:     null as number | null,
      avg30d:    null as number | null,
      isAnomaly: false,
    })),
    [readinessHist.data],
  )

  const SPARKLINES: Array<{
    key:       SparklineKey
    label:     string
    unit:      string
    toDisplay: (v: number) => string
    transform: (v: number) => number
    trend:     ReturnType<typeof useMetricTrend>
    color:     string
  }> = [
    {
      key:       'hrv',
      label:     'HRV',
      unit:      ' ms',
      toDisplay: v => `${Math.round(v)}`,
      transform: v => v,
      trend:     hrvTrend,
      color:     'var(--data-primary)',
    },
    {
      key:       'sleep_duration',
      label:     'Sleep',
      unit:      'h',
      toDisplay: v => (v / 60).toFixed(1),
      transform: v => v / 60,
      trend:     sleepTrend,
      color:     'var(--status-excellent)',
    },
    {
      key:       'daily_strain',
      label:     'Strain',
      unit:      '',
      toDisplay: v => v.toFixed(1),
      transform: v => v,
      trend:     strainTrend,
      color:     'var(--status-caution)',
    },
  ]

  // ---------------------------------------------------------------------------
  // Empty state — all main queries settled with no data
  const allSettled = readiness.isSuccess && sleepData.isSuccess && recentWorkouts.isSuccess
  const hasNoData  = allSettled && (readinessData?.confidence ?? 0) === 0 && sleepArr.length === 0
  if (hasNoData) {
    return (
      <div style={{ maxWidth: 480, margin: '48px auto', padding: '0 16px' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          {/* Abstract pulse / arc illustration */}
          <svg
            width="120" height="80" viewBox="0 0 120 80"
            fill="none" xmlns="http://www.w3.org/2000/svg"
            style={{ display: 'block', margin: '0 auto 24px' }}
            aria-hidden="true"
          >
            {/* Outer arc */}
            <path d="M10 60 A55 55 0 0 1 110 60" stroke="rgba(93,202,165,0.18)" strokeWidth="1.5" strokeLinecap="round" />
            {/* Middle arc */}
            <path d="M22 60 A43 43 0 0 1 98 60" stroke="rgba(93,202,165,0.30)" strokeWidth="1.5" strokeLinecap="round" />
            {/* Inner arc */}
            <path d="M34 60 A31 31 0 0 1 86 60" stroke="rgba(93,202,165,0.50)" strokeWidth="1.5" strokeLinecap="round" />
            {/* Pulse waveform */}
            <polyline
              points="15,60 30,60 36,40 42,72 48,52 54,60 66,60 72,35 78,72 84,55 90,60 105,60"
              stroke="var(--status-excellent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
              fill="none" opacity="0.7"
            />
            {/* Center dot */}
            <circle cx="60" cy="60" r="3" fill="var(--status-excellent)" opacity="0.9" />
          </svg>
          <p style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontSize: 26, fontWeight: 700,
            color: 'var(--text-primary)', marginBottom: 8,
          }}>
            Connect your devices
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6, maxWidth: 320, margin: '0 auto' }}>
            Link Whoop or Garmin to start seeing your personalised readiness dashboard.
          </p>
        </div>
        <ConnectDevicesPanel />
      </div>
    )
  }

  // Sparklines inner content
  const sparklineButtons = SPARKLINES.map(({ key, label, unit, toDisplay, transform, trend, color }) => {
    const data      = trend.data
    const allValues = data?.values.filter((v): v is number => v != null) ?? []
    const latest    = allValues.length > 0 ? allValues[allValues.length - 1] : undefined

    const prevValues = allValues.slice(-2)
    const arrowRaw   = prevValues.length === 2 ? prevValues[1] - prevValues[0] : 0
    const arrow      = Math.abs(arrowRaw) < 0.5 ? '→' : arrowRaw > 0 ? '↑' : '↓'
    const arrowColor = arrow === '→'
      ? 'var(--text-tertiary)'
      : arrow === '↑' ? 'var(--data-primary)' : 'var(--data-anomaly)'

    const chartData = (data?.values ?? []).map(v => ({
      value: v != null ? transform(v) : null,
    }))

    const isActive = expandedSparkline === key

    return (
      <button
        key={key}
        onClick={() => setExpandedSparkline(v => v === key ? null : key)}
        aria-pressed={isActive}
        aria-label={`${label} sparkline — ${latest != null ? toDisplay(latest) + unit : 'no data'}`}
        style={{
          background:   'var(--bg-card)',
          border:       isActive
            ? '0.5px solid var(--brand)'
            : '0.5px solid var(--border-subtle)',
          borderRadius: 10,
          padding:      '10px 10px 6px',
          cursor:       'pointer',
          textAlign:    'left',
          overflow:     'hidden',
          minWidth:     0,
          transition:   'border-color 150ms ease',
        }}
        className="focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50"
      >
        <p style={{ fontSize: 10, letterSpacing: '0.03em', color: 'var(--text-secondary)', marginBottom: 4 }}>
          {label}
        </p>

        {trend.isPending ? (
          <div className="skeleton" style={{ width: '60%', height: 20, borderRadius: 4, marginBottom: 6 }} />
        ) : latest != null ? (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 4 }}>
            <span
              style={{
                fontSize:           16,
                fontWeight:         700,
                color:              'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
                fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
              }}
            >
              {toDisplay(latest)}{unit}
            </span>
            <span style={{ fontSize: 11, color: arrowColor }}>{arrow}</span>
          </div>
        ) : (
          <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 4 }}>No data</p>
        )}

        {trend.isPending ? (
          <div className="skeleton" style={{ height: 40, borderRadius: 4 }} />
        ) : chartData.length > 0 ? (
          <MiniSparkline data={chartData} color={color} height={40} />
        ) : (
          <div style={{ height: 40 }} />
        )}
      </button>
    )
  })

  // Expanded sparkline card
  const expandedSparklineCard = expandedSparkline !== null ? (() => {
    const cfg       = SPARKLINES.find(s => s.key === expandedSparkline)!
    const data      = cfg.trend.data
    const chartData = data
      ? data.dates.map((d, i) => ({
          date:      d,
          value:     data.values[i] != null ? cfg.transform(data.values[i]!) : null,
          avg7d:     data.rolling_avg_7d[i] != null ? cfg.transform(data.rolling_avg_7d[i]!) : null,
          avg30d:    null as number | null,
          isAnomaly: data.anomalies.some(a => a.date === d),
        }))
      : []

    return (
      <div
        style={{
          background:   'var(--bg-card)',
          borderRadius: 12,
          border:       '0.5px solid var(--border-subtle)',
          padding:      '16px 16px 12px',
        }}
      >
        <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
          {cfg.label} — 30 days
        </p>
        <TrendChart
          data={chartData}
          metricName={cfg.label}
          unit={cfg.unit}
          showRollingAvg
          height={160}
          color={cfg.color}
        />
      </div>
    )
  })() : null

  // Sleep stage detail grid (shown when sleep section is expanded)
  const sleepDetailGrid = lastSleep ? (
    <div
      style={{
        display:             'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap:                 12,
      }}
    >
      {[
        { label: 'Deep',  value: fmtDuration(lastSleep.deep_minutes) },
        { label: 'REM',   value: fmtDuration(lastSleep.rem_minutes) },
        { label: 'Light', value: fmtDuration(lastSleep.light_minutes) },
        {
          label: 'Efficiency',
          value: lastSleep.sleep_efficiency != null
            ? `${Math.round(lastSleep.sleep_efficiency)}%`
            : '—',
        },
        {
          label: 'Sleep debt',
          value: lastSleep.sleep_debt_estimate != null
            ? fmtDuration(Math.abs(lastSleep.sleep_debt_estimate)) +
              (lastSleep.sleep_debt_estimate < 0 ? ' deficit' : ' surplus')
            : '—',
        },
      ].map(({ label, value }) => (
        <div key={label}>
          <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>{label}</p>
          <p style={{
            fontSize: 15,
            fontWeight: 600,
            color: 'var(--text-primary)',
            fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
            fontVariantNumeric: 'tabular-nums',
          }}>{value}</p>
        </div>
      ))}
    </div>
  ) : (
    <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>No sleep data for last night</p>
  )

  // Last workout detail (shown when training section is expanded)
  const lastWorkoutDetail = lastWorkout ? (
    <>
      <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>Last workout</p>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', textTransform: 'capitalize' }}>
            {(lastWorkout.activity_type ?? 'Workout').replace(/_/g, ' ')}
          </p>
          <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
            {lastWorkout.date}
            {lastWorkout.duration_minutes != null
              ? ` · ${Math.round(lastWorkout.duration_minutes)} min`
              : ''}
          </p>
        </div>
        {lastWorkout.strain != null && (
          <div style={{ textAlign: 'right' }}>
            <p style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Strain</p>
            <p style={{
              fontSize: 20, fontWeight: 700, color: 'var(--text-primary)',
              fontVariantNumeric: 'tabular-nums',
              fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
            }}>
              {lastWorkout.strain.toFixed(1)}
            </p>
          </div>
        )}
      </div>
      {trainingLoad.data?.confidence_note && (
        <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 10, fontStyle: 'italic' }}>
          {trainingLoad.data.confidence_note}
        </p>
      )}
    </>
  ) : (
    <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>No workouts in the last 7 days</p>
  )

  // Sleep header right-side content
  const sleepHeaderRight = lastSleep?.sleep_performance != null ? (
    <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
      {Math.round(lastSleep.sleep_performance)}% perf
    </span>
  ) : undefined

  // Sleep duration value
  const sleepValue = (
    <span
      style={{
        fontSize:           22,
        fontWeight:         700,
        color:              'var(--text-primary)',
        fontVariantNumeric: 'tabular-nums',
        fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
        display:            'block',
        marginTop:          2,
      }}
    >
      {sleepData.isPending
        ? <span className="skeleton" style={{ display: 'inline-block', width: 72, height: 28, borderRadius: 4 }} />
        : fmtDuration(lastSleep?.total_sleep_minutes ?? null)
      }
    </span>
  )

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

      {/* ── Left column: Hero ──────────────────────────────────────────── */}
      <div
        className="animate-fade-in"
        style={{
          background:   'var(--bg-card)',
          borderRadius: 18,
          border:       '0.5px solid var(--border-subtle)',
          padding:      '24px 20px 20px',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          {readiness.isPending ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
              <p style={{ fontSize: 11, letterSpacing: '0.06em', color: 'var(--text-tertiary)' }}>
                Morning Readiness
              </p>
              <div className="skeleton" style={{ width: 260, height: 160, borderRadius: 8 }} />
              <div className="skeleton" style={{ width: 80, height: 28, borderRadius: 6 }} />
            </div>
          ) : (
            <ReadinessArcGauge
              score={readinessData?.score ?? null}
              recommendation={recommendation}
              confidence={readinessData?.confidence ?? null}
            />
          )}

          <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {limiters.isPending ? (
              <>
                <div className="skeleton" style={{ height: 34, borderRadius: 6 }} />
                <div className="skeleton" style={{ height: 34, borderRadius: 6 }} />
              </>
            ) : limitersList.length === 0 ? (
              readiness.isSuccess ? (
                <p style={{ fontSize: 13, color: 'var(--status-excellent)', textAlign: 'center' }}>
                  All systems green — cleared to train
                </p>
              ) : null
            ) : (
              limitersList.map((lf, i) => (
                <LimitingFactorCard
                  key={i}
                  factorName={lf.factor_name}
                  context={stripFactorPrefix(lf.explanation, lf.factor_name)}
                  severity={toCardSeverity(lf.severity)}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* ── Right column: Sleep + Sparklines ───────────────────────────── */}
      <div className="flex flex-col gap-4 animate-fade-in delay-1">

        {/* Last Night's Sleep — using ExpandableSection */}
        <ExpandableSection
          label={
            <div>
              <SectionLabel>Last Night's Sleep</SectionLabel>
              {sleepValue}
            </div>
          }
          right={sleepHeaderRight}
          open={sleepOpen}
          onToggle={() => setSleepOpen(v => !v)}
          headerPadding="14px 16px 10px"
          bodyPadding="12px 16px 16px"
          preview={
            sleepData.isPending
              ? <div className="skeleton" style={{ height: 10, borderRadius: 5 }} />
              : <SleepStageBar
                  deepMinutes={lastSleep?.deep_minutes ?? null}
                  lightMinutes={lastSleep?.light_minutes ?? null}
                  remMinutes={lastSleep?.rem_minutes ?? null}
                  awakeMinutes={lastSleep?.awake_minutes ?? null}
                />
          }
        >
          {sleepDetailGrid}
        </ExpandableSection>

        {/* Sparkline row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {sparklineButtons}
        </div>

        {/* Expanded sparkline inline below sparklines */}
        {expandedSparklineCard}
      </div>

      {/* ── Training Snapshot — full width ─────────────────────────────── */}
      <div className="lg:col-span-2 animate-fade-in delay-2">
        <ExpandableSection
          label="Training Load"
          open={trainingOpen}
          onToggle={() => setTrainingOpen(v => !v)}
          preview={
            trainingLoad.isPending ? (
              <div style={{ padding: '0 0 16px' }}>
                <div className="skeleton" style={{ height: 20, borderRadius: 4, marginBottom: 8 }} />
                <div className="skeleton" style={{ height: 12, borderRadius: 6 }} />
              </div>
            ) : (
              <div style={{ paddingBottom: 16 }}>
                <ACWRGauge
                  acwr={trainingLoad.data?.acwr ?? null}
                  zone={trainingLoad.data?.zone ?? null}
                  zoneDescription={trainingLoad.data?.zone_description ?? null}
                />
              </div>
            )
          }
          bodyPadding="12px 16px 16px"
        >
          {lastWorkoutDetail}
        </ExpandableSection>
      </div>

      {/* ── 30-Day Readiness Trend — full width ────────────────────────── */}
      <div className="lg:col-span-2 animate-fade-in delay-3">
        <ExpandableSection
          label="30-Day Readiness Trend"
          open={trendOpen}
          onToggle={() => setTrendOpen(v => !v)}
        >
          {readinessHist.isPending ? (
            <div className="skeleton" style={{ height: 160, borderRadius: 6 }} />
          ) : (
            <TrendChart
              data={trendChartData}
              metricName="Readiness"
              unit=""
              showRollingAvg={false}
              height={160}
            />
          )}
        </ExpandableSection>
      </div>

    </div>
  )
}
