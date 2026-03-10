import { useEffect, useRef, useState } from 'react'

/**
 * Returns true when the browser has network connectivity.
 *
 * Uses navigator.onLine + online/offline events as the base, augmented by
 * custom 'api-offline' / 'api-online' events dispatched by the API client.
 * This is necessary because navigator.onLine is unreliable in iOS standalone
 * PWA mode — it often stays true even when the device is in airplane mode.
 *
 * api-offline is debounced with a 3-second delay to avoid false positives
 * from transient failures (e.g. a single timed-out request on a slow network).
 */
export function useOnlineStatus(): boolean {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine)
  const offlineTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    function handleOnline() { setIsOnline(true) }
    function handleOffline() { setIsOnline(false) }

    function handleApiOnline() {
      if (offlineTimer.current) {
        clearTimeout(offlineTimer.current)
        offlineTimer.current = null
      }
      setIsOnline(true)
    }

    function handleApiOffline() {
      // Only mark offline after a sustained failure (3 s) to ignore transient errors
      if (!offlineTimer.current) {
        offlineTimer.current = setTimeout(() => {
          offlineTimer.current = null
          setIsOnline(false)
        }, 3000)
      }
    }

    window.addEventListener('online',      handleOnline)
    window.addEventListener('offline',     handleOffline)
    window.addEventListener('api-online',  handleApiOnline)
    window.addEventListener('api-offline', handleApiOffline)

    return () => {
      window.removeEventListener('online',      handleOnline)
      window.removeEventListener('offline',     handleOffline)
      window.removeEventListener('api-online',  handleApiOnline)
      window.removeEventListener('api-offline', handleApiOffline)
      if (offlineTimer.current) clearTimeout(offlineTimer.current)
    }
  }, [])

  return isOnline
}
