import { useSyncStatus } from '../../hooks/useApi'
import { useTheme } from '../../context/ThemeContext'

interface HeaderProps {
  onMenuClick: () => void
}

export function Header({ onMenuClick }: HeaderProps) {
  const { data: syncStatus } = useSyncStatus()
  const { theme, toggle } = useTheme()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })

  const whoopSync = syncStatus?.find(s => s.source === 'whoop')
  const lastSync = whoopSync?.last_sync_at
    ? new Date(whoopSync.last_sync_at).toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      })
    : null

  return (
    <header
      className="flex min-h-14 items-end gap-3 border-b border-surface-border bg-surface-raised px-4 lg:px-6 flex-shrink-0 pb-3"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      <button
        onClick={onMenuClick}
        className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-slate-700 dark:hover:text-slate-200 lg:hidden transition-colors"
        aria-label="Open menu"
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <div className="flex flex-1 items-center justify-between">
        <p className="text-sm text-slate-400">{today}</p>

        <div className="flex items-center gap-3">
          {lastSync && (
            <p className="hidden sm:block text-xs text-slate-500">
              Synced <span className="text-slate-400">{lastSync}</span>
            </p>
          )}

          {/* Theme toggle */}
          <button
            onClick={toggle}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-slate-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
            aria-label="Toggle theme"
            title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {theme === 'dark' ? (
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
                />
              </svg>
            ) : (
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </header>
  )
}
