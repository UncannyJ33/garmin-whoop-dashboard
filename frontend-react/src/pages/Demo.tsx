/**
 * Demo — public showcase at /demo.
 * Mirrors the Today page layout with hardcoded 30-day sample data.
 * No auth required. No API calls.
 *
 * Story: fictional athlete coming off a 2-week training block,
 * took a recovery day, now sitting at 74 readiness — "Train normally."
 */

import { useState } from 'react'
import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { ACWRGauge } from '../components/ACWRGauge'
import { LimitingFactorCard } from '../components/LimitingFactorCard'
import { ReadinessArcGauge } from '../components/ReadinessArcGauge'
import { SleepStageBar } from '../components/SleepStageBar'
import { TrendChart } from '../components/TrendChart'
import type { LimitingFactor, MetricTrend } from '../types/api'

// ---------------------------------------------------------------------------
// Mock data helpers
// ---------------------------------------------------------------------------

function buildDates(n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date('2026-03-20T12:00:00')
    d.setDate(d.getDate() - (n - 1 - i))
    return d.toISOString().split('T')[0]
  })
}

function rollingAvg(arr: number[], w: number): (number | null)[] {
  return arr.map((_, i) => {
    if (i < w - 1) return null
    const s = arr.slice(i - w + 1, i + 1)
    return Math.round((s.reduce((a, b) => a + b, 0) / w) * 10) / 10
  })
}

// ---------------------------------------------------------------------------
// 30-day sample dataset
// Week 1 (days 0–6):   Base building — readiness 68–75, HRV 58–64
// Week 2 (days 7–13):  Hard block — readiness dips to 42, HRV drops to 40
// Week 3 (days 14–20): Reload — readiness 50→68, HRV 43→56
// Week 4 (days 21–29): Fresh — readiness 72–78, HRV 54–62
// Today (day 29):      74 readiness, HRV 54 ms (slightly below 7d avg)
// ---------------------------------------------------------------------------

const DATES = buildDates(30)

//                           W1                        W2                        W3                           W4+today
const READINESS_RAW = [70, 68, 72, 75, 73, 71, 69,  58, 55, 52, 54, 48, 45, 42,  50, 52, 55, 58, 60, 65, 68,  72, 76, 78, 75, 78, 74, 72, 76, 74]
const HRV_RAW       = [60, 58, 62, 61, 64, 62, 59,  52, 50, 48, 46, 44, 41, 40,  43, 45, 48, 50, 52, 54, 56,  58, 60, 62, 58, 56, 54, 56, 58, 54]
const SLEEP_MIN_RAW = [450, 420, 465, 455, 440, 470, 445, 390, 420, 410, 435, 330, 415, 450, 405, 440, 430, 460, 450, 445, 465, 420, 455, 470, 440, 475, 462, 448, 455, 442]
const STRAIN_RAW    = [9.5, 10.2, 8.8, 11.1, 9.4, 10.8, 9.2, 14.5, 15.2, 16.8, 15.5, 17.2, 18.1, 16.4, 14.8, 13.5, 12.2, 9.8, 10.5, 11.2, 8.4, 9.1, 10.8, 13.2, 11.5, 12.8, 13.5, 12.1, 13.8, 13.2]

function makeTrend(name: string, values: number[], anomalyIdx: number | null = null): MetricTrend {
  return {
    metric_name:     name,
    dates:           DATES,
    values,
    rolling_avg_7d:  rollingAvg(values, 7),
    rolling_avg_30d: rollingAvg(values, 30),
    rolling_std_7d:  Array(30).fill(null),
    anomalies:       anomalyIdx != null
      ? [{ date: DATES[anomalyIdx], value: values[anomalyIdx], direction: 'low', severity: 2 }]
      : [],
    trend_direction: 'improving',
  }
}

const MOCK_HRV_TREND    = makeTrend('hrv', HRV_RAW, 13)
const MOCK_SLEEP_TREND  = makeTrend('sleep_duration', SLEEP_MIN_RAW)
const MOCK_STRAIN_TREND = makeTrend('daily_strain', STRAIN_RAW)

const MOCK_READINESS_TREND = DATES.map((date, i) => ({
  date,
  value:     READINESS_RAW[i],
  avg7d:     null as number | null,
  avg30d:    null as number | null,
  isAnomaly: i === 13,
}))

const MOCK_LIMITERS: LimitingFactor[] = [
  {
    factor_name:           'HRV',
    current_value:         54,
    current_value_display: '54 ms',
    normalized_score:      0.48,
    seven_day_avg:         61,
    seven_day_avg_display: '61 ms',
    deviation_pct:         -11.5,
    explanation:           'HRV is slightly below your 7-day baseline (54 ms vs 61 ms avg).',
    severity:              'moderate',
  },
  {
    factor_name:           'Sleep debt',
    current_value:         -48,
    current_value_display: '48 min deficit',
    normalized_score:      0.55,
    seven_day_avg:         452,
    seven_day_avg_display: '7h 32m',
    deviation_pct:         -2.1,
    explanation:           'Sleep debt accumulating — 0.8h below your weekly target.',
    severity:              'moderate',
  },
]

