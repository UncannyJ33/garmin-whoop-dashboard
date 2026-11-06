/**
 * SleepStageBar — horizontal stacked bar showing sleep architecture.
 *
 * Design spec §3.5:
 * - Rounded segments, 2px gaps in bg-card color between stages
 * - Compact (12-16px): Today page
 * - Detailed (20-24px): Recovery page
 * - Colors: Deep #4a3d8f, Light #6b7a99, REM #8b5fbf, Awake #4a4a50
 */

import { useState } from 'react'

interface SleepStageBarProps {
  deepMinutes:  number | null
  lightMinutes: number | null
  remMinutes:   number | null
  awakeMinutes: number | null
  /** 'compact' (14px) for Today page, 'detailed' (22px) for Recovery page */
  variant?: 'compact' | 'detailed'
}

const STAGE_CONFIG = [
  { key: 'deep',  label: 'Deep',  color: '#1e7a5a' },
  { key: 'light', label: 'Light', color: '#3d6b9e' },
  { key: 'rem',   label: 'REM',   color: '#7a5ea0' },
  { key: 'awake', label: 'Awake', color: '#3d3d3d' },
]

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
  variant = 'compact',
}: SleepStageBarProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)

  const rawValues: Record<string, number> = {
    deep:  deepMinutes  ?? 0,
    light: lightMinutes ?? 0,
    rem:   remMinutes   ?? 0,
    awake: awakeMinutes ?? 0,
  }

  const stages = STAGE_CONFIG.filter(s => rawValues[s.key] > 0)
  const total  = stages.reduce((sum, s) => sum + rawValues[s.key], 0)

  const barHeight = variant === 'compact' ? 14 : 22

  if (total === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-full text-xs"
        style={{ height: barHeight, backgroundColor: 'var(--bg-card)', color: 'var(--text-muted)', lineHeight: 1 }}
      >
        --
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Stacked bar with 2px gaps between segments */}
      <div
        className="flex w-full overflow-hidden rounded-full"
        style={{ height: barHeight, gap: 2, backgroundColor: 'var(--bg-card)' }}
      >
        {stages.map(stage => (
          <div
            key={stage.key}
            style={{
              width:           `${(rawValues[stage.key] / total) * 100}%`,
              backgroundColor: stage.color,
              opacity:         hoveredKey && hoveredKey !== stage.key ? 0.4 : 1,
              transition:      'opacity 150ms ease',
              cursor:          'default',
              flexShrink:      0,
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
            className="flex items-center gap-1.5 cursor-default whitespace-nowrap"
            onMouseEnter={() => setHoveredKey(stage.key)}
            onMouseLeave={() => setHoveredKey(null)}
          >
            <span
              style={{
                width: 6, height: 6,
                borderRadius: '50%',
                backgroundColor: stage.color,
                display: 'block',
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              {stage.label}{' '}
              <span
                style={{
                  fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
                  fontVariantNumeric: 'tabular-nums',
                  color:              hoveredKey === stage.key
                    ? 'var(--text-primary)'
                    : 'var(--text-tertiary)',
                  transition:         'color 150ms ease',
                }}
              >
                {fmtDur(rawValues[stage.key])}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
