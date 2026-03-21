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
import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { ACWRGauge } from '../components/ACWRGauge'
import { LimitingFactorCard } from '../components/LimitingFactorCard'
import { ReadinessArcGauge } from '../components/ReadinessArcGauge'
import { SleepStageBar } from '../components/SleepStageBar'
import type { ReadinessLevel } from '../components/StatusBadge'
import { TrendChart } from '../components/TrendChart'
import { ConnectDevicesPanel } from '../components/ConnectDevicesPanel'
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

// The API returns a full sentence like "Push hard — your body is primed…"
// Extract the ReadinessLevel prefix so StatusBadge can look it up.
const READINESS_LEVELS: ReadinessLevel[] = ['Push hard', 'Train normally', 'Go easy', 'Rest day']
function extractLevel(rec: string | undefined): ReadinessLevel | null {
  if (!rec) return null
  return READINESS_LEVELS.find(l => rec.startsWith(l)) ?? null
}

// Strip factor_name prefix from explanation text if the API includes it.
// e.g. "Body Battery is low at 88" → "is low at 88"
function stripFactorPrefix(explanation: string, factorName: string): string {
  if (explanation.startsWith(factorName)) {
    return explanation.slice(factorName.length).replace(/^[\s—\-:]+/, '')
  }
  return explanation
}

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

