import { memo } from 'react'

export const DayButton = memo(function DayButton({ n, active, onClick }: { n: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50 ${
        active
          ? 'bg-brand text-white'
          : 'bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
      }`}
    >
      {n}d
    </button>
  )
})
