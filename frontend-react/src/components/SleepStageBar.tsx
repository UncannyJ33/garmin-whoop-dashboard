import { useState } from 'react'

interface SleepStageBarProps {
  deepMinutes: number | null
  lightMinutes: number | null
  remMinutes: number | null
  awakeMinutes: number | null
}

interface Stage {
  key: string
  label: string
  minutes: number
  color: string
  bg: string
}

function fmtDur(min: number): string {
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export function SleepStageBar({
  deepMinutes,
  lightMinutes,
  remMinutes,
  awakeMinutes,
}: SleepStageBarProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)

  const stages: Stage[] = [
    { key: 'deep',  label: 'Deep',  minutes: deepMinutes  ?? 0, color: '#4f46e5', bg: 'bg-indigo-500' },
    { key: 'light', label: 'Light', minutes: lightMinutes ?? 0, color: '#60a5fa', bg: 'bg-blue-400' },
    { key: 'rem',   label: 'REM',   minutes: remMinutes   ?? 0, color: '#c084fc', bg: 'bg-purple-400' },
    { key: 'awake', label: 'Awake', minutes: awakeMinutes ?? 0, color: '#94a3b8', bg: 'bg-slate-400' },
  ].filter(s => s.minutes > 0)

  const total = stages.reduce((s, st) => s + st.minutes, 0)

  if (total === 0) {
    return <div className="h-6 rounded-full skeleton" />
  }

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-6 w-full overflow-hidden rounded-full gap-px">
        {stages.map(stage => (
          <div
            key={stage.key}
            className={`${stage.bg} cursor-default transition-opacity duration-150 relative`}
            style={{
              width: `${(stage.minutes / total) * 100}%`,
              opacity: hoveredKey && hoveredKey !== stage.key ? 0.4 : 1,
            }}
            onMouseEnter={() => setHoveredKey(stage.key)}
            onMouseLeave={() => setHoveredKey(null)}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {stages.map(stage => (
          <div
            key={stage.key}
            className="flex items-center gap-1.5 cursor-default"
            onMouseEnter={() => setHoveredKey(stage.key)}
            onMouseLeave={() => setHoveredKey(null)}
          >
            <span
              className="h-2 w-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: stage.color }}
            />
            <span className="text-2xs text-slate-400">
              {stage.label}{' '}
              <span
                className={`font-mono transition-colors ${
                  hoveredKey === stage.key ? 'text-slate-800 dark:text-slate-100' : 'text-slate-500'
                }`}
              >
                {fmtDur(stage.minutes)}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
