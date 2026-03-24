/**
 * TrendChart — recharts LineChart styled to the design system.
 *
 * Design spec §3.3 + §7:
 * - Transparent background (inherits card)
 * - Horizontal-only grid at --chart-grid
 * - No axis lines, no ticks
 * - Primary line: --data-primary teal 2px
 * - 7d avg: --data-secondary amber 1.5px
 * - 30d avg: --data-tertiary 1px
 * - Anomaly markers: --data-anomaly coral 6px circles
 * - Custom tooltip: bg-card-elevated, border-hover, 8px radius
 * - Sparkline variant: no axes/grid, 200×48px, value+arrow at right end
 */

import {
  CartesianGrid,
  Dot,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export interface TrendDataPoint {
  date: string
  value: number | null
  avg7d?: number | null
  avg30d?: number | null
  isAnomaly?: boolean
}

interface TrendChartProps {
  data: TrendDataPoint[]
  metricName: string
  unit?: string
  showRollingAvg?: boolean
  height?: number
  /** Primary line color — defaults to --data-primary teal */
  color?: string
  formatValue?: (v: number) => string
  /** Renders a compact sparkline with no axes */
  sparkline?: boolean
}

interface TooltipPayloadEntry {
  name: string
  value: number | null
  color: string
}

// ── Custom tooltip ─────────────────────────────────────────────────────────

function CustomTooltip({
  active,
  payload,
  label,
  unit,
  formatValue,
}: {
  active?: boolean
  payload?: TooltipPayloadEntry[]
  label?: string
  unit?: string
  formatValue?: (v: number) => string
}) {
  if (!active || !payload?.length) return null

  const fmt = formatValue ?? ((v: number) => v.toFixed(1))

  return (
    <div
      style={{
        background:   'var(--bg-card-elevated)',
        border:       '0.5px solid var(--border-hover)',
        borderRadius: 8,
        padding:      '8px 12px',
        fontSize:     12,
        minWidth:     100,
        boxShadow:    '0 4px 16px rgba(0,0,0,0.4)',
      }}
    >
      <p style={{ color: 'var(--text-secondary)', fontWeight: 500, marginBottom: 4 }}>
        {label}
      </p>
      {payload.map(entry =>
        entry.value !== null && entry.value !== undefined ? (
          <p
            key={entry.name}
            style={{
              color:              entry.color,
              fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {entry.name}: {fmt(entry.value)}{unit ?? ''}
          </p>
        ) : null,
      )}
    </div>
  )
}

// ── Custom anomaly dot ─────────────────────────────────────────────────────

function CustomDot(props: {
  cx?: number
  cy?: number
  payload?: TrendDataPoint
  color?: string
}) {
  const { cx, cy, payload, color } = props
  if (!cx || !cy || !payload) return null
  if (payload.isAnomaly) {
    return (
      <Dot
        cx={cx}
        cy={cy}
        r={3}
        fill="var(--data-anomaly)"
        stroke="var(--data-anomaly)"
        strokeWidth={0}
      />
    )
  }
  return <Dot cx={cx} cy={cy} r={2} fill={color ?? 'var(--data-primary)'} fillOpacity={0.25} stroke="none" />
}

// ── Date formatter ─────────────────────────────────────────────────────────

function formatDate(iso: string) {
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Sparkline variant ──────────────────────────────────────────────────────

function Sparkline({
  data,
  color,
  formatValue,
  unit,
}: {
  data: TrendDataPoint[]
  color: string
  formatValue?: (v: number) => string
  unit?: string
}) {
  const lastPoint = [...data].reverse().find(d => d.value !== null)
  const secondLast = data.filter(d => d.value !== null).slice(-2)[0]

  let arrow = '→'
  let arrowColor = 'var(--text-tertiary)'
  if (lastPoint && secondLast && lastPoint.value !== null && secondLast.value !== null) {
    if (lastPoint.value > secondLast.value + 0.5) { arrow = '↑'; arrowColor = 'var(--data-primary)' }
    else if (lastPoint.value < secondLast.value - 0.5) { arrow = '↓'; arrowColor = 'var(--data-anomaly)' }
  }

  const fmt = formatValue ?? ((v: number) => v.toFixed(1))

  return (
    <div className="flex items-center gap-2">
      <ResponsiveContainer width={200} height={48}>
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 4, left: 4 }}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-1">
        {lastPoint?.value !== null && lastPoint?.value !== undefined && (
          <span style={{ fontSize: 13, color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
            {fmt(lastPoint.value)}{unit ?? ''}
          </span>
        )}
        <span style={{ fontSize: 13, color: arrowColor }}>{arrow}</span>
      </div>
    </div>
  )
}

// ── Main chart ─────────────────────────────────────────────────────────────

export function TrendChart({
  data,
  metricName,
  unit,
  showRollingAvg = true,
  height = 220,
  color = 'var(--data-primary)',
  formatValue,
  sparkline = false,
}: TrendChartProps) {
  if (!data.length) {
    return (
      <div
        className="flex items-center justify-center rounded-xl text-sm"
        style={{
          height,
          background: 'var(--bg-card-elevated)',
          color:      'var(--text-tertiary)',
        }}
      >
        No data
      </div>
    )
  }

  if (sparkline) {
    return <Sparkline data={data} color={color} formatValue={formatValue} unit={unit} />
  }

  const fmt = formatValue ?? ((v: number) => v.toFixed(1))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid
          strokeDasharray="0"
          vertical={false}
          stroke="var(--chart-grid)"
        />

        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 11, fill: 'var(--chart-axis)', fontFamily: 'DM Sans, system-ui, sans-serif' }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          minTickGap={40}
        />

        <YAxis
          tick={{ fontSize: 11, fill: 'var(--chart-axis)', fontFamily: 'DM Sans, system-ui, sans-serif' }}
          tickLine={false}
          axisLine={false}
          tickFormatter={fmt}
          width={36}
        />

        <Tooltip
          content={<CustomTooltip unit={unit} formatValue={formatValue} />}
          labelFormatter={formatDate}
          cursor={{ stroke: 'var(--border-hover)', strokeWidth: 1 }}
        />

        {/* 30d avg — subtle */}
        {showRollingAvg && (
          <Line
            type="monotone"
            dataKey="avg30d"
            name="30d avg"
            stroke="var(--data-tertiary)"
            strokeWidth={1}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
          />
        )}

        {/* 7d avg — amber */}
        {showRollingAvg && (
          <Line
            type="monotone"
            dataKey="avg7d"
            name="7d avg"
            stroke="var(--data-secondary)"
            strokeWidth={1.5}
            dot={false}
            connectNulls
          />
        )}

        {/* Raw values — primary teal */}
        <Line
          type="monotone"
          dataKey="value"
          name={metricName}
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
          dot={<CustomDot color={color} />}
          activeDot={{ r: 4, fill: color, stroke: 'var(--bg-card)', strokeWidth: 2 }}
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
