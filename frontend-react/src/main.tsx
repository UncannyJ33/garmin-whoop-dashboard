import React from 'react'
import ReactDOM from 'react-dom/client'
import { App } from './App'
import { DateRangeProvider } from './context/DateRangeContext'
import { ThemeProvider } from './context/ThemeContext'
import './styles/globals.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <DateRangeProvider>
        <App />
      </DateRangeProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
