/**
 * AuthContext — JWT token stored in sessionStorage (not localStorage).
 * sessionStorage is cleared when the browser tab/session closes, which is
 * more secure than localStorage while still surviving page refreshes.
 *
 * On 401 the API client dispatches an 'auth-error' event; AuthProvider
 * listens for it and redirects to /login.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import { useNavigate } from 'react-router-dom'

const SESSION_KEY = 'pd_auth'

interface AuthTokens {
  access_token: string
  refresh_token: string
  expires_at: string
}

interface AuthContextValue {
  token: string | null
  isAuthenticated: boolean
  login: (tokens: AuthTokens) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue>({
  token: null,
  isAuthenticated: false,
  login: () => {},
  logout: () => {},
})

function loadFromSession(): AuthTokens | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthTokens
    // Discard if access token is expired
    if (new Date(parsed.expires_at) <= new Date()) {
      sessionStorage.removeItem(SESSION_KEY)
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [tokens, setTokens] = useState<AuthTokens | null>(loadFromSession)
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate

  const login = useCallback((t: AuthTokens) => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(t))
    setTokens(t)
  }, [])

  const logout = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setTokens(null)
    navigateRef.current('/login')
  }, [])

  // Listen for 401s dispatched by the API client
  useEffect(() => {
    const handler = () => logout()
    window.addEventListener('auth-error', handler)
    return () => window.removeEventListener('auth-error', handler)
  }, [logout])

  return (
    <AuthContext.Provider
      value={{
        token: tokens?.access_token ?? null,
        isAuthenticated: tokens !== null,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
