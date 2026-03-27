import { useState, useEffect } from 'react'

// ── Mock data ────────────────────────────────────────────────────────────────
const SPARKLINE_DATA = {
  hrv: [48, 52, 55, 50, 61, 58, 63, 59, 65, 62, 58, 64, 60, 67, 63, 61, 59, 62, 66, 63, 68, 65, 62, 67, 64, 69, 66, 63, 67, 62],
  sleep: [6.8, 7.2, 6.5, 7.1, 7.4, 6.9, 7.6, 7.0, 7.3, 6.7, 7.5, 7.1, 6.8, 7.2, 7.6, 7.0, 7.3, 6.9, 7.4, 7.1, 7.5, 6.8, 7.2, 7.4, 7.0, 7.6, 7.1, 7.3, 6.9, 7.4],
  strain: [8.2, 12.1, 6.5, 14.3, 9.8, 11.2, 7.6, 13.5, 10.1, 8.9, 15.2, 6.8, 12.4, 9.1, 11.8, 7.3, 14.1, 8.5, 10.9, 13.2, 7.8, 11.5, 9.4, 12.7, 8.1, 14.8, 10.3, 11.1, 9.6, 12.8],
}

// ── Components ───────────────────────────────────────────────────────────────

function Card({ children, className = '', style = {} }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={className} style={{ background: 'var(--bg-card)', border: '0.5px solid var(--border-subtle)', borderRadius: 12, padding: '16px', ...style }}>
      {children}
    </div>
  )
}

function Mono({ children, size = 28 }: { children: React.ReactNode; size?: number }) {
  return <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: size, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>{children}</span>
}

function Label({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.02em', color: 'var(--text-secondary)', marginBottom: 4 }}>{children}</p>
}

function MiniSparkline({ data, color, height = 40 }: { data: number[]; color: string; height?: number }) {
  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const w = 100
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * w},${height - ((v - min) / range) * (height - 4) - 2}`).join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

function ReadinessArc({ score }: { score: number }) {
  const [animScore, setAnimScore] = useState(0)
  useEffect(() => { const t = setTimeout(() => setAnimScore(score), 100); return () => clearTimeout(t) }, [score])

  const color = score >= 75 ? 'var(--status-excellent)' : score >= 50 ? 'var(--status-caution)' : 'var(--status-alert)'
  const glowColor = score >= 75 ? 'rgba(93,202,165,0.15)' : score >= 50 ? 'rgba(239,159,39,0.15)' : 'rgba(232,119,90,0.15)'
  const recommendation = score >= 75 ? 'Push hard' : score >= 60 ? 'Train normally' : score >= 45 ? 'Go easy' : 'Rest day'
  const badgeColor = score >= 75 ? 'var(--status-excellent)' : score >= 60 ? 'var(--status-excellent)' : score >= 45 ? 'var(--status-caution)' : 'var(--status-alert)'
  const badgeBg = score >= 75 ? 'var(--status-excellent-muted)' : score >= 60 ? 'var(--status-excellent-muted)' : score >= 45 ? 'var(--status-caution-muted)' : 'var(--status-alert-muted)'

  const cx = 130, cy = 135, r = 110
  const arcLength = Math.PI * r
  const offset = arcLength - (animScore / 100) * arcLength

  const zones = [
    { pct: 0.25, color: 'rgba(232,119,90,0.15)' },
    { pct: 0.25, color: 'rgba(239,159,39,0.12)' },
    { pct: 0.25, color: 'rgba(93,202,165,0.12)' },
    { pct: 0.25, color: 'rgba(93,202,165,0.20)' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
      <p style={{ fontSize: 11, letterSpacing: '0.08em', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>Morning Readiness</p>
      <div style={{ position: 'relative', width: 260, height: 160 }}>
        {/* Radial glow */}
        <div style={{ position: 'absolute', left: '50%', top: '85%', transform: 'translate(-50%, -50%)', width: 140, height: 140, borderRadius: '50%', background: glowColor, filter: 'blur(40px)' }} />

        <svg viewBox="0 0 260 160" width="260" height="160">
          {/* Zone arcs */}
          {zones.map((z, i) => {
            const startAngle = Math.PI + (i * 0.248 + i * 0.005) * Math.PI
            const endAngle = startAngle + 0.248 * Math.PI
            const x1 = cx + r * Math.cos(startAngle)
            const y1 = cy + r * Math.sin(startAngle)
            const x2 = cx + r * Math.cos(endAngle)
            const y2 = cy + r * Math.sin(endAngle)
            return <path key={i} d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`} fill="none" stroke={z.color} strokeWidth="7" strokeLinecap="round" />
          })}
          {/* Progress arc */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none" stroke={color} strokeWidth="7" strokeLinecap="round"
            strokeDasharray={arcLength} strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 600ms ease-out', filter: `drop-shadow(0 0 8px ${glowColor})` }}
          />
          {/* Score */}
          <text x={cx} y={cy - 10} textAnchor="middle" fill="var(--text-primary)" fontFamily="'Barlow Condensed', sans-serif" fontSize="62" fontWeight="700">
            {animScore}
          </text>
        </svg>
      </div>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, color: badgeColor, background: badgeBg, border: `0.5px solid ${badgeColor}33` }}>
        {recommendation}
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>92% confidence</p>
    </div>
  )
}

