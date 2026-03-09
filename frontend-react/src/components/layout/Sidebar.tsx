import { NavLink } from 'react-router-dom'

interface NavItem {
  path: string
  label: string
  icon: string
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', label: 'Readiness', icon: '⚡' },
  { path: '/workouts', label: 'Workouts', icon: '🏃' },
  { path: '/sleep', label: 'Sleep', icon: '🌙' },
  { path: '/trends', label: 'Trends', icon: '📈' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export function Sidebar({ open, onClose }: SidebarProps) {
  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-20 bg-black/60 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`
          fixed inset-y-0 left-0 z-30 flex w-56 flex-col bg-surface-raised border-r border-white/5
          transition-transform duration-200
          ${open ? 'translate-x-0' : '-translate-x-full'}
          lg:relative lg:translate-x-0 lg:z-auto
        `}
      >
        {/* Logo */}
        <div className="flex h-14 items-center px-4 border-b border-white/5">
          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 tracking-wide">
            Fitness<span className="text-brand"> Dashboard</span>
          </span>
        </div>

        {/* Nav links */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map(({ path, label, icon }) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/'}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand/20 text-brand'
                    : 'text-slate-500 dark:text-slate-400 hover:bg-black/5 dark:hover:bg-white/5 hover:text-slate-700 dark:hover:text-slate-200'
                }`
              }
            >
              <span className="text-base">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-white/5">
          <p className="text-xs text-slate-500">Garmin + Whoop</p>
        </div>
      </aside>
    </>
  )
}
