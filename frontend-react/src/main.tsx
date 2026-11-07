import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { DateRangeProvider } from './context/DateRangeContext'
import { ThemeProvider } from './context/ThemeContext'
import './styles/globals.css'

// One-time cleanup (see public/sw.js): earlier builds shipped a PWA service worker whose caches
// could serve stale assets (or a previous user's data). public/sw.js is a kill-switch for those
// installs; this unregisters any leftover worker and drops its caches once per browser, gated by
// a localStorage flag. If localStorage is unavailable, fall back to running the cleanup each load.
const SW_CLEANUP_KEY = 'pe-sw-cleanup-v1'

function swCleanupDone(): boolean {
  try {
    return localStorage.getItem(SW_CLEANUP_KEY) === '1'
  } catch {
    return false
  }
}

function markSwCleanupDone(): void {
  try {
    localStorage.setItem(SW_CLEANUP_KEY, '1')
  } catch {
    // storage blocked: cleanup simply runs again next load
  }
}

if (!swCleanupDone()) {
  const tasks: Promise<unknown>[] = []
  if ('serviceWorker' in navigator) {
    tasks.push(
      navigator.serviceWorker
        .getRegistrations()
        .then(regs => Promise.all(regs.map(r => r.unregister()))),
    )
  }
  if ('caches' in window) {
    tasks.push(caches.keys().then(names => Promise.all(names.map(n => caches.delete(n)))))
  }
  void Promise.all(tasks).then(markSwCleanupDone, err => {
    console.warn('Service worker cleanup failed; will retry next load', err)
  })
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <DateRangeProvider>
        <App />
      </DateRangeProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
