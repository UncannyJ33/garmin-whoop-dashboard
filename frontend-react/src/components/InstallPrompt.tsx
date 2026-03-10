import { useEffect, useRef, useState } from 'react'

const DISMISSED_KEY = 'pwa-install-dismissed'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallPrompt() {
  const [visible, setVisible] = useState(false)
  const deferred = useRef<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    // Don't show if already dismissed
    if (localStorage.getItem(DISMISSED_KEY)) return
    // Don't show if already running as installed PWA
    if (window.matchMedia('(display-mode: standalone)').matches) return

    function handleBeforeInstall(e: Event) {
      e.preventDefault()
      deferred.current = e as BeforeInstallPromptEvent
      setVisible(true)
    }

    function handleInstalled() {
      setVisible(false)
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstall)
    window.addEventListener('appinstalled', handleInstalled)

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstall)
      window.removeEventListener('appinstalled', handleInstalled)
    }
  }, [])

  async function handleAdd() {
    if (!deferred.current) return
    await deferred.current.prompt()
    const { outcome } = await deferred.current.userChoice
    if (outcome === 'accepted') setVisible(false)
    deferred.current = null
  }

  function handleDismiss() {
    localStorage.setItem(DISMISSED_KEY, '1')
    setVisible(false)
  }

  if (!visible) return null

  return (
    <div className="flex items-center justify-between gap-3 border-b border-surface-border bg-brand/5 px-4 py-2.5 animate-fade-in">
      <div className="flex items-center gap-2.5 min-w-0">
        {/* Download / add-to-home icon */}
        <svg className="h-4 w-4 text-brand flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
          />
        </svg>
        <p className="text-xs text-slate-600 dark:text-slate-300 truncate">
          Add PulseEngine to your home screen for quick access
        </p>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        <button
          onClick={handleAdd}
          className="rounded-lg bg-brand px-3 py-1 text-xs font-semibold text-white hover:opacity-90 transition-opacity"
        >
          Add
        </button>
        <button
          onClick={handleDismiss}
          aria-label="Dismiss install prompt"
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors p-0.5"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