function ACWRGauge({ acwr }: { acwr: number }) {
  const [pos, setPos] = useState(0)
  useEffect(() => { const t = setTimeout(() => setPos(Math.min(acwr / 2.2, 1) * 100), 200); return () => clearTimeout(t) }, [acwr])

  const zones = [
    { label: 'Detraining', w: 18, color: 'rgba(37,99,255,0.15)' },
    { label: 'Maintenance', w: 18, color: 'rgba(37,99,255,0.25)' },
    { label: 'Sweet Spot', w: 27, color: 'rgba(93,202,165,0.30)' },
    { label: 'Overreaching', w: 22, color: 'rgba(239,159,39,0.25)' },
    { label: 'Danger', w: 15, color: 'rgba(232,119,90,0.25)' },
  ]
  const zone = acwr < 0.8 ? 'Detraining' : acwr < 1.0 ? 'Maintenance' : acwr < 1.3 ? 'Sweet Spot' : acwr < 1.5 ? 'Overreaching' : 'Danger'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
        <Mono size={20}>{acwr.toFixed(2)}</Mono>
        <span style={{ fontSize: 12, color: 'var(--status-excellent)' }}>{zone}</span>
      </div>
      <div style={{ position: 'relative', height: 12, borderRadius: 6, display: 'flex', gap: 2, overflow: 'hidden' }}>
        {zones.map(z => (
          <div key={z.label} style={{ flex: `0 0 ${z.w}%`, background: z.color, borderRadius: 3 }} />
        ))}
        <div style={{ position: 'absolute', left: `${pos}%`, top: -2, width: 2, height: 16, background: '#fff', borderRadius: 1, boxShadow: '0 0 6px rgba(255,255,255,0.4)', transition: 'left 500ms ease-out' }} />
      </div>
    </div>
  )
}

