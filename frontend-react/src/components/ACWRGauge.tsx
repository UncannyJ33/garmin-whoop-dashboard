/**
 * ACWRGauge — horizontal bar showing acute:chronic workload ratio zones.
 *
 * Design spec §3.9:
 * - Horizontal bar, 5 zone segments (ACWR zone colors)
 * - 10-12px height
 * - White 2px vertical indicator at current position
 * - Ratio number above (20px 600), zone name below (13px zone color)
 * - One-line interpretation sentence below
 */

import { useEffect, useState } from 'react'

interface ACWRGaugeProps {
  acwr: number | null
  zone?: string | null
  zoneDescription?: string | null
  className?: string
}

// ACWR zone definitions matching the design spec
const ZONES = [
  { label: 'Detraining',   min: 0,   max: 0.6,  color: 'rgba(255,255,255,0.12)', textColor: 'rgba(255,255,255,0.40)' },
  { label: 'Maintenance',  min: 0.6, max: 0.8,  color: 'rgba(37,99,255,0.25)',   textColor: 'var(--brand)' },
  { label: 'Sweet Spot',   min: 0.8, max: 1.3,  color: 'rgba(29,158,117,0.30)',  textColor: 'var(--status-excellent)' },
  { label: 'Overreaching', min: 1.3, max: 1.5,  color: 'rgba(186,117,23,0.30)',  textColor: 'var(--status-caution)' },
  { label: 'Danger',       min: 1.5, max: 2.2,  color: 'rgba(216,90,48,0.30)',   textColor: 'var(--status-alert)' },
]

const SCALE_MIN = 0
const SCALE_MAX = 2.2

function zoneOf(acwr: number) {
  return ZONES.find(z => acwr >= z.min && acwr < z.max) ?? ZONES[ZONES.length - 1]
}

/** % position of a value on the gauge (0–100) */
function pct(v: number) {
  return Math.min(100, Math.max(0, ((v - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100))
}

/** Width % of each zone segment */
function segWidth(z: typeof ZONES[0]) {
  return pct(z.max) - pct(z.min)
}

export function ACWRGauge({ acwr, zone, zoneDescription, className = '' }: ACWRGaugeProps) {
  const currentZone = acwr !== null ? zoneOf(acwr) : null
  const targetPosition = acwr !== null ? pct(acwr) : null

  const [animatedPosition, setAnimatedPosition] = useState<number | null>(null)
  useEffect(() => {
    if (targetPosition === null) { setAnimatedPosition(null); return }
    setAnimatedPosition(0)
    const id = requestAnimationFrame(() => setAnimatedPosition(targetPosition))
    return () => cancelAnimationFrame(id)
  }, [targetPosition])

  const position = animatedPosition

  // Use the API zone label if provided, otherwise derive from the range
  const zoneName = zone
    ? zone.charAt(0).toUpperCase() + zone.slice(1).replace(/_/g, ' ')
    : currentZone?.label ?? ''

  const zoneColor = currentZone?.textColor ?? 'var(--text-secondary)'

  return (
    <div className={className}>
      {/* Ratio number + zone name */}
      <div className="flex items-baseline justify-between mb-2">
        <div>
          {acwr !== null ? (
            <span
              style={{
                fontSize:           20,
                fontWeight:         600,
                color:              zoneColor,
                fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {acwr.toFixed(2)}x
            </span>
          ) : (
            <span className="skeleton inline-block w-16 h-5 rounded" />
          )}
        </div>
        <span className="text-xs font-medium" style={{ color: zoneColor }}>
          {zoneName}
        </span>
      </div>

      {/* Bar */}
      <div className="relative" style={{ height: 12 }}>
        {/* Zone segments */}
        <div className="flex h-full w-full overflow-hidden rounded-full">
          {ZONES.map((z, i) => (
            <div
              key={i}
              style={{
                width:           `${segWidth(z)}%`,
                backgroundColor: z.color,
                flexShrink:      0,
              }}
            />
          ))}
        </div>

        {/* Vertical indicator */}
        {position !== null && (
          <div
            style={{
              position:   'absolute',
              top:        -4,
              bottom:     -4,
              left:       `${position}%`,
              width:      2,
              background: 'rgba(255,255,255,0.90)',
              borderRadius: 2,
              transform:  'translateX(-50%)',
              boxShadow:  '0 0 4px rgba(255,255,255,0.4)',
              transition: 'left 500ms ease-out',
            }}
          />
        )}
      </div>

      {/* Zone label beneath bar at position */}
      <div className="relative mt-1.5" style={{ height: 16 }}>
        {position !== null && (
          <span
            className="absolute text-xs font-medium"
            style={{
              left:       `${position}%`,
              transform:  'translateX(-50%)',
              color:      'var(--text-tertiary)',
              whiteSpace: 'nowrap',
              transition: 'left 500ms ease-out',
            }}
          >
            {acwr?.toFixed(2)}
          </span>
        )}
      </div>

      {/* Interpretation sentence */}
      {zoneDescription && (
        <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
          {zoneDescription}
        </p>
      )}
    </div>
  )
}
