function Card({ children, style = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <div style={{ background: 'var(--bg-card)', border: '0.5px solid var(--border-subtle)', borderRadius: 12, padding: 16, ...style }}>{children}</div>
}
function Label({ children }: { children: React.ReactNode }) {
  return <p style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.02em', color: 'var(--text-secondary)', marginBottom: 6 }}>{children}</p>
}
function Mono({ children, size = 28 }: { children: React.ReactNode; size?: number }) {
  return <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: size, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>{children}</span>
}

// ── Mock data ────────────────────────────────────────────────────────────────

const SLEEP_TREND = Array.from({ length: 30 }, (_, i) => {
  const base = 420 + Math.sin(i * 0.3) * 30 + (Math.random() - 0.5) * 40
  const deep = base * (0.18 + Math.random() * 0.06)
  const rem = base * (0.2 + Math.random() * 0.04)
  const awake = 10 + Math.random() * 15
  return { day: i + 1, total: Math.round(base), deep: Math.round(deep), rem: Math.round(rem), light: Math.round(base - deep - rem - awake), awake: Math.round(awake), isAnomaly: i === 8 || i === 22 }
})

const ROLLING_7D = SLEEP_TREND.map((_, i) => {
  const window = SLEEP_TREND.slice(Math.max(0, i - 6), i + 1)
  return Math.round(window.reduce((s, d) => s + d.total, 0) / window.length)
})

// ── Charts ───────────────────────────────────────────────────────────────────

function SleepTrendChart() {
  const maxVal = Math.max(...SLEEP_TREND.map(d => d.total)) * 1.05
  const minVal = Math.min(...SLEEP_TREND.map(d => d.total)) * 0.9
  const range = maxVal - minVal
  const w = 600, h = 160, pad = 30

  return (
    <svg viewBox={`0 0 ${w} ${h + 20}`} width="100%" height={h + 20} preserveAspectRatio="xMidYMid meet">
      {/* Grid */}
      {[0, 0.25, 0.5, 0.75, 1].map(pct => {
        const y = h - pct * (h - 10) - 5
        const val = (minVal + pct * range) / 60
        return (
          <g key={pct}>
            <line x1={pad} y1={y} x2={w} y2={y} stroke="rgba(255,255,255,0.04)" strokeWidth="0.5" />
            <text x={pad - 4} y={y + 3} textAnchor="end" fill="var(--text-tertiary)" fontSize="7" fontFamily="'IBM Plex Mono'">{val.toFixed(1)}h</text>
          </g>
        )
      })}

      {/* Bars */}
      {SLEEP_TREND.map((d, i) => {
        const x = pad + (i / (SLEEP_TREND.length - 1)) * (w - pad) - 6
        const barH = ((d.total - minVal) / range) * (h - 10)
        return (
          <g key={i}>
            <defs>
              <linearGradient id={`bar-${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--data-primary)" stopOpacity="0.6" />
                <stop offset="100%" stopColor="var(--data-primary)" stopOpacity="0.15" />
              </linearGradient>
            </defs>
            <rect x={x} y={h - barH - 5} width={12} height={barH} rx={2} fill={`url(#bar-${i})`} />
          </g>
        )
      })}

      {/* 7d avg line */}
      {(() => {
        const pts = ROLLING_7D.map((v, i) => `${pad + (i / (ROLLING_7D.length - 1)) * (w - pad)},${h - ((v - minVal) / range) * (h - 10) - 5}`).join(' ')
        return <polyline points={pts} fill="none" stroke="var(--data-secondary)" strokeWidth="1.5" strokeDasharray="4 2" strokeLinejoin="round" />
      })()}

      {/* Anomaly dots */}
      {SLEEP_TREND.filter(d => d.isAnomaly).map(d => {
        const x = pad + ((d.day - 1) / (SLEEP_TREND.length - 1)) * (w - pad)
        const y = h - ((d.total - minVal) / range) * (h - 10) - 5
        return <circle key={d.day} cx={x} cy={y} r="4" fill="var(--data-anomaly)" stroke="var(--bg-card)" strokeWidth="1.5" />
      })}

      {/* X labels */}
      {[0, 7, 14, 21, 29].map(i => (
        <text key={i} x={pad + (i / (SLEEP_TREND.length - 1)) * (w - pad)} y={h + 14} textAnchor="middle" fill="var(--text-tertiary)" fontSize="7" fontFamily="'DM Sans'">
          Mar {i + 1}
        </text>
      ))}
    </svg>
  )
}

function SleepStageArea() {
  const w = 600, h = 120, pad = 0
  const stages = ['deep', 'rem', 'light', 'awake'] as const
  const colors = { deep: '#1e7a5a', rem: '#7a5ea0', light: '#3d6b9e', awake: '#3d3d3d' }

  // Build stacked points
  const stacked = SLEEP_TREND.map(d => {
    const total = d.deep + d.rem + d.light + d.awake
    return {
      deep: d.deep / total,
      rem: (d.deep + d.rem) / total,
      light: (d.deep + d.rem + d.light) / total,
      awake: 1,
    }
  })

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="xMidYMid meet">
      <defs>
        {stages.map(s => (
          <linearGradient key={s} id={`stage-${s}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colors[s]} stopOpacity="0.7" />
            <stop offset="100%" stopColor={colors[s]} stopOpacity="0.15" />
          </linearGradient>
        ))}
      </defs>
      {/* Render in reverse order (awake on top) */}
      {[...stages].reverse().map(stage => {
        const prevStage = stages[stages.indexOf(stage) - 1]
        const topPts = stacked.map((d, i) => `${pad + (i / (stacked.length - 1)) * (w - pad)},${h - d[stage] * h}`).join(' ')
        const bottomPts = stacked.map((d, i) => `${pad + (i / (stacked.length - 1)) * (w - pad)},${h - (prevStage ? d[prevStage] : 0) * h}`).reverse().join(' ')
        return <polygon key={stage} points={`${topPts} ${bottomPts}`} fill={`url(#stage-${stage})`} />
      })}
    </svg>
  )
}

function CorrelationCard({ title, r, high, low }: { title: string; r: number; high: string; low: string }) {
  const strength = Math.abs(r) >= 0.5 ? 'Strong' : Math.abs(r) >= 0.3 ? 'Moderate' : 'Weak'
  const color = Math.abs(r) >= 0.5 ? 'var(--status-excellent)' : Math.abs(r) >= 0.3 ? 'var(--status-caution)' : 'var(--text-tertiary)'
  return (
    <Card>
      <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8 }}>{title}</p>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700, color }}>{r > 0 ? '+' : ''}{r.toFixed(2)}</span>
        <span style={{ fontSize: 11, color }}>{strength}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: 'var(--text-tertiary)' }}>High strain nights</span>
          <span style={{ color: 'var(--text-primary)', fontFamily: "'IBM Plex Mono', monospace" }}>{high}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: 'var(--text-tertiary)' }}>Normal nights</span>
          <span style={{ color: 'var(--text-primary)', fontFamily: "'IBM Plex Mono', monospace" }}>{low}</span>
        </div>
      </div>
    </Card>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function RecoveryPage() {
  const lastNight = SLEEP_TREND[SLEEP_TREND.length - 1]
  const totalHrs = (lastNight.total / 60).toFixed(1)

  const stages = [
    { label: 'Deep', min: lastNight.deep, color: '#1e7a5a' },
    { label: 'Light', min: lastNight.light, color: '#3d6b9e' },
    { label: 'REM', min: lastNight.rem, color: '#7a5ea0' },
    { label: 'Awake', min: lastNight.awake, color: '#3d3d3d' },
  ]
  const stageTotal = stages.reduce((s, st) => s + st.min, 0)

  return (
    <div className="space-y-4">
      <h1 className="animate-fade-in" style={{ fontFamily: "'Barlow Condensed', sans-serif", fontSize: 32, fontWeight: 700 }}>Recovery</h1>

      {/* Hero */}
      <Card className="animate-fade-in delay-1" style={{ borderRadius: 18, padding: '24px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
          <div>
            <Label>Last Night</Label>
            <Mono size={36}>{totalHrs}h</Mono>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>Performance</span>
            <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700, color: 'var(--status-excellent)' }}>89%</p>
          </div>
        </div>

        {/* Stage bar */}
        <div style={{ display: 'flex', height: 22, borderRadius: 11, overflow: 'hidden', gap: 2, marginBottom: 8 }}>
          {stages.map(s => (
            <div key={s.label} style={{ flex: `0 0 ${(s.min / stageTotal) * 100}%`, background: s.color, borderRadius: 6 }} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {stages.map(s => (
            <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 6, height: 6, borderRadius: 2, background: s.color }} />
              <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{s.label}</span>
              <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontFamily: "'IBM Plex Mono', monospace" }}>{Math.floor(s.min / 60)}h {s.min % 60}m</span>
            </div>
          ))}
        </div>

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-4">
          {[
            { label: 'Efficiency', value: '94%', status: 'good' },
            { label: 'Deep %', value: `${Math.round(lastNight.deep / lastNight.total * 100)}%`, status: 'good' },
            { label: 'REM %', value: `${Math.round(lastNight.rem / lastNight.total * 100)}%`, status: 'good' },
            { label: 'Sleep Debt', value: '1.2h', status: 'caution' },
          ].map(m => (
            <div key={m.label} style={{
              padding: '8px 12px',
              borderLeft: `2px solid ${m.status === 'good' ? 'var(--status-excellent)' : 'var(--status-caution)'}`,
              borderRadius: '0 6px 6px 0',
              background: m.status === 'good' ? 'var(--status-excellent-muted)' : 'var(--status-caution-muted)',
            }}>
              <p style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 2 }}>{m.label}</p>
              <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>{m.value}</p>
            </div>
          ))}
        </div>
      </Card>

      {/* Sleep Trends */}
      <Card className="animate-fade-in delay-2">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <Label>Sleep Duration — 30 Days</Label>
          <div style={{ display: 'flex', gap: 12 }}>
            {[
              { color: 'var(--data-primary)', label: 'Duration' },
              { color: 'var(--data-secondary)', label: '7d Avg', dashed: true },
              { color: 'var(--data-anomaly)', label: 'Anomaly', dot: true },
            ].map(l => (
              <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {l.dot ? <div style={{ width: 6, height: 6, borderRadius: '50%', background: l.color }} /> : <div style={{ width: 10, height: 2, background: l.color, borderRadius: 1, ...(l.dashed ? { backgroundImage: `repeating-linear-gradient(90deg, ${l.color} 0 3px, transparent 3px 5px)`, background: 'none' } : {}) }} />}
                <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{l.label}</span>
              </div>
            ))}
          </div>
        </div>
        <SleepTrendChart />
      </Card>

      {/* Stage Distribution */}
      <Card className="animate-fade-in delay-3">
        <Label>Sleep Stage Distribution</Label>
        <SleepStageArea />
        <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
          {[
            { label: 'Deep', color: '#1e7a5a' },
            { label: 'REM', color: '#7a5ea0' },
            { label: 'Light', color: '#3d6b9e' },
            { label: 'Awake', color: '#3d3d3d' },
          ].map(s => (
            <div key={s.label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
              <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{s.label}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Correlations */}
      <div className="animate-fade-in delay-4">
        <Label>Training ↔ Sleep Correlations</Label>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-2">
          <CorrelationCard title="Strain → Total Sleep" r={0.62} high="7.8h avg" low="7.1h avg" />
          <CorrelationCard title="Strain → Deep Sleep %" r={0.41} high="21% avg" low="18% avg" />
          <CorrelationCard title="Sleep → Recovery" r={0.71} high="78 avg" low="61 avg" />
        </div>
      </div>

      {/* Consistency */}
      <Card className="animate-fade-in delay-5">
        <Label>Sleep Consistency</Label>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-2">
          {[
            { label: 'Avg Bedtime', value: '10:45 PM' },
            { label: 'Avg Wake', value: '6:12 AM' },
            { label: 'Variability', value: '±32 min' },
            { label: 'Trend', value: '→ Stable' },
          ].map(m => (
            <div key={m.label}>
              <p style={{ fontSize: 10, color: 'var(--text-tertiary)', marginBottom: 2 }}>{m.label}</p>
              <p style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{m.value}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
