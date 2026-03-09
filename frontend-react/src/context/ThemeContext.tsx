import { createContext, useContext, useEffect, useState } from 'react'

type Theme = 'dark' | 'light'

interface ThemeContextValue {
  theme: Theme
  toggle: () => void
}

const DARK_VARS: Record<string, string> = {
  '--color-surface': '#0d0f18',
  '--color-surface-raised': '#161926',
  '--color-surface-overlay': '#1e2235',
  '--color-surface-border': 'rgba(255,255,255,0.07)',
  '--color-text': '#f1f5f9',
  '--color-text-muted': '#94a3b8',
  '--recharts-grid': 'rgba(255,255,255,0.05)',
  '--recharts-axis': '#64748b',
}

const LIGHT_VARS: Record<string, string> = {
  '--color-surface': '#f1f5f9',
  '--color-surface-raised': '#ffffff',
  '--color-surface-overlay': '#e2e8f0',
  '--color-surface-border': 'rgba(0,0,0,0.09)',
  '--color-text': '#0f172a',
  '--color-text-muted': '#475569',
  '--recharts-grid': 'rgba(0,0,0,0.06)',
  '--recharts-axis': '#64748b',
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  const vars = theme === 'dark' ? DARK_VARS : LIGHT_VARS
  for (const [key, value] of Object.entries(vars)) {
    root.style.setProperty(key, value)
  }
  if (theme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  toggle: () => {},
})

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem('theme') as Theme | null
    return stored ?? 'dark'
  })

  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggle = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'))

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
