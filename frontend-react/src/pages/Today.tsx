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

import { useState } from 'react'
import { ACWRGauge } from '../components/ACWRGauge'
import { LimitingFactorCard } from '../components/LimitingFactorCard'
import { ReadinessArcGauge } from '../components/ReadinessArcGauge'
import { SleepStageBar } from '../components/SleepStageBar'
import type { ReadinessLevel } from '../components/StatusBadge'
import { TrendChart } from '../components/TrendChart'
import {
  useLimitingFactors,
  useMetricTrend,
  useReadinessHistory,
  useReadinessToday,
  useSleepInsights,
  useTrainingLoadRatio,
  useWorkouts,
} from '../hooks/useApi'
import { todayISO, useDateRange } from '../hooks/useDateRange'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDuration(minutes: number | null): string {
  if (minutes == null) return '—'
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function yesterdayISO(): string {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  return d.toLocaleDateString('en-CA')
}

function toCardSeverity(severity: string): 'alert' | 'caution' {
  return severity === 'poor' ? 'alert' : 'caution'
}

// Section wrapper — card with consistent styling
function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div
      style={{
        background:   'var(--bg-card)',
        borderRadius: 12,
        border:       '0.5px solid var(--border-subtle)',
        overflow:     'hidden',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

// Chevron icon (rotates when expanded)
function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      style={{
        color:     'var(--text-tertiary)',
        transform: open ? 'rotate(180deg)' : 'none',
        transition:'transform 200ms ease',
        flexShrink: 0,
      }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Section label
// ---------------------------------------------------------------------------
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        fontSize:      11,
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        color:         'var(--text-tertiary)',
        fontWeight:    500,
      }}
    >
      {children}
    </span>
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
  const range3    = useDateRange(3) // for last night's sleep

  // ── Data ────────────────────────────────────────────────────────────────
  const readiness       = useReadinessToday()
  const limiters        = useLimitingFactors(2)
  const sleepData       = useSleepInsights(range3.start, today)
  const trainingLoad    = useTrainingLoadRatio()
  const recentWorkouts  = useWorkouts(range7.start, range7.end)
  const readinessHist   = useReadinessHistory(range30.start, range30.end)

  const hrvTrend        = useMetricTrend('hrv',            range30.start, range30.end)
  const sleepTrend      = useMetricTrend('sleep_duration', range30.start, range30.end)
  const strainTrend     = useMetricTrend('daily_strain',   range30.start, range30.end)

  // ── UI state ─────────────────────────────────────────────────────────────
  const [sleepExpanded,    setSleepExpanded]    = useState(false)
  const [trainingExpanded, setTrainingExpanded] = useState(false)
  const [trendExpanded,    setTrendExpanded]    = useState(false)
  const [expandedSparkline, setExpandedSparkline] = useState<SparklineKey | null>(null)

  // ── Derived ──────────────────────────────────────────────────────────────
  const readinessData = readiness.data
  const limitersList  = limiters.data ?? []
  const sleepArr      = (sleepData.data ?? []).filter(s => s.date <= yesterday)
  const lastSleep     = sleepArr[sleepArr.length - 1] ?? null
  const lastWorkout   = [...(recentWorkouts.data ?? [])]
    .sort((a, b) => b.date.localeCompare(a.date))[0] ?? null

  const recommendation = readinessData?.recommendation as ReadinessLevel | undefined

  // Readiness history → TrendChart data shape
  const trendChartData = (readinessHist.data ?? []).map(p => ({
    date:      p.date,
    value:     p.score,
    avg7d:     null as number | null,
    avg30d:    null as number | null,
    isAnomaly: false,
  }))

  // Sparkline configs
  const SPARKLINES: Array<{
    key:       SparklineKey
    label:     string
    unit:      string
    toDisplay: (v: number) => string
    transform: (v: number) => number
    trend:     ReturnType<typeof useMetricTrend>
  }> = [
    {
      key:       'hrv',
      label:     'HRV',
      unit:      ' ms',
      toDisplay: v => `${Math.round(v)}`,
      transform: v => v,
      trend:     hrvTrend,
    },
    {
      key:       'sleep_duration',
      label:     'Sleep',
      unit:      'h',
      toDisplay: v => (v / 60).toFixed(1),
      transform: v => v / 60,  // backend returns minutes; chart shows hours
      trend:     sleepTrend,
    },
    {
      key:       'daily_strain',
      label:     'Strain',
      unit:      '',
      toDisplay: v => v.toFixed(1),
      transform: v => v,
      trend:     strainTrend,
    },
  ]

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div
      style={{
        display:       'flex',
        flexDirection: 'column',
        gap:           16,
        maxWidth:      600,
        margin:        '0 auto',
      }}
    >

      {/* ── 1. Hero ──────────────────────────────────────────────────────── */}
      <Card style={{ padding: '24px 20px 20px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <ReadinessArcGauge
            score={readinessData?.score ?? null}
            recommendation={recommendation ?? null}
            confidence={readinessData?.confidence ?? null}
          />

          {/* Limiting factors or all-clear */}
          <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {limitersList.length === 0 ? (
              readiness.isSuccess && limiters.isSuccess ? (
                <p style={{ fontSize: 13, color: 'var(--status-excellent)', textAlign: 'center' }}>
                  All systems green — cleared to train
                </p>
              ) : null
            ) : (
              limitersList.map((lf, i) => (
                <LimitingFactorCard
                  key={i}
                  factorName={lf.factor_name}
                  context={lf.explanation}
                  severity={toCardSeverity(lf.severity)}
                />
              ))
            )}
          </div>
        </div>
      </Card>

      {/* ── 2. Last Night's Sleep ──────────────────────────────────────── */}
      <Card>
        {/* Header row — tappable */}
        <button
          onClick={() => setSleepExpanded(v => !v)}
          style={{
            display:    'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width:      '100%',
            padding:    '14px 16px 10px',
            background: 'transparent',
            border:     'none',
            cursor:     'pointer',
            textAlign:  'left',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <SectionLabel>Last Night's Sleep</SectionLabel>
            <span
              style={{
                fontSize:          22,
                fontWeight:        700,
                color:             'var(--text-primary)',
                fontVariantNumeric:'tabular-nums',
                fontFamily:        "'Geist', system-ui, sans-serif",
              }}
            >
              {fmtDuration(lastSleep?.total_sleep_minutes ?? null)}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {lastSleep?.sleep_performance != null && (
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                {Math.round(lastSleep.sleep_performance)}% perf
              </span>
            )}
            <Chevron open={sleepExpanded} />
          </div>
        </button>

        {/* Sleep stage bar — always visible */}
        <div style={{ padding: '0 16px 14px' }}>
          <SleepStageBar
            deepMinutes={lastSleep?.deep_minutes ?? null}
            lightMinutes={lastSleep?.light_minutes ?? null}
            remMinutes={lastSleep?.rem_minutes ?? null}
            awakeMinutes={lastSleep?.awake_minutes ?? null}
          />
        </div>

        {/* Expanded detail */}
        {sleepExpanded && lastSleep && (
          <div
            style={{
              padding:             '12px 16px 16px',
              borderTop:           '0.5px solid var(--border-subtle)',
              display:             'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap:                 12,
            }}
          >
            {[
              { label: 'Deep',        value: fmtDuration(lastSleep.deep_minutes) },
              { label: 'REM',         value: fmtDuration(lastSleep.rem_minutes) },
              { label: 'Light',       value: fmtDuration(lastSleep.light_minutes) },
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
                <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>
                  {label}
                </p>
                <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {value}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ── 3. Sparkline Row ───────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {SPARKLINES.map(({ key, label, unit, toDisplay, transform, trend }) => {
          const data      = trend.data
          const allValues = data?.values.filter((v): v is number => v != null) ?? []
          const latest    = allValues.length > 0 ? allValues[allValues.length - 1] : undefined
          const isActive  = expandedSparkline === key

          const sparkData = data
            ? data.dates.map((d, i) => ({
                date:      d,
                value:     data.values[i] != null ? transform(data.values[i]!) : null,
                avg7d:     null as number | null,
                avg30d:    null as number | null,
                isAnomaly: false,
              }))
            : []

          return (
            <button
              key={key}
              onClick={() => setExpandedSparkline(v => (v === key ? null : key))}
              style={{
                background:   'var(--bg-card)',
                border:       isActive
                  ? '0.5px solid var(--status-excellent)'
                  : '0.5px solid var(--border-subtle)',
                borderRadius: 10,
                padding:      '10px 10px 4px',
                cursor:       'pointer',
                textAlign:    'left',
                overflow:     'hidden',
                minWidth:     0,
              }}
            >
              <p
                style={{
                  fontSize:      10,
                  textTransform: 'uppercase',
                  letterSpacing: '0.07em',
                  color:         'var(--text-tertiary)',
                  marginBottom:  3,
                }}
              >
                {label}
              </p>

              {latest != null ? (
                <p
                  style={{
                    fontSize:          16,
                    fontWeight:        700,
                    color:             'var(--text-primary)',
                    fontVariantNumeric:'tabular-nums',
                    marginBottom:      4,
                    fontFamily:        "'Geist', system-ui, sans-serif",
                  }}
                >
                  {toDisplay(latest)}{unit}
                </p>
              ) : (
                <div className="skeleton w-10 h-4 rounded mb-1" style={{ marginBottom: 4 }} />
              )}

              {/* Negative margin to bleed sparkline to card edges */}
              <div style={{ margin: '0 -10px' }}>
                <TrendChart
                  data={sparkData}
                  metricName={label}
                  unit={unit}
                  showRollingAvg={false}
                  sparkline
                />
              </div>
            </button>
          )
        })}
      </div>

      {/* Expanded sparkline — full 30-day chart */}
      {expandedSparkline !== null && (() => {
        const cfg = SPARKLINES.find(s => s.key === expandedSparkline)!
        const data = cfg.trend.data
        const chartData = data
          ? data.dates.map((d, i) => ({
              date:      d,
              value:     data.values[i] != null ? cfg.transform(data.values[i]!) : null,
              avg7d:     data.rolling_avg_7d[i] != null
                ? cfg.transform(data.rolling_avg_7d[i]!)
                : null,
              avg30d:    null as number | null,
              isAnomaly: data.anomalies.some(a => a.date === d),
            }))
          : []

        return (
          <Card style={{ padding: '16px 16px 12px' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
              {cfg.label} — 30 days
            </p>
            <TrendChart
              data={chartData}
              metricName={cfg.label}
              unit={cfg.unit}
              showRollingAvg
              height={160}
            />
          </Card>
        )
      })()}

      {/* ── 4. Training Snapshot ───────────────────────────────────────── */}
      <Card>
        <button
          onClick={() => setTrainingExpanded(v => !v)}
          style={{
            display:       'flex',
            alignItems:    'center',
            justifyContent:'space-between',
            width:         '100%',
            padding:       '14px 16px',
            background:    'transparent',
            border:        'none',
            cursor:        'pointer',
            textAlign:     'left',
          }}
        >
          <SectionLabel>Training Load</SectionLabel>
          <Chevron open={trainingExpanded} />
        </button>

        <div style={{ padding: '0 16px 16px' }}>
          <ACWRGauge
            acwr={trainingLoad.data?.acwr ?? null}
            zone={trainingLoad.data?.zone ?? null}
            zoneDescription={trainingLoad.data?.zone_description ?? null}
          />
        </div>

        {/* Last workout — expanded */}
        {trainingExpanded && (
          <div
            style={{
              padding:   '12px 16px 16px',
              borderTop: '0.5px solid var(--border-subtle)',
            }}
          >
            {lastWorkout ? (
              <>
                <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>
                  Last workout
                </p>
                <div
                  style={{
                    display:       'flex',
                    alignItems:    'center',
                    justifyContent:'space-between',
                  }}
                >
                  <div>
                    <p
                      style={{
                        fontSize:     14,
                        fontWeight:   600,
                        color:        'var(--text-primary)',
                        textTransform:'capitalize',
                      }}
                    >
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
                      <p
                        style={{
                          fontSize:          20,
                          fontWeight:        700,
                          color:             'var(--text-primary)',
                          fontVariantNumeric:'tabular-nums',
                          fontFamily:        "'Geist', system-ui, sans-serif",
                        }}
                      >
                        {lastWorkout.strain.toFixed(1)}
                      </p>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>
                No workouts in the last 7 days
              </p>
            )}

            {trainingLoad.data?.confidence_note && (
              <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 10, fontStyle: 'italic' }}>
                {trainingLoad.data.confidence_note}
              </p>
            )}
          </div>
        )}
      </Card>

      {/* ── 5. 30-Day Readiness Trend (collapsed by default) ──────────── */}
      <Card>
        <button
          onClick={() => setTrendExpanded(v => !v)}
          style={{
            display:       'flex',
            alignItems:    'center',
            justifyContent:'space-between',
            width:         '100%',
            padding:       '14px 16px',
            background:    'transparent',
            border:        'none',
            cursor:        'pointer',
            textAlign:     'left',
          }}
        >
          <SectionLabel>30-Day Readiness Trend</SectionLabel>
          <Chevron open={trendExpanded} />
        </button>

        {trendExpanded && (
          <div style={{ padding: '0 16px 16px' }}>
            <TrendChart
              data={trendChartData}
              metricName="Readiness"
              unit=""
              showRollingAvg={false}
              height={160}
            />
          </div>
        )}
      </Card>

    </div>
  )
}