// ---------------------------------------------------------------------------
// Layout atoms (mirrors Today.tsx — kept local so Demo is self-contained)
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
        letterSpacing: '0.02em',
        color:         'var(--text-tertiary)',
        fontWeight:    500,
      }}
    >
      {children}
    </span>
  )
}

function MiniSparkline({
  data,
  color = 'var(--data-primary)',
  height = 40,
}: {
  data:    Array<{ value: number | null }>
  color?:  string
  height?: number
}) {
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

function stripPrefix(explanation: string, factorName: string): string {
  if (explanation.startsWith(factorName)) {
    return explanation.slice(factorName.length).replace(/^[\s—\-:]+/, '')
  }
  return explanation
}

// ---------------------------------------------------------------------------
// Demo page
// ---------------------------------------------------------------------------

type SparklineKey = 'hrv' | 'sleep_duration' | 'daily_strain'

const SPARKLINES: Array<{
  key:       SparklineKey
  label:     string
  unit:      string
  toDisplay: (v: number) => string
  transform: (v: number) => number
  trend:     MetricTrend
  color:     string
}> = [
  {
    key:       'hrv',
    label:     'HRV',
    unit:      ' ms',
    toDisplay: v => `${Math.round(v)}`,
    transform: v => v,
    trend:     MOCK_HRV_TREND,
    color:     'var(--data-primary)',
  },
  {
    key:       'sleep_duration',
    label:     'Sleep',
    unit:      'h',
    toDisplay: v => (v / 60).toFixed(1),
    transform: v => v / 60,
    trend:     MOCK_SLEEP_TREND,
    color:     'var(--status-excellent)',
  },
  {
    key:       'daily_strain',
    label:     'Strain',
    unit:      '',
    toDisplay: v => v.toFixed(1),
    transform: v => v,
    trend:     MOCK_STRAIN_TREND,
    color:     'var(--status-caution)',
  },
]

export function Demo() {
  const [sleepExpanded,     setSleepExpanded]     = useState(false)
  const [trainingExpanded,  setTrainingExpanded]  = useState(false)
  const [trendExpanded,     setTrendExpanded]     = useState(false)
  const [expandedSparkline, setExpandedSparkline] = useState<SparklineKey | null>(null)

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>

      {/* ── Top bar ─────────────────────────────────────────────────── */}
      <header
        style={{
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'space-between',
          padding:        '14px 24px',
          background:     'var(--bg-card)',
          borderBottom:   '0.5px solid var(--border-subtle)',
          position:       'sticky',
          top:            0,
          zIndex:         10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize:      16,
              fontWeight:    700,
              color:         'var(--text-primary)',
              letterSpacing: '-0.01em',
              fontFamily:    "'Barlow Condensed', system-ui, sans-serif",
            }}
          >
            PulseEngine
          </span>
          <span
            style={{
              fontSize:      10,
              fontWeight:    600,
              background:    'var(--brand-muted)',
              color:         'var(--brand)',
              padding:       '2px 7px',
              borderRadius:  10,
              letterSpacing: '0.03em',
            }}
          >
            Demo
          </span>
        </div>
        <a
          href="/login"
          style={{
            fontSize:       13,
            fontWeight:     600,
            color:          'var(--brand)',
            textDecoration: 'none',
          }}
        >
          Create account →
        </a>
      </header>

      {/* ── Demo banner ──────────────────────────────────────────────── */}
      <div
        style={{
          background:     'var(--brand-muted)',
          borderBottom:   '0.5px solid var(--brand-border)',
          padding:        '10px 24px',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'space-between',
          gap:            12,
        }}
      >
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
          Sample data — connect your Garmin + Whoop to see your actual metrics
        </p>
        <a
          href="/login"
          style={{
            fontSize:       13,
            fontWeight:     600,
            color:          'var(--brand)',
            textDecoration: 'none',
            whiteSpace:     'nowrap',
          }}
        >
          Get started →
        </a>
      </div>

      {/* ── Content ─────────────────────────────────────────────────── */}
      <div
        style={{
          display:             'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap:                 16,
          maxWidth:            960,
          margin:              '0 auto',
          padding:             '24px 16px 64px',
          alignItems:          'start',
        }}
      >

        {/* ── Left column ─────────────────────────────────────────── */}
        <Card style={{ padding: '24px 20px 20px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
            <ReadinessArcGauge
              score={74}
              recommendation="Train normally"
              confidence={0.91}
            />
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
              {MOCK_LIMITERS.map((lf, i) => (
                <LimitingFactorCard
                  key={i}
                  factorName={lf.factor_name}
                  context={stripPrefix(lf.explanation, lf.factor_name)}
                  severity="caution"
                />
              ))}
            </div>
          </div>
        </Card>

        {/* ── Right column ─────────────────────────────────────────── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

        {/* 2. Last Night's Sleep ───────────────────────────────────── */}
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
              <span
                style={{
                  fontSize:           22,
                  fontWeight:         700,
                  color:              'var(--text-primary)',
                  fontVariantNumeric: 'tabular-nums',
                  fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
                }}
              >
                7h 22m
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>82% perf</span>
              <Chevron open={sleepExpanded} />
            </div>
          </button>

          <div style={{ padding: '0 16px 14px' }}>
            <SleepStageBar deepMinutes={88} lightMinutes={228} remMinutes={102} awakeMinutes={24} />
          </div>

          {sleepExpanded && (
            <div
              style={{
                padding:             '12px 16px 16px',
                borderTop:           '0.5px solid var(--border-subtle)',
                display:             'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap:                 12,
              }}
            >
              {([
                { label: 'Deep',       value: '1h 28m' },
                { label: 'REM',        value: '1h 42m' },
                { label: 'Light',      value: '3h 48m' },
                { label: 'Efficiency', value: '95%' },
                { label: 'Sleep debt', value: '48 min deficit' },
              ] as const).map(({ label, value }) => (
                <div key={label}>
                  <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 2 }}>{label}</p>
                  <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{value}</p>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* 3. Sparkline Row ───────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {SPARKLINES.map(({ key, label, unit, toDisplay, transform, trend, color }) => {
            const allValues  = trend.values.filter((v): v is number => v != null)
            const latest     = allValues[allValues.length - 1]
            const prev       = allValues[allValues.length - 2]
            const arrowRaw   = latest - prev
            const arrow      = Math.abs(arrowRaw) < 0.5 ? '→' : arrowRaw > 0 ? '↑' : '↓'
            const arrowColor = arrow === '→'
              ? 'var(--text-tertiary)'
              : arrow === '↑' ? 'var(--data-primary)' : 'var(--data-anomaly)'
            const chartData  = trend.values.map(v => ({ value: v != null ? transform(v) : null }))
            const isActive   = expandedSparkline === key

            return (
              <button
                key={key}
                onClick={() => setExpandedSparkline(v => v === key ? null : key)}
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
                }}
              >
                <p style={{ fontSize: 10, letterSpacing: '0.02em', color: 'var(--text-tertiary)', marginBottom: 4 }}>
                  {label}
                </p>
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
                <MiniSparkline data={chartData} color={color} height={40} />
              </button>
            )
          })}
        </div>

        {/* Expanded sparkline — full 30-day chart */}
        {expandedSparkline !== null && (() => {
          const cfg = SPARKLINES.find(s => s.key === expandedSparkline)!
          const chartData = cfg.trend.dates.map((d, i) => ({
            date:      d,
            value:     cfg.trend.values[i] != null ? cfg.transform(cfg.trend.values[i]!) : null,
            avg7d:     cfg.trend.rolling_avg_7d[i] != null ? cfg.transform(cfg.trend.rolling_avg_7d[i]!) : null,
            avg30d:    null as number | null,
            isAnomaly: cfg.trend.anomalies.some(a => a.date === d),
          }))
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

        {/* 4. Training Snapshot ───────────────────────────────────── */}
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
            <ACWRGauge
              acwr={1.05}
              zone="sweet_spot"
              zoneDescription="Load is well-balanced — good time to maintain or slightly increase training."
            />
          </div>

          {trainingExpanded && (
            <div
              style={{
                padding:   '12px 16px 16px',
                borderTop: '0.5px solid var(--border-subtle)',
              }}
            >
              <p style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 8 }}>Last workout</p>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <p style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Running</p>
                  <p style={{ fontSize: 12, color: 'var(--text-tertiary)', marginTop: 2 }}>
                    Mar 19 · 48 min
                  </p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <p style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Strain</p>
                  <p
                    style={{
                      fontSize:           20,
                      fontWeight:         700,
                      color:              'var(--text-primary)',
                      fontVariantNumeric: 'tabular-nums',
                      fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
                    }}
                  >
                    13.2
                  </p>
                </div>
              </div>
            </div>
          )}
        </Card>

        {/* 5. 30-Day Readiness Trend ──────────────────────────────── */}
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
              <TrendChart
                data={MOCK_READINESS_TREND}
                metricName="Readiness"
                unit=""
                showRollingAvg={false}
                height={160}
              />
            </div>
          )}
        </Card>

        </div>{/* end right column */}
      </div>
    </div>
  )
}
