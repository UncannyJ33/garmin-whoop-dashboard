import { useEffect, useState } from 'react'

/**
 * Returns true when the browser has network connectivity.
 *
 * Uses navigator.onLine + online/offline events as the base, augmented by
 * custom 'api-offline' / 'api-online' events dispatched by the API client.
 * This is necessary because navigator.onLine is unreliable in iOS standalone
 * PWA mode — it often stays true even when the device is in airplane mode.
 */
export function useOnlineStatus(): boolean {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    function handleOnline()    { setIsOnline(true) }
    function handleOffline()   { setIsOnline(false) }
    function handleApiOnline() { setIsOnline(true) }
    function handleApiOffline() { setIsOnline(false) }

    window.addEventListener('online',      handleOnline)
    window.addEventListener('offline',     handleOffline)
    window.addEventListener('api-online',  handleApiOnline)
    window.addEventListener('api-offline', handleApiOffline)

    return () => {
      window.removeEventListener('online',      handleOnline)
      window.removeEventListener('offline',     handleOffline)
      window.removeEventListener('api-online',  handleApiOnline)
      window.removeEventListener('api-offline', handleApiOffline)
    }
  }, [])

  return isOnline
}