// ---------------------------------------------------------------------------
// Shared layout atoms
// ---------------------------------------------------------------------------

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

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="14" height="14" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round"
      style={{
        color:      'var(--text-tertiary)',
        transform:  open ? 'rotate(180deg)' : 'none',
        transition: 'transform 200ms ease',
        flexShrink: 0,
      }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

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
// Inline sparkline — full-width Recharts LineChart (no fixed-width hack).
// Avoids TrendChart's fixed width={200} which clips in narrow cards.
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
  const [sleepExpanded,     setSleepExpanded]     = useState(false)
  const [trainingExpanded,  setTrainingExpanded]  = useState(false)
  const [trendExpanded,     setTrendExpanded]     = useState(false)
  const [expandedSparkline, setExpandedSparkline] = useState<SparklineKey | null>(null)

  // ── Derived ────────────────────────────────────────────────────────────
  const readinessData  = readiness.data
  const limitersList   = limiters.data ?? []
  const sleepArr       = (sleepData.data ?? []).filter(s => s.date <= yesterday)
  const lastSleep      = sleepArr[sleepArr.length - 1] ?? null
  const lastWorkout    = [...(recentWorkouts.data ?? [])]
    .sort((a, b) => b.date.localeCompare(a.date))[0] ?? null
  const recommendation = extractLevel(readinessData?.recommendation)

  // Readiness history for the trend chart
  const trendChartData = (readinessHist.data ?? []).map(p => ({
    date:      p.date,
    value:     p.score,
    avg7d:     null as number | null,
    avg30d:    null as number | null,
    isAnomaly: false,
  }))

  // Sparkline card config — transform + format kept local, chart uses values[]
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
      // backend returns minutes; display as hours
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
      <div style={{ maxWidth: 480, margin: '32px auto', padding: '0 16px' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <p style={{ fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
            Connect your devices
          </p>
          <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
            Link Whoop or Garmin to start seeing your personalised dashboard.
          </p>
        </div>
        <ConnectDevicesPanel />
      </div>
    )
  }

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
          {/* Gauge — skeleton until data arrives */}
          {readiness.isPending ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
              <p style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'var(--text-tertiary)' }}>
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

          {/* Limiting factors or all-clear.
              position:relative ensures this stacking context paints above the arc
              container's position:relative div (they're now both positioned). */}
          <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
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
      </Card>

      {/* ── 2. Last Night's Sleep ──────────────────────────────────────── */}
      <Card>
        <button
          onClick={() => setSleepExpanded(v => !v)}
          style={{
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'space-between',
            width:          '100%',
            padding:        '14px 16px 10px',
            background:     'transparent',
            border:         'none',
            cursor:         'pointer',
            textAlign:      'left',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <SectionLabel>Last Night's Sleep</SectionLabel>
            {sleepData.isPending ? (
              <div className="skeleton" style={{ width: 72, height: 28, borderRadius: 4, marginTop: 2 }} />
            ) : (
              <span
                style={{
                  fontSize:           22,
                  fontWeight:         700,
                  color:              'var(--text-primary)',
                  fontVariantNumeric: 'tabular-nums',
                  fontFamily:         "'Geist', system-ui, sans-serif",
                }}
              >
                {fmtDuration(lastSleep?.total_sleep_minutes ?? null)}
              </span>
            )}
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

        {/* Sleep stage bar */}
        <div style={{ padding: '0 16px 14px' }}>
          {sleepData.isPending ? (
            <div className="skeleton" style={{ height: 10, borderRadius: 5 }} />
          ) : (
            <SleepStageBar
              deepMinutes={lastSleep?.deep_minutes ?? null}
              lightMinutes={lastSleep?.light_minutes ?? null}
              remMinutes={lastSleep?.rem_minutes ?? null}
              awakeMinutes={lastSleep?.awake_minutes ?? null}
            />
          )}
        </div>

        {/* Expanded detail — only shown when we have data */}
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
                <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>{label}</p>
                <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{value}</p>
              </div>
            ))}
          </div>
        )}

        {/* Prompt when expanded but no data */}
        {sleepExpanded && !lastSleep && !sleepData.isPending && (
          <p style={{ fontSize: 13, color: 'var(--text-tertiary)', padding: '8px 16px 14px' }}>
            No sleep data for last night
          </p>
        )}
      </Card>

      {/* ── 3. Sparkline Row ───────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {SPARKLINES.map(({ key, label, unit, toDisplay, transform, trend, color }) => {
          const data      = trend.data
          const allValues = data?.values.filter((v): v is number => v != null) ?? []
          const latest    = allValues.length > 0 ? allValues[allValues.length - 1] : undefined

          // Direction arrow: compare last two non-null values
          const prevValues   = allValues.slice(-2)
          const arrowRaw     = prevValues.length === 2 ? prevValues[1] - prevValues[0] : 0
          const arrow        = Math.abs(arrowRaw) < 0.5 ? '→' : arrowRaw > 0 ? '↑' : '↓'
          const arrowColor   = arrow === '→'
            ? 'var(--text-tertiary)'
            : arrow === '↑' ? 'var(--data-primary)' : 'var(--data-anomaly)'

          // Chart data: transform values (e.g. sleep: minutes→hours)
          const chartData = (data?.values ?? []).map(v => ({
            value: v != null ? transform(v) : null,
          }))

          const isActive = expandedSparkline === key

          return (
            <button
              key={key}
              onClick={() => setExpandedSparkline(v => v === key ? null : key)}
              style={{
                background:   'var(--bg-card)',
                border:       isActive
                  ? '0.5px solid var(--status-excellent)'
                  : '0.5px solid var(--border-subtle)',
                borderRadius: 10,
                padding:      '10px 10px 6px',
                cursor:       'pointer',
                textAlign:    'left',
                overflow:     'hidden',
                minWidth:     0,
              }}
            >
              {/* Label row */}
              <p style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-tertiary)', marginBottom: 4 }}>
                {label}
              </p>

              {/* Value + arrow row */}
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
                      fontFamily:         "'Geist', system-ui, sans-serif",
                    }}
                  >
                    {toDisplay(latest)}{unit}
                  </span>
                  <span style={{ fontSize: 11, color: arrowColor }}>{arrow}</span>
                </div>
              ) : (
                <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginBottom: 4 }}>No data</p>
              )}

              {/* Inline full-width sparkline */}
              {trend.isPending ? (
                <div className="skeleton" style={{ height: 40, borderRadius: 4 }} />
              ) : chartData.length > 0 ? (
                <MiniSparkline data={chartData} color={color} height={40} />
              ) : (
                <div style={{ height: 40 }} />
              )}
            </button>
          )
        })}
      </div>

      {/* Expanded sparkline — full 30-day chart below the row */}
      {expandedSparkline !== null && (() => {
        const cfg      = SPARKLINES.find(s => s.key === expandedSparkline)!
        const data     = cfg.trend.data
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
              color={cfg.color}
            />
          </Card>
        )
      })()}

      {/* ── 4. Training Snapshot ───────────────────────────────────────── */}
      <Card>
        <button
          onClick={() => setTrainingExpanded(v => !v)}
          style={{
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'space-between',
            width:          '100%',
            padding:        '14px 16px',
            background:     'transparent',
            border:         'none',
            cursor:         'pointer',
            textAlign:      'left',
          }}
        >
          <SectionLabel>Training Load</SectionLabel>
          <Chevron open={trainingExpanded} />
        </button>

        <div style={{ padding: '0 16px 16px' }}>
          {trainingLoad.isPending ? (
            <>
              <div className="skeleton" style={{ height: 20, borderRadius: 4, marginBottom: 8 }} />
              <div className="skeleton" style={{ height: 12, borderRadius: 6 }} />
            </>
          ) : (
            <ACWRGauge
              acwr={trainingLoad.data?.acwr ?? null}
              zone={trainingLoad.data?.zone ?? null}
              zoneDescription={trainingLoad.data?.zone_description ?? null}
            />
          )}
        </div>

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
                      <p style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums', fontFamily: "'Geist', system-ui, sans-serif" }}>
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
            display:        'flex',
            alignItems:     'center',
            justifyContent: 'space-between',
            width:          '100%',
            padding:        '14px 16px',
            background:     'transparent',
            border:         'none',
            cursor:         'pointer',
            textAlign:      'left',
          }}
        >
          <SectionLabel>30-Day Readiness Trend</SectionLabel>
          <Chevron open={trendExpanded} />
        </button>

        {trendExpanded && (
          <div style={{ padding: '0 16px 16px' }}>
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
          </div>
        )}
      </Card>

    </div>
  )
}
