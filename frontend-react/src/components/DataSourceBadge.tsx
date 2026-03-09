interface DataSourceBadgeProps {
  source: 'whoop' | 'garmin' | 'both'
  size?: 'xs' | 'sm'
}

const SOURCE_CONFIG = {
  whoop:  { label: 'W',     className: 'bg-brand/15 text-brand   border-brand/30' },
  garmin: { label: 'G',     className: 'bg-chart-teal/15 text-chart-teal border-chart-teal/30' },
  both:   { label: 'W+G',   className: 'bg-good/15 text-good     border-good/30' },
}

export function DataSourceBadge({ source, size = 'xs' }: DataSourceBadgeProps) {
  const cfg = SOURCE_CONFIG[source] ?? SOURCE_CONFIG.whoop
  const sizeClass = size === 'xs'
    ? 'px-1.5 py-0.5 text-2xs'
    : 'px-2 py-0.5 text-xs'

  return (
    <span
      className={`
        inline-flex items-center rounded border font-mono font-semibold tracking-wide flex-shrink-0
        ${cfg.className} ${sizeClass}
      `}
    >
      {cfg.label}
    </span>
  )
}
