import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { DateRangeProvider } from './context/DateRangeContext'
import { ThemeProvider } from './context/ThemeContext'
import './styles/globals.css'

// One-time cleanup: earlier builds shipped a PWA service worker whose caches could serve stale
// assets (or a previous user's data). Unregister any leftover worker and drop its caches.
if ('serviceWorker' in navigator) {
  void navigator.serviceWorker
    .getRegistrations()
    .then(regs => Promise.all(regs.map(r => r.unregister())))
    .catch(() => {})
}
if ('caches' in window) {
  void caches
    .keys()
    .then(names => Promise.all(names.map(n => caches.delete(n))))
    .catch(() => {})
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
