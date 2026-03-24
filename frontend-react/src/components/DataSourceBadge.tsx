/**
 * DataSourceBadge — source pill (W, G, W+G).
 * Spec §3.6: 10px text, 4px 8px padding, subtle tint, 4px radius.
 */

interface DataSourceBadgeProps {
  source: 'whoop' | 'garmin' | 'both'
  size?: 'xs' | 'sm'
}

const SOURCE_CONFIG = {
  whoop:  { label: 'W',   bg: 'rgba(93,202,165,0.10)', border: 'rgba(93,202,165,0.20)', color: 'var(--status-excellent)' },
  garmin: { label: 'G',   bg: 'rgba(93,202,165,0.08)', border: 'rgba(93,202,165,0.15)', color: '#7dd8b8'                 },
  both:   { label: 'W+G', bg: 'rgba(93,202,165,0.12)', border: 'rgba(93,202,165,0.25)', color: 'var(--status-excellent)' },
}

export function DataSourceBadge({ source, size = 'xs' }: DataSourceBadgeProps) {
  const cfg = SOURCE_CONFIG[source] ?? SOURCE_CONFIG.whoop
  const fontSize = size === 'xs' ? 10 : 11
  const padding  = size === 'xs' ? '3px 7px' : '4px 9px'

  return (
    <span
      style={{
        display:            'inline-flex',
        alignItems:         'center',
        background:         cfg.bg,
        border:             `0.5px solid ${cfg.border}`,
        borderRadius:       4,
        padding,
        fontSize,
        fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
        fontWeight:         600,
        color:              cfg.color,
        flexShrink:         0,
        letterSpacing:      '0.03em',
        fontVariantNumeric: 'tabular-nums',
      }}
    >
      {cfg.label}
    </span>
  )
}
