import { useState } from 'react'

function Card({ children, className = '', style = {} }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return <div className={className} style={{ background: 'var(--bg-card)', border: '0.5px solid var(--border-subtle)', borderRadius: 12, padding: 16, ...style }}>{children}</div>
}
function Label({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.02em', color: 'var(--text-secondary)', marginBottom: 6 }}>{children}</p>
}
function Mono({ children, size = 28 }: { children: React.ReactNode; size?: number }) {
  return <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: size, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>{children}</span>
}

// ── Mock data ────────────────────────────────────────────────────────────────

const RUNNING_WEEKS = [
  { week: 'W9', km: 28, hrs: 3.1 },
  { week: 'W10', km: 34, hrs: 3.8 },
  { week: 'W11', km: 31, hrs: 3.4 },
  { week: 'W12', km: 42, hrs: 4.6 },
  { week: 'W13', km: 38, hrs: 4.2 },
  { week: 'W14', km: 45, hrs: 4.9 },
]

const STRENGTH_EXERCISES = [
  { name: 'Back Squat', data: [185, 195, 195, 205, 205, 215, 225] },
  { name: 'Bench Press', data: [155, 155, 165, 165, 170, 175, 175] },
  { name: 'Deadlift', data: [225, 235, 245, 245, 255, 265, 275] },
  { name: 'OHP', data: [95, 100, 100, 105, 105, 110, 115] },
]

const DYNAMICS = [
  { date: 'Mar 1', cadence: 172, gct: 248 },
  { date: 'Mar 5', cadence: 174, gct: 244 },
  { date: 'Mar 9', cadence: 175, gct: 241 },
  { date: 'Mar 12', cadence: 176, gct: 238 },
  { date: 'Mar 16', cadence: 177, gct: 236 },
  { date: 'Mar 19', cadence: 178, gct: 234 },
  { date: 'Mar 23', cadence: 179, gct: 231 },
]

const SCATTER = [
  { strain: 8.2, recovery: 72, type: 'run', color: 'var(--status-excellent)' },
  { strain: 12.1, recovery: 58, type: 'run', color: 'var(--status-excellent)' },
  { strain: 14.3, recovery: 45, type: 'strength', color: 'var(--status-caution)' },
  { strain: 9.8, recovery: 68, type: 'run', color: 'var(--status-excellent)' },
  { strain: 15.2, recovery: 42, type: 'strength', color: 'var(--status-caution)' },
  { strain: 6.5, recovery: 81, type: 'yoga', color: '#7a5ea0' },
  { strain: 11.2, recovery: 55, type: 'cycling', color: 'var(--brand)' },
  { strain: 7.6, recovery: 75, type: 'cycling', color: 'var(--brand)' },
  { strain: 13.5, recovery: 51, type: 'run', color: 'var(--status-excellent)' },
  { strain: 10.1, recovery: 62, type: 'strength', color: 'var(--status-caution)' },
  { strain: 16.8, recovery: 38, type: 'run', color: 'var(--status-excellent)' },
  { strain: 5.2, recovery: 85, type: 'yoga', color: '#7a5ea0' },
]

// ── Chart components ─────────────────────────────────────────────────────────

/** Vertical bar chart matching the actual dashboard style */
function VerticalBarChart({ data, color, unit }: { data: { label: string; value: number }[]; color: string; unit: string }) {
  const maxVal = Math.max(...data.map(d => d.value)) * 1.15
  const h = 160
  const barWidth = Math.min(32, Math.floor(200 / data.length))
  const gap = 8

  return (
    <div style={{ width: '100%' }}>
      <svg viewBox={`0 0 ${data.length * (barWidth + gap) + 20} ${h + 24}`} width="100%" height={h + 24} preserveAspectRatio="xMidYMid meet">
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map(pct => (
          <line key={pct} x1={0} y1={h * (1 - pct)} x2={data.length * (barWidth + gap) + 20} y2={h * (1 - pct)} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
        ))}
        {/* Bars with gradient */}
        <defs>
          <linearGradient id={`vbar-${color.replace(/[^a-z]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.8" />
            <stop offset="100%" stopColor={color} stopOpacity="0.2" />
          </linearGradient>
        </defs>
        {data.map((d, i) => {
          const barH = (d.value / maxVal) * h
          const x = 10 + i * (barWidth + gap)
          return (
            <g key={i}>
              <rect x={x} y={h - barH} width={barWidth} height={barH} rx={3} fill={`url(#vbar-${color.replace(/[^a-z]/g, '')})`} />
              {/* Value on top */}
              <text x={x + barWidth / 2} y={h - barH - 4} textAnchor="middle" fill="var(--text-secondary)" fontSize="8" fontFamily="'IBM Plex Mono', monospace">
                {d.value.toFixed(unit === 'h' ? 1 : 0)}
              </text>
              {/* Label below */}
              <text x={x + barWidth / 2} y={h + 14} textAnchor="middle" fill="var(--text-tertiary)" fontSize="8" fontFamily="'DM Sans', sans-serif">
                {d.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function LineChart({ series, labels, height = 140 }: { series: { data: number[]; color: string; label: string; dashed?: boolean }[]; labels: string[]; height?: number }) {
  const allVals = series.flatMap(s => s.data)
  const min = Math.min(...allVals) * 0.92
  const max = Math.max(...allVals) * 1.08
  const range = max - min || 1
  const w = 300

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${height + 20}`} width="100%" height={height + 20} preserveAspectRatio="xMidYMid meet">
        {[0, 0.25, 0.5, 0.75, 1].map(pct => (
          <line key={pct} x1={30} y1={height * (1 - pct)} x2={w} y2={height * (1 - pct)} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
        ))}
        {series.map(s => {
          const pts = s.data.map((v, i) => `${30 + (i / (s.data.length - 1)) * (w - 30)},${height - ((v - min) / range) * (height - 10) - 5}`).join(' ')
          return <polyline key={s.label} points={pts} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? '4 3' : 'none'} />
        })}
        {labels.map((l, i) => (
          <text key={i} x={30 + (i / (labels.length - 1)) * (w - 30)} y={height + 14} textAnchor="middle" fill="var(--text-tertiary)" fontSize="8" fontFamily="'DM Sans', sans-serif">{l}</text>
        ))}
      </svg>
      <div style={{ display: 'flex', gap: 16, marginTop: 4 }}>
        {series.map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 2, background: s.color, borderRadius: 1 }} />
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function ScatterPlot({ data }: { data: typeof SCATTER }) {
  const maxStrain = 20, maxRecovery = 100
  const w = 300, h = 160, pad = 30

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h + 20}`} width="100%" height={h + 20}>
        {[0, 0.25, 0.5, 0.75, 1].map(pct => (
          <line key={pct} x1={pad} y1={h * (1 - pct)} x2={w} y2={h * (1 - pct)} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
        ))}
        {data.map((d, i) => (
          <circle key={i} cx={pad + (d.strain / maxStrain) * (w - pad)} cy={h - (d.recovery / maxRecovery) * (h - 10) - 5} r="4" fill={d.color} opacity="0.75" />
        ))}
        <text x={w / 2 + pad / 2} y={h + 16} textAnchor="middle" fill="var(--text-tertiary)" fontSize="8" fontFamily="'DM Sans'">Strain</text>
      </svg>
      <div style={{ display: 'flex', gap: 12, marginTop: 4, flexWrap: 'wrap' }}>
        {[
          { label: 'Running', color: 'var(--status-excellent)' },
          { label: 'Strength', color: 'var(--status-caution)' },
          { label: 'Cycling', color: 'var(--brand)' },
          { label: 'Yoga', color: '#7a5ea0' },
        ].map(l => (
          <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: l.color }} />
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function TrainingPage() {
  const [days, setDays] = useState(30)

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between animate-fade-in">
        <h1 style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 32, fontWeight: 700 }}>Training</h1>
        <div style={{ display: 'flex', gap: 4 }}>
          {[7, 14, 30, 60].map(d => (
            <button key={d} onClick={() => setDays(d)} style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 500, border: 'none', cursor: 'pointer', background: days === d ? 'var(--brand)' : 'var(--bg-card-elevated)', color: days === d ? '#fff' : 'var(--text-secondary)', transition: 'all 150ms' }}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 animate-fade-in delay-1">
        {[
          { label: 'Workouts', value: '18', delta: '+3', good: true },
          { label: 'Total Hours', value: '14.2', delta: '+1.8', good: true },
          { label: 'Avg Strain', value: '11.4', delta: '+0.6', good: false },
          { label: 'VO2 Max', value: '48.2', delta: '+0.4', good: true },
        ].map(m => (
          <Card key={m.label}>
            <Label>{m.label}</Label>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
              <Mono size={24}>{m.value}</Mono>
              <span style={{ fontSize: 11, fontFamily: "'IBM Plex Mono', monospace", color: m.good ? 'var(--status-excellent)' : 'var(--status-caution)' }}>{m.delta}</span>
            </div>
          </Card>
        ))}
      </div>

      {/* Weekly Volume — 2 column grid matching actual dashboard */}
      <Card className="animate-fade-in delay-2">
        <Label>Weekly Running Volume</Label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <p style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 4 }}>Distance (km)</p>
            <VerticalBarChart
              data={RUNNING_WEEKS.map(w => ({ label: w.week, value: w.km }))}
              color="var(--data-primary)"
              unit="km"
            />
          </div>
          <div>
            <p style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 4 }}>Time (hours)</p>
            <VerticalBarChart
              data={RUNNING_WEEKS.map(w => ({ label: w.week, value: w.hrs }))}
              color="var(--data-secondary)"
              unit="h"
            />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Running Dynamics */}
        <Card className="animate-fade-in delay-3">
          <Label>Running Dynamics</Label>
          <LineChart
            series={[
              { data: DYNAMICS.map(d => d.cadence), color: 'var(--data-primary)', label: 'Cadence (spm)' },
              { data: DYNAMICS.map(d => d.gct), color: 'var(--data-secondary)', label: 'GCT (ms)' },
            ]}
            labels={DYNAMICS.map(d => d.date.slice(4))}
          />
        </Card>

        {/* Strain vs Recovery */}
        <Card className="animate-fade-in delay-4">
          <Label>Strain vs Next-Day Recovery</Label>
          <ScatterPlot data={SCATTER} />
        </Card>
      </div>

      {/* Strength PRs */}
      <Card className="animate-fade-in delay-5">
        <Label>Strength Progression (lb)</Label>
        <LineChart
          series={STRENGTH_EXERCISES.map((e, i) => ({
            data: e.data,
            color: ['var(--data-primary)', 'var(--data-secondary)', 'var(--status-alert)', 'var(--brand)'][i],
            label: e.name,
          }))}
          labels={['W8', 'W9', 'W10', 'W11', 'W12', 'W13', 'W14']}
          height={140}
        />
      </Card>
    </div>
  )
}
