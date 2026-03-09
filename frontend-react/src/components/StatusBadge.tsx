type ReadinessLevel = 'Push hard' | 'Train normally' | 'Go easy' | 'Rest day'

interface StatusBadgeProps {
  level: ReadinessLevel
  score?: number
  size?: 'sm' | 'md' | 'lg'
}

const LEVEL_CONFIG: Record<
  ReadinessLevel,
  { color: string; bg: string; border: string; ring: string }
> = {
  'Push hard':     { color: 'text-good',     bg: 'bg-good/10',     border: 'border-good/40',     ring: 'ring-good/20' },
  'Train normally':{ color: 'text-brand',    bg: 'bg-brand/10',    border: 'border-brand/40',    ring: 'ring-brand/20' },
  'Go easy':       { color: 'text-moderate', bg: 'bg-moderate/10', border: 'border-moderate/40', ring: 'ring-moderate/20' },
  'Rest day':      { color: 'text-poor',     bg: 'bg-poor/10',     border: 'border-poor/40',     ring: 'ring-poor/20' },
}

const SIZE_CLASSES = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-4 py-1.5 text-sm',
  lg: 'px-6 py-2.5 text-base',
}

export function StatusBadge({ level, score, size = 'md' }: StatusBadgeProps) {
  const cfg = LEVEL_CONFIG[level]

  return (
    <div
      className={`
        inline-flex items-center gap-2 rounded-full border font-semibold
        ring-4 tracking-wide
        ${cfg.color} ${cfg.bg} ${cfg.border} ${cfg.ring}
        ${SIZE_CLASSES[size]}
      `}
    >
      {score !== undefined && (
        <span className="font-mono tabular-nums">{score}</span>
      )}
      {level}
    </div>
  )
}
