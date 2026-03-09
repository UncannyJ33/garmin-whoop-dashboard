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
  color?: string
  formatValue?: (v: number) => string
}

interface TooltipPayloadEntry {
  name: string
  value: number | null
  color: string
}

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
    <div className="rounded-xl border border-surface-border bg-surface-overlay px-3 py-2 shadow-xl text-xs space-y-1">
      <p className="text-slate-400 font-medium">{label}</p>
      {payload.map((entry) =>
        entry.value !== null && entry.value !== undefined ? (
          <p key={entry.name} style={{ color: entry.color }} className="font-mono">
            {entry.name}: {fmt(entry.value)}{unit ?? ''}
          </p>
        ) : null,
      )}
    </div>
  )
}

// Custom dot — red for anomalies, invisible otherwise (clean line)
function CustomDot(props: {
  cx?: number
  cy?: number
  payload?: TrendDataPoint
  color?: string
}) {
  const { cx, cy, payload, color } = props
  if (!cx || !cy || !payload) return null
  if (payload.isAnomaly) {
    return <Dot cx={cx} cy={cy} r={4} fill="#ef4444" stroke="#ef4444" strokeWidth={1} />
  }
  // Invisible dot for hover hit area
  return <Dot cx={cx} cy={cy} r={2} fill={color ?? '#60a5fa'} fillOpacity={0.3} stroke="none" />
}

export function TrendChart({
  data,
  metricName,
  unit,
  showRollingAvg = true,
  height = 220,
  color = '#60a5fa',
  formatValue,
}: TrendChartProps) {
  if (!data.length) {
    return (
      <div
        className="flex items-center justify-center rounded-xl bg-surface-overlay text-slate-500 text-sm"
        style={{ height }}
      >
        No data
      </div>
    )
  }

  const fmt = formatValue ?? ((v: number) => v.toFixed(1))

  // Format date label: "Mar 9"
  const formatDate = (iso: string) => {
    // Append T12:00:00 so date-only strings are parsed as local noon, not UTC midnight.
    // Without this, 'YYYY-MM-DD' parses as UTC 00:00 and shifts one day back in US timezones.
    const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -8 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />

        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
          minTickGap={40}
        />

        <YAxis
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={fmt}
          width={36}
        />

        <Tooltip
          content={
            <CustomTooltip unit={unit} formatValue={formatValue} />
          }
          labelFormatter={formatDate}
        />

        {/* 30d avg — subtle dashed */}
        {showRollingAvg && (
          <Line
            type="monotone"
            dataKey="avg30d"
            name="30d avg"
            stroke="#94a3b8"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            connectNulls
          />
        )}

        {/* 7d avg — prominent */}
        {showRollingAvg && (
          <Line
            type="monotone"
            dataKey="avg7d"
            name="7d avg"
            stroke="#fb923c"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        )}

        {/* Raw values */}
        <Line
          type="monotone"
          dataKey="value"
          name={metricName}
          stroke={color}
          strokeWidth={1.5}
          dot={<CustomDot color={color} />}
          activeDot={{ r: 4, fill: color }}
          connectNulls={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
