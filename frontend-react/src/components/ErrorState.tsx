interface ErrorStateProps {
  message?: string
  onRetry?: () => void
}

export function ErrorState({
  message = 'Failed to load data.',
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-poor/20 bg-poor/5 px-6 py-10 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-poor/10">
        <svg className="h-6 w-6 text-poor" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
          />
        </svg>
      </div>

      <div className="space-y-1">
        <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Something went wrong</p>
        <p className="text-xs text-slate-400 max-w-xs">{message}</p>
      </div>

      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded-lg bg-surface-overlay px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-surface-border transition-colors border border-surface-border"
        >
          Try again
        </button>
      )}
    </div>
  )
}
