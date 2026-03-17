/**
 * ReadinessArcGauge — semi-circular arc gauge for the morning readiness hero card.
 *
 * Design spec §3.1:
 * - ~260px wide, 180° span, 6-8px stroke
 * - 4 color-banded zone segments with 2-3px gaps
 * - Progress fill: solid status color, rounded linecaps
 * - Score (58-64px 700, status color) + badge centered inside arc
 * - Radial glow behind score at 6-8% opacity
 * - Animate fill from 0 on first load (600ms)
 */

import { useEffect, useRef, useState } from 'react'
import { StatusBadge } from './StatusBadge'
import type { ReadinessLevel } from './StatusBadge'

// Arc geometry
const CX = 130        // center x
const CY = 135        // center y (bottom of arc)
const R  = 110        // radius
const SW = 7          // stroke width
const SEMI_C = Math.PI * R  // semi-circumference ≈ 345.6px

// Score → status color and glow
function scoreToStatus(score: number): {
  color: string
  glow: string
  level: ReadinessLevel
} {
  if (score >= 80) return {
    color: 'var(--status-excellent)',
    glow:  'rgba(29,158,117,0.07)',
    level: 'Push hard',
  }
  if (score >= 60) return {
    color: 'var(--status-excellent)',
    glow:  'rgba(29,158,117,0.07)',
    level: 'Train normally',
  }
  if (score >= 40) return {
    color: 'var(--status-caution)',
    glow:  'rgba(186,117,23,0.07)',
    level: 'Go easy',
  }
  return {
    color: 'var(--status-alert)',
    glow:  'rgba(216,90,48,0.08)',
    level: 'Rest day',
  }
}

// Override the level if explicitly provided
function levelToColor(level: ReadinessLevel): string {
  switch (level) {
    case 'Push hard':     return 'var(--status-excellent)'
    case 'Train normally':return 'var(--status-excellent)'
    case 'Go easy':       return 'var(--status-caution)'
    case 'Rest day':      return 'var(--status-alert)'
  }
}

/** Cartesian point on the arc for a given t ∈ [0,1] (0 = left, 1 = right). */
function ptAt(t: number): [number, number] {
  const angle = (1 - t) * Math.PI
  return [
    CX + R * Math.cos(angle),
    CY - R * Math.sin(angle),
  ]
}

/** SVG arc path from t1 to t2 (counter-clockwise = through the top). */
function arcSeg(t1: number, t2: number): string {
  const [x1, y1] = ptAt(t1)
  const [x2, y2] = ptAt(t2)
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 0 0 ${x2.toFixed(2)} ${y2.toFixed(2)}`
}

// 4 background zone segments with ~1% gap between them
const GAP = 0.012
const ZONES = [
  { t1: 0 + GAP,       t2: 0.25 - GAP,   color: 'rgba(216,90,48,0.17)',    },  // 0–25% coral
  { t1: 0.25 + GAP,    t2: 0.50 - GAP,   color: 'rgba(186,117,23,0.14)',   },  // 25–50% amber
  { t1: 0.50 + GAP,    t2: 0.75 - GAP,   color: 'rgba(29,158,117,0.11)',   },  // 50–75% teal
  { t1: 0.75 + GAP,    t2: 1.00 - GAP,   color: 'rgba(29,158,117,0.14)',   },  // 75–100% bright teal
]

export interface ReadinessArcGaugeProps {
  score: number | null
  recommendation?: ReadinessLevel | null
  confidence?: number | null
  sourcesText?: string | null
  /** If true, skip the 600ms entrance animation (subsequent visits). */
  skipAnimation?: boolean
}

export function ReadinessArcGauge({
  score,
  recommendation,
  confidence,
  sourcesText,
  skipAnimation = false,
}: ReadinessArcGaugeProps) {
  const displayScore = score ?? 0
  const { color, glow, level } = scoreToStatus(displayScore)
  const badgeLevel = recommendation ?? level

  // Animated dashoffset: starts full (hidden), transitions to target
  const [dashOffset, setDashOffset] = useState(SEMI_C)
  const mounted = useRef(false)

  useEffect(() => {
    if (skipAnimation || mounted.current) {
      // Subsequent renders or skip: set immediately
      setDashOffset(SEMI_C * (1 - displayScore / 100))
      return
    }
    // First mount: animate from 0 → target
    const id = requestAnimationFrame(() => {
      setDashOffset(SEMI_C * (1 - displayScore / 100))
    })
    mounted.current = true
    return () => cancelAnimationFrame(id)
  }, [displayScore, skipAnimation])

  const scoreColor = recommendation ? levelToColor(recommendation) : color

  return (
    <div className="flex flex-col items-center gap-3">
      {/* MORNING READINESS label */}
      <p
        className="text-xs uppercase tracking-widest"
        style={{ color: 'var(--text-tertiary)', letterSpacing: '0.1em' }}
      >
        Morning Readiness
      </p>

      {/* Arc gauge */}
      <div className="relative" style={{ width: 260, height: 160 }}>
        {/* Radial glow behind score */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            width:  280,
            height: 280,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${glow} 0%, transparent 65%)`,
            top:  '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            pointerEvents: 'none',
          }}
        />

        <svg
          viewBox="0 0 260 160"
          width="260"
          height="160"
          aria-label={`Readiness score ${displayScore}`}
          style={{ overflow: 'visible' }}
        >
          {/* Zone background segments */}
          {ZONES.map((z, i) => (
            <path
              key={i}
              d={arcSeg(z.t1, z.t2)}
              stroke={z.color}
              strokeWidth={SW}
              strokeLinecap="round"
              fill="none"
            />
          ))}

          {/* Progress fill */}
          {score !== null && (
            <path
              d={arcSeg(0, 1)}
              stroke={scoreColor}
              strokeWidth={SW}
              strokeLinecap="round"
              fill="none"
              strokeOpacity={0.88}
              strokeDasharray={`${SEMI_C} ${SEMI_C}`}
              strokeDashoffset={dashOffset}
              style={{
                transition: skipAnimation ? 'none' : 'stroke-dashoffset 600ms ease-out',
              }}
            />
          )}
        </svg>

        {/* Score + badge centered inside arc */}
        <div
          className="absolute flex flex-col items-center gap-2"
          style={{
            left: '50%',
            top:  '42%',
            transform: 'translate(-50%, -50%)',
          }}
        >
          {score !== null ? (
            <span
              style={{
                fontSize:   62,
                fontWeight: 700,
                lineHeight: 1,
                color:      scoreColor,
                fontFamily: "'Geist', system-ui, sans-serif",
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {Math.round(score)}
            </span>
          ) : (
            <div className="skeleton w-16 h-14 rounded-lg" />
          )}

          <StatusBadge level={badgeLevel} />
        </div>
      </div>

      {/* Sources text */}
      {sourcesText && (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {sourcesText}
        </p>
      )}

      {/* Confidence */}
      {confidence !== null && confidence !== undefined && (
        <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
          {Math.round(confidence * 100)}% confidence
        </p>
      )}
    </div>
  )
}
