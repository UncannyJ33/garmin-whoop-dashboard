import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { InstallPrompt } from '../InstallPrompt'
import { useOnlineStatus } from '../../hooks/useOnlineStatus'

function OfflineBanner() {
  return (
    <div className="flex items-center gap-2 border-b border-surface-border bg-moderate/5 px-4 py-2">
      <span className="h-1.5 w-1.5 rounded-full bg-moderate flex-shrink-0" />
      <p className="text-xs text-moderate font-medium">
        Offline — showing cached data
      </p>
    </div>
  )
}

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const isOnline = useOnlineStatus()

  return (
    <div className="flex h-screen overflow-hidden bg-surface safe-x">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex flex-1 flex-col overflow-hidden">
        <Header onMenuClick={() => setSidebarOpen(true)} />
        <InstallPrompt />
        {!isOnline && <OfflineBanner />}

        <main className="flex-1 overflow-y-auto p-4 lg:p-6 safe-bottom">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
