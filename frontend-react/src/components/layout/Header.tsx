/**
 * Header — mobile-only top bar with hamburger menu.
 * On desktop the sidebar is always visible; this bar handles mobile nav trigger only.
 * Dark-only: no theme toggle.
 */

import { useSyncStatus } from '../../hooks/useApi'

interface HeaderProps {
  onMenuClick: () => void
}

export function Header({ onMenuClick }: HeaderProps) {
  const { data: syncStatus } = useSyncStatus()

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month:   'long',
    day:     'numeric',
  })

  const whoopSync = syncStatus?.find(s => s.source === 'whoop')
  const lastSync = whoopSync?.last_sync_at
    ? new Date(whoopSync.last_sync_at).toLocaleTimeString('en-US', {
        hour:   'numeric',
        minute: '2-digit',
      })
    : null

  return (
    <header
      className="flex min-h-14 items-end gap-3 flex-shrink-0 lg:hidden"
      style={{
        background:   'var(--bg-card)',
        borderBottom: '0.5px solid var(--border-subtle)',
        padding:      'env(safe-area-inset-top, 0px) 16px 12px',
        paddingTop:   'max(env(safe-area-inset-top, 0px), 12px)',
      }}
    >
      <button
        onClick={onMenuClick}
        className="flex h-9 w-9 items-center justify-center rounded-lg"
        style={{ color: 'var(--text-secondary)', flexShrink: 0 }}
        aria-label="Open menu"
      >
        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      <div className="flex flex-1 items-center justify-between">
        <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{today}</p>

        {lastSync && (
          <p style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
            Synced{' '}
            <span style={{ color: 'var(--text-secondary)' }}>{lastSync}</span>
          </p>
        )}
      </div>
    </header>
  )
}
