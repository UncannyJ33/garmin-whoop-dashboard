/**
 * Sidebar navigation — desktop left panel (200-220px).
 *
 * Design spec §4:
 * - Logo top
 * - Nav items: icon + label, 14px, text-secondary default, status-good teal when active
 * - Active: teal text + rgba(29,158,117,0.08) bg tint
 * - Settings at bottom, separated by divider
 */

import { NavLink } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { PulseLogo } from '../PulseLogo'

// SVG icons
const Icons = {
  Today: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="12" x2="15" y2="15" />
    </svg>
  ),
  Training: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 4v16M18 4v16M6 12h12M2 7h4M18 7h4M2 17h4M18 17h4" />
    </svg>
  ),
  Recovery: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  ),
  Insights: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
  Settings: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  SignOut: (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
    </svg>
  ),
}

const NAV_ITEMS = [
  { path: '/',         label: 'Today',    icon: Icons.Today,    end: true  },
  { path: '/workouts', label: 'Training', icon: Icons.Training, end: false },
  { path: '/sleep',    label: 'Recovery', icon: Icons.Recovery, end: false },
  { path: '/trends',   label: 'Insights', icon: Icons.Insights, end: false },
  { path: '/settings', label: 'Settings', icon: Icons.Settings, end: false },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const { logout } = useAuth()

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-20 lg:hidden"
          style={{ background: 'rgba(0,0,0,0.65)' }}
          onClick={onClose}
        />
      )}

      {/* Sidebar panel */}
      <aside
        style={{
          width:       216,
          background:  'var(--bg-card)',
          borderRight: '0.5px solid var(--border-subtle)',
          display:     'flex',
          flexDirection: 'column',
        }}
        className={[
          'fixed inset-y-0 left-0 z-30',
          'transition-transform duration-200',
          open ? 'translate-x-0' : '-translate-x-full',
          'lg:relative lg:translate-x-0 lg:z-auto lg:flex-shrink-0',
        ].join(' ')}
      >
        {/* Logo area */}
        <div
          style={{
            borderBottom: '0.5px solid var(--border-subtle)',
            display:      'flex',
            alignItems:   'flex-end',
            minHeight:    60,
            padding:      'max(env(safe-area-inset-top, 16px), 16px) 20px 14px',
          }}
        >
          <PulseLogo width={128} />
        </div>

        {/* Nav links */}
        <nav
          style={{ flex: 1, overflowY: 'auto', padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 1 }}
        >
          {NAV_ITEMS.map(({ path, label, icon, end }) => (
            <NavLink
              key={path}
              to={path}
              end={end}
              onClick={onClose}
              className="nav-item"
              style={({ isActive }) => ({
                display:        'flex',
                alignItems:     'center',
                gap:            10,
                padding:        '8px 12px',
                borderRadius:   8,
                fontSize:       14,
                fontWeight:     isActive ? 500 : 400,
                color:          isActive ? 'var(--status-excellent)' : 'var(--text-secondary)',
                background:     isActive ? 'rgba(29,158,117,0.08)' : 'transparent',
                textDecoration: 'none',
                transition:     'color 150ms, background 150ms',
              })}
            >
              {({ isActive }) => (
                <>
                  <span style={{ opacity: isActive ? 1 : 0.5, flexShrink: 0 }}>{icon}</span>
                  <span>{label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Sign out */}
        <div style={{ padding: '8px 8px 12px', borderTop: '0.5px solid var(--border-subtle)' }}>
          <button
            onClick={logout}
            style={{
              display:     'flex',
              alignItems:  'center',
              gap:         10,
              width:       '100%',
              padding:     '8px 12px',
              borderRadius:8,
              fontSize:    13,
              color:       'var(--text-tertiary)',
              background:  'transparent',
              border:      'none',
              cursor:      'pointer',
              textAlign:   'left',
              transition:  'color 150ms',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-tertiary)')}
          >
            <span style={{ opacity: 0.5 }}>{Icons.SignOut}</span>
            Sign out
          </button>
        </div>
      </aside>
    </>
  )
}
