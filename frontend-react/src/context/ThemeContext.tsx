/**
 * ThemeContext — dark-only in v1.
 * The toggle is a no-op; the interface is preserved so existing imports compile.
 */
import { createContext, useContext, useEffect } from 'react'

interface ThemeContextValue {
  theme: 'dark'
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'dark',
  toggle: () => {},
})

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // Always dark — ensure the class is set and theme-color meta matches
    document.documentElement.classList.add('dark')
    document.querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', '#0a0b0f')
  }, [])

  return (
    <ThemeContext.Provider value={{ theme: 'dark', toggle: () => {} }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  return useContext(ThemeContext)
}
