import { useState } from 'react'

function Card({ children, style = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ background: 'var(--bg-card)', border: '0.5px solid var(--border-subtle)', borderRadius: 12, padding: 16, ...style }}>{children}</div>
}
function Label({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.02em', color: 'var(--text-secondary)', marginBottom: 6 }}>{children}</p>
}

// ── Mock data ────────────────────────────────────────────────────────────────

const METRICS: Record<string, { data: number[]; unit: string; color: string }> = {
  Recovery: { data: [68, 72, 65, 78, 71, 80, 63, 75, 82, 69, 77, 84, 66, 73, 79, 85, 70, 76, 81, 74, 88, 71, 78, 83, 67, 79, 86, 72, 77, 82], unit: '', color: 'var(--data-primary)' },
  HRV: { data: [48, 52, 55, 50, 61, 58, 63, 59, 65, 62, 58, 64, 60, 67, 63, 61, 59, 62, 66, 63, 68, 65, 62, 67, 64, 69, 66, 63, 67, 62], unit: 'ms', color: 'var(--data-primary)' },
  Strain: { data: [8.2, 12.1, 6.5, 14.3, 9.8, 11.2, 7.6, 13.5, 10.1, 8.9, 15.2, 6.8, 12.4, 9.1, 11.8, 7.3, 14.1, 8.5, 10.9, 13.2, 7.8, 11.5, 9.4, 12.7, 8.1, 14.8, 10.3, 11.1, 9.6, 12.8], unit: '', color: 'var(--status-caution)' },
  'Body Battery': { data: [72, 65, 78, 80, 68, 85, 74, 71, 82, 76, 88, 69, 81, 75, 83, 90, 67, 79, 86, 73, 91, 70, 84, 77, 87, 66, 82, 78, 85, 81], unit: '%', color: 'var(--brand)' },
  'Sleep Duration': { data: [408, 432, 390, 426, 444, 414, 456, 420, 438, 402, 450, 426, 408, 432, 456, 420, 438, 414, 444, 426, 450, 408, 432, 444, 420, 456, 426, 438, 414, 444], unit: 'h', color: 'var(--status-excellent)' },
  'Resting HR': { data: [58, 57, 59, 56, 58, 55, 57, 56, 54, 57, 55, 53, 56, 54, 55, 52, 54, 56, 53, 55, 52, 54, 53, 51, 54, 52, 53, 51, 52, 50], unit: 'bpm', color: 'var(--status-alert)' },
}

const ANOMALIES = [
  { date: 'Mar 23', metric: 'Strain', value: '16.8', direction: 'high', severity: 'alert' },
  { date: 'Mar 21', metric: 'Recovery', value: '88', direction: 'high', severity: 'excellent' },
  { date: 'Mar 18', metric: 'HRV', value: '42', direction: 'low', severity: 'alert' },
  { date: 'Mar 15', metric: 'Sleep Duration', value: '5.4h', direction: 'low', severity: 'caution' },
  { date: 'Mar 12', metric: 'Body Battery', value: '94', direction: 'high', severity: 'excellent' },
  { date: 'Mar 8', metric: 'Resting HR', value: '62', direction: 'high', severity: 'caution' },
]

const DIGESTS = [
  { category: 'Recovery', icon: '♥', color: 'var(--status-excellent)', text: 'Your recovery averaged 78 this week — up 12% from last week. HRV trend is climbing steadily.' },
  { category: 'Training', icon: '⚡', color: 'var(--status-caution)', text: 'ACWR at 1.08 — right in the sweet spot. Volume increased 18% week-over-week without overreaching.' },
  { category: 'Sleep', icon: '☽', color: '#7a5ea0', text: 'Sleep consistency improved. Bedtime variability down to ±32min from ±48min. Deep sleep % trending up.' },
]

// ── Charts ───────────────────────────────────────────────────────────────────

function MetricExplorerChart({ metric }: { metric: string }) {
  const m = METRICS[metric]
  if (!m) return null
  const data = m.unit === 'h' ? m.data.map(v => v / 60) : m.data
  const min = Math.min(...data) * 0.9
  const max = Math.max(...data) * 1.1
  const range = max - min || 1
  const w = 600, h = 160, pad = 35

  // Rolling 7d
  const avg7 = data.map((_, i) => {
    const window = data.slice(Math.max(0, i - 6), i + 1)
    return window.reduce((s, v) => s + v, 0) / window.length
  })
  // Rolling 30d
  const avg30 = data.map((_, i) => {
    const window = data.slice(Math.max(0, i - 29), i + 1)
    return window.reduce((s, v) => s + v, 0) / window.length
  })

  const toY = (v: number) => h - ((v - min) / range) * (h - 10) - 5
  const toX = (i: number) => pad + (i / (data.length - 1)) * (w - pad)
  const pts = data.map((v, i) => `${toX(i)},${toY(v)}`).join(' ')
  const avg7pts = avg7.map((v, i) => `${toX(i)},${toY(v)}`).join(' ')
  const avg30pts = avg30.map((v, i) => `${toX(i)},${toY(v)}`).join(' ')

  // Find anomalies (z-score > 2)
  const mean = data.reduce((s, v) => s + v, 0) / data.length
  const std = Math.sqrt(data.reduce((s, v) => s + (v - mean) ** 2, 0) / data.length)
  const anomalyIndices = data.map((v, i) => Math.abs(v - mean) / (std || 1) > 1.8 ? i : -1).filter(i => i >= 0)

  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h + 20}`} width="100%" height={h + 20} preserveAspectRatio="xMidYMid meet">
        {/* Grid + Y labels */}
        {[0, 0.25, 0.5, 0.75, 1].map(pct => {
          const y = toY(min + pct * range)
          const val = min + pct * range
          return (
            <g key={pct}>
              <line x1={pad} y1={y} x2={w} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
              <text x={pad - 4} y={y + 3} textAnchor="end" fill="var(--text-tertiary)" fontSize="7" fontFamily="'IBM Plex Mono'">{val.toFixed(m.unit === 'h' ? 1 : 0)}{m.unit === 'h' ? 'h' : ''}</text>
            </g>
          )
        })}
        {/* 30d avg */}
        <polyline points={avg30pts} fill="none" stroke="var(--text-tertiary)" strokeWidth="1" strokeDasharray="3 3" strokeLinejoin="round" opacity="0.5" />
        {/* 7d avg */}
        <polyline points={avg7pts} fill="none" stroke="var(--data-secondary)" strokeWidth="1.5" strokeLinejoin="round" />
        {/* Main line */}
        <polyline points={pts} fill="none" stroke={m.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* Anomalies */}
        {anomalyIndices.map(i => (
          <circle key={i} cx={toX(i)} cy={toY(data[i])} r="4" fill="var(--data-anomaly)" stroke="var(--bg-card)" strokeWidth="1.5" />
        ))}
        {/* X labels */}
        {[0, 7, 14, 21, 29].map(i => (
          <text key={i} x={toX(i)} y={h + 14} textAnchor="middle" fill="var(--text-tertiary)" fontSize="7" fontFamily="'DM Sans'">Mar {i + 1}</text>
        ))}
      </svg>
      <div style={{ display: 'flex', gap: 16, marginTop: 4 }}>
        {[
          { color: m.color, label: metric },
          { color: 'var(--data-secondary)', label: '7d avg' },
          { color: 'var(--text-tertiary)', label: '30d avg', dashed: true },
          { color: 'var(--data-anomaly)', label: 'Anomaly', dot: true },
        ].map(l => (
          <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {l.dot
              ? <div style={{ width: 6, height: 6, borderRadius: '50%', background: l.color }} />
              : <div style={{ width: 10, height: 2, background: l.color, borderRadius: 1, opacity: l.dashed ? 0.5 : 1 }} />
            }
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function InsightsPage() {
  const [metric, setMetric] = useState('Recovery')
  const [days, setDays] = useState(30)

  return (
    <div className="space-y-4">
      <h1 className="animate-fade-in" style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 32, fontWeight: 700 }}>Insights</h1>

      {/* Weekly Digest */}
      <div className="animate-fade-in delay-1">
        <Label>Weekly Digest</Label>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-2">
          {DIGESTS.map(d => (
            <Card key={d.category}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <span style={{ fontSize: 14 }}>{d.icon}</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: d.color, letterSpacing: '0.02em' }}>{d.category}</span>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{d.text}</p>
            </Card>
          ))}
        </div>
      </div>

      {/* Metric Explorer */}
      <Card className="animate-fade-in delay-2">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Label>Metric Explorer</Label>
            <select
              value={metric}
              onChange={e => setMetric(e.target.value)}
              style={{
                background: 'var(--bg-card-elevated)',
                border: '0.5px solid var(--border-subtle)',
                borderRadius: 6,
                padding: '4px 8px',
                fontSize: 12,
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              {Object.keys(METRICS).map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {[30, 60, 90, 180].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                style={{
                  padding: '3px 8px', borderRadius: 5, fontSize: 11, border: 'none', cursor: 'pointer',
                  background: days === d ? 'var(--brand)' : 'var(--bg-card-elevated)',
                  color: days === d ? '#fff' : 'var(--text-secondary)',
                  transition: 'all 150ms',
                }}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
        <MetricExplorerChart metric={metric} />
      </Card>

      {/* Anomaly Feed */}
      <Card className="animate-fade-in delay-3">
        <Label>Anomaly Feed</Label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4 }}>
          {ANOMALIES.map((a, i) => {
            const color = a.severity === 'alert' ? 'var(--status-alert)' : a.severity === 'caution' ? 'var(--status-caution)' : 'var(--status-excellent)'
            const bg = a.severity === 'alert' ? 'var(--status-alert-muted)' : a.severity === 'caution' ? 'var(--status-caution-muted)' : 'var(--status-excellent-muted)'
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: bg,
                  borderLeft: `2px solid ${color}`,
                }}
              >
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: 'var(--text-tertiary)', width: 44, flexShrink: 0 }}>{a.date}</span>
                <span style={{ fontSize: 12, color: 'var(--text-primary)', flex: 1 }}>{a.metric}</span>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, fontWeight: 600, color }}>{a.value}</span>
                <span style={{ fontSize: 10, color, textTransform: 'uppercase', letterSpacing: '0.04em', width: 32 }}>{a.direction === 'high' ? '↑ High' : '↓ Low'}</span>
              </div>
            )
          })}
        </div>
      </Card>

      {/* Correlations */}
      <div className="animate-fade-in delay-4">
        <Label>Correlations (Pearson r)</Label>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-2">
          {[
            { title: 'HRV ↔ Recovery', r: 0.68, desc: 'Same-day' },
            { title: 'Strain → Recovery', r: -0.54, desc: 'Next-day shift' },
            { title: 'Sleep ↔ Body Battery', r: 0.72, desc: 'Same-day' },
          ].map(c => {
            const abs = Math.abs(c.r)
            const strength = abs >= 0.5 ? 'Strong' : abs >= 0.3 ? 'Moderate' : 'Weak'
            const color = abs >= 0.5 ? 'var(--status-excellent)' : abs >= 0.3 ? 'var(--status-caution)' : 'var(--text-tertiary)'
            return (
              <Card key={c.title}>
                <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>{c.title}</p>
                <p style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 8 }}>{c.desc}</p>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 24, fontWeight: 700, color }}>
                    {c.r > 0 ? '+' : ''}{c.r.toFixed(2)}
                  </span>
                  <span style={{ fontSize: 11, color }}>{strength}</span>
                </div>
                {/* Visual bar */}
                <div style={{ marginTop: 8, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${abs * 100}%`, background: color, borderRadius: 2, transition: 'width 500ms ease-out' }} />
                </div>
              </Card>
            )
          })}
        </div>
      </div>
    </div>
  )
}
