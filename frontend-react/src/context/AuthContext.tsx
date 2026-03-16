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
import { useQueryClient } from '@tanstack/react-query'
import { setAuthToken } from '../api/client'

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
  const [tokens, setTokens] = useState<AuthTokens | null>(() => {
    const t = loadFromSession()
    setAuthToken(t?.access_token ?? null)
    return t
  })
  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const queryClient = useQueryClient()

  const login = useCallback((t: AuthTokens) => {
    // Cancel in-flight requests (aborts fetch via AbortSignal) then wipe cache
    // so no prior user's data leaks into the new session.
    void queryClient.cancelQueries()
    queryClient.clear()
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(t))
    setAuthToken(t.access_token)
    setTokens(t)
  }, [queryClient])

  const logout = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setAuthToken(null)
    setTokens(null)
    // Cancel in-flight requests then wipe cache before navigating to login.
    void queryClient.cancelQueries()
    queryClient.clear()
    navigateRef.current('/login')
  }, [queryClient])

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
