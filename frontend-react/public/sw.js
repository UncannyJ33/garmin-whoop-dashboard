// Self-destroying service worker. The PWA was removed, but browsers that installed the old
// worker still check this URL for updates; serving this file replaces the old registration,
// clears its caches and unregisters itself. Nothing registers it. Safe to delete once no
// browser still has the old PWA installed.
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys()
      await Promise.all(names.map(n => caches.delete(n)))
      await self.registration.unregister()
      const clients = await self.clients.matchAll({ type: 'window' })
      clients.forEach(c => c.navigate(c.url))
    })(),
  )
})
