/**
 * StatusBadge — readiness level pill badge.
 *
 * Design spec §3.4 exact color values:
 * | Level          | Background              | Border                  | Text     |
 * | Push hard      | rgba(29,158,117,0.10)   | rgba(29,158,117,0.20)   | #7dd8b8  |
 * | Train normally | rgba(29,158,117,0.08)   | rgba(29,158,117,0.15)   | #7dd8b8  |
 * | Go easy        | rgba(186,117,23,0.10)   | rgba(186,117,23,0.25)   | #efb34e  |
 * | Rest day       | rgba(216,90,48,0.10)    | rgba(216,90,48,0.20)    | #e8916e  |
 *
 * Style: 12-13px, weight 500, 6px radius, 4px 16px padding, 0.5px border.
 */

export type ReadinessLevel = 'Push hard' | 'Train normally' | 'Go easy' | 'Rest day'

interface StatusBadgeProps {
  level: ReadinessLevel
  score?: number
  size?: 'sm' | 'md' | 'lg'
}

interface LevelStyle {
  bg:    string
  border:string
  color: string
}

const LEVEL_STYLES: Record<ReadinessLevel, LevelStyle> = {
  'Push hard':      { bg: 'rgba(29,158,117,0.10)', border: 'rgba(29,158,117,0.20)', color: '#7dd8b8' },
  'Train normally': { bg: 'rgba(29,158,117,0.08)', border: 'rgba(29,158,117,0.15)', color: '#7dd8b8' },
  'Go easy':        { bg: 'rgba(186,117,23,0.10)', border: 'rgba(186,117,23,0.25)', color: '#efb34e' },
  'Rest day':       { bg: 'rgba(216,90,48,0.10)',  border: 'rgba(216,90,48,0.20)',  color: '#e8916e' },
}

const SIZE_STYLE: Record<'sm' | 'md' | 'lg', { fontSize: number; padding: string }> = {
  sm: { fontSize: 11, padding: '3px 10px' },
  md: { fontSize: 12, padding: '4px 16px' },
  lg: { fontSize: 13, padding: '6px 20px' },
}

export function StatusBadge({ level, score, size = 'md' }: StatusBadgeProps) {
  const s = LEVEL_STYLES[level]
  const z = SIZE_STYLE[size]

  return (
    <span
      style={{
        display:         'inline-flex',
        alignItems:      'center',
        gap:             6,
        background:      s.bg,
        border:          `0.5px solid ${s.border}`,
        borderRadius:    6,
        padding:         z.padding,
        fontSize:        z.fontSize,
        fontWeight:      500,
        color:           s.color,
        whiteSpace:      'nowrap',
        fontFamily:      "'DM Sans', system-ui, sans-serif",
      }}
    >
      {score !== undefined && (
        <span style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace", fontVariantNumeric: 'tabular-nums' }}>
          {score}
        </span>
      )}
      {level}
    </span>
  )
}
