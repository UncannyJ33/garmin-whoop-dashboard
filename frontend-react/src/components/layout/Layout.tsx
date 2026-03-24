/**
 * Layout — app shell with sidebar (desktop) + mobile bottom tab bar.
 *
 * Design spec §4:
 * - Desktop: left sidebar 200-220px, always visible
 * - Mobile: bottom tab bar 56px, 5 items, icons only, teal active fill
 */

import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { InstallPrompt } from '../InstallPrompt'
import { useOnlineStatus } from '../../hooks/useOnlineStatus'

// ── Offline banner ─────────────────────────────────────────────────────────

function OfflineBanner() {
  return (
    <div
      className="flex items-center gap-2 px-4 py-2"
      style={{
        borderBottom: '0.5px solid var(--border-subtle)',
        background:   'rgba(186,117,23,0.06)',
      }}
    >
      <span
        style={{
          width:  6, height: 6, borderRadius: '50%',
          background: 'var(--status-caution)',
          flexShrink: 0, display: 'block',
        }}
      />
      <p style={{ fontSize: 12, color: 'var(--status-caution)', fontWeight: 500 }}>
        Offline — showing cached data
      </p>
    </div>
  )
}

// ── Mobile bottom tab bar ──────────────────────────────────────────────────

const NAV_TABS = [
  {
    path: '/',
    label: 'Today',
    end: true,
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="12" x2="15" y2="15" />
      </svg>
    ),
  },
  {
    path: '/training',
    label: 'Training',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 4v16M18 4v16M6 12h12M2 7h4M18 7h4M2 17h4M18 17h4" />
      </svg>
    ),
  },
  {
    path: '/recovery',
    label: 'Recovery',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
      </svg>
    ),
  },
  {
    path: '/insights',
    label: 'Insights',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
  },
  {
    path: '/settings',
    label: 'Settings',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    ),
  },
]

function BottomTabBar() {
  return (
    <nav
      className="flex lg:hidden flex-shrink-0 safe-bottom items-stretch"
      style={{
        background: 'var(--bg-card)',
        borderTop:  '0.5px solid var(--border-subtle)',
        height:     56,
      }}
    >
      {NAV_TABS.map(tab => (
        <NavLink
          key={tab.path}
          to={tab.path}
          end={tab.end}
          className="flex-1 flex flex-col items-center justify-center gap-0.5"
          style={({ isActive }) => ({
            color:          isActive ? 'var(--brand)' : 'var(--text-tertiary)',
            textDecoration: 'none',
            transition:     'color 150ms ease',
          })}
        >
          {({ isActive }) => (
            <>
              <span style={{ opacity: isActive ? 1 : 0.55 }}>{tab.icon}</span>
              <span style={{ fontSize: 9, fontWeight: isActive ? 600 : 400, letterSpacing: '0.04em' }}>
                {tab.label.toUpperCase()}
              </span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  )
}

// ── Layout ─────────────────────────────────────────────────────────────────

export function Layout({ children }: { children?: React.ReactNode } = {}) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const isOnline = useOnlineStatus()

  return (
    <div
      className="flex h-screen overflow-hidden safe-x"
      style={{ background: 'var(--bg-primary)' }}
    >
      {/* Desktop sidebar */}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Mobile-only header */}
        <Header onMenuClick={() => setSidebarOpen(true)} />

        <InstallPrompt />
        {!isOnline && <OfflineBanner />}

        <main
          className="flex-1 overflow-y-auto"
          style={{ padding: '24px', maxWidth: '1200px', width: '100%', margin: '0 auto' }}
        >
          {children ?? <Outlet />}
        </main>

        {/* Mobile bottom tab bar */}
        <BottomTabBar />
      </div>
    </div>
  )
}