function SleepStageBar() {
  const stages = [
    { label: 'Deep', min: 82, color: '#1e7a5a' },
    { label: 'Light', min: 195, color: '#3d6b9e' },
    { label: 'REM', min: 98, color: '#7a5ea0' },
    { label: 'Awake', min: 18, color: '#3d3d3d' },
  ]
  const total = stages.reduce((s, st) => s + st.min, 0)
  return (
    <div>
      <div style={{ display: 'flex', height: 14, borderRadius: 7, overflow: 'hidden', gap: 2 }}>
        {stages.map(s => (
          <div key={s.label} style={{ flex: `0 0 ${(s.min / total) * 100}%`, background: s.color, borderRadius: 4 }} />
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
        {stages.map(s => (
          <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 6, height: 6, borderRadius: 2, background: s.color }} />
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{s.label} {Math.floor(s.min / 60)}h {s.min % 60}m</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function LimitingFactor({ name, context, severity }: { name: string; context: string; severity: 'alert' | 'caution' }) {
  const color = severity === 'alert' ? 'var(--status-alert)' : 'var(--status-caution)'
  const bg = severity === 'alert' ? 'var(--status-alert-muted)' : 'var(--status-caution-muted)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderLeft: `2px solid ${color}`, borderRadius: '0 6px 6px 0', background: bg }}>
      <span style={{ fontSize: 12, fontWeight: 600, color }}>{name}</span>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{context}</span>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function TodayPage() {
  const [expandedSparkline, setExpandedSparkline] = useState<string | null>(null)

  const sparklines = [
    { key: 'hrv', label: 'HRV', value: '62', unit: ' ms', data: SPARKLINE_DATA.hrv, color: 'var(--data-primary)', arrow: '↑', arrowColor: 'var(--data-primary)' },
    { key: 'sleep', label: 'Sleep', value: '7.4', unit: 'h', data: SPARKLINE_DATA.sleep, color: 'var(--status-excellent)', arrow: '→', arrowColor: 'var(--text-tertiary)' },
    { key: 'strain', label: 'Strain', value: '12.8', unit: '', data: SPARKLINE_DATA.strain, color: 'var(--status-caution)', arrow: '↑', arrowColor: 'var(--data-anomaly)' },
  ]

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Hero — Readiness Arc */}
      <Card className="animate-fade-in" style={{ borderRadius: 18, padding: '24px 20px 20px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
          <ReadinessArc score={78} />
          <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <LimitingFactor name="Sleep Debt" context="Accumulated 1.2h deficit over 3 nights" severity="caution" />
          </div>
        </div>
      </Card>

      {/* Right column */}
      <div className="flex flex-col gap-4 animate-fade-in delay-1">
        {/* Sleep */}
        <Card>
          <Label>Last Night's Sleep</Label>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
            <Mono size={22}>7h 24m</Mono>
            <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>89% perf</span>
          </div>
          <SleepStageBar />
        </Card>

        {/* Sparklines */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {sparklines.map(s => {
            const active = expandedSparkline === s.key
            return (
              <button
                key={s.key}
                onClick={() => setExpandedSparkline(v => v === s.key ? null : s.key)}
                style={{
                  background: 'var(--bg-card)',
                  border: active ? '0.5px solid var(--brand)' : '0.5px solid var(--border-subtle)',
                  borderRadius: 10,
                  padding: '10px 10px 6px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'border-color 150ms',
                }}
              >
                <p style={{ fontSize: 10, letterSpacing: '0.03em', color: 'var(--text-secondary)', marginBottom: 4 }}>{s.label}</p>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 4 }}>
                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
                    {s.value}{s.unit}
                  </span>
                  <span style={{ fontSize: 11, color: s.arrowColor }}>{s.arrow}</span>
                </div>
                <MiniSparkline data={s.data} color={s.color} />
              </button>
            )
          })}
        </div>

        {/* Expanded sparkline */}
        {expandedSparkline && (
          <Card className="animate-fade-in" style={{ padding: '16px 16px 12px' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 12 }}>
              {sparklines.find(s => s.key === expandedSparkline)?.label} — 30 days
            </p>
            <MiniSparkline
              data={SPARKLINE_DATA[expandedSparkline as keyof typeof SPARKLINE_DATA]}
              color={sparklines.find(s => s.key === expandedSparkline)?.color ?? 'var(--data-primary)'}
              height={120}
            />
          </Card>
        )}
      </div>

      {/* Training Load — full width */}
      <Card className="lg:col-span-2 animate-fade-in delay-2">
        <Label>Training Load</Label>
        <ACWRGauge acwr={1.08} />
      </Card>
    </div>
  )
}
