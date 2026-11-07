/**
 * AuthContext — JWT tokens stored in localStorage so they survive PWA close/reopen.
 * On app open, if the access token is expired but a refresh token exists, a silent
 * refresh is attempted before redirecting to login.
 *
 * On 401 the API client dispatches an 'auth-error' event; AuthProvider listens and
 * redirects to /login.
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

const STORAGE_KEY = 'pd_auth'

interface AuthTokens {
  access_token: string
  refresh_token: string
  expires_at: string
}

interface AuthContextValue {
  token: string | null
  userId: string | null
  isAuthenticated: boolean
  isInitializing: boolean
  login: (tokens: AuthTokens) => void
  logout: () => void
}

/** Extract the `sub` (user UUID) from a JWT without a library. JWTs are signed, not encrypted. */
function extractUserId(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return (payload.sub as string) ?? null
  } catch {
    return null
  }
}

function isAccessTokenExpired(tokens: AuthTokens): boolean {
  return new Date(tokens.expires_at) <= new Date()
}

const AuthContext = createContext<AuthContextValue>({
  token: null,
  userId: null,
  isAuthenticated: false,
  isInitializing: true,
  login: () => {},
  logout: () => {},
})

function loadFromStorage(): AuthTokens | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthTokens
    // If expired with no refresh token, discard immediately
    if (isAccessTokenExpired(parsed) && !parsed.refresh_token) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    // If expired but refresh token present, return as-is — will be refreshed on mount
    return parsed
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [tokens, setTokens] = useState<AuthTokens | null>(() => {
    const t = loadFromStorage()
    // Only set the auth token if access token is still valid
    if (t && !isAccessTokenExpired(t)) setAuthToken(t.access_token)
    return t
  })
  // isInitializing stays true until we've either confirmed the token or refreshed/cleared it
  const [isInitializing, setIsInitializing] = useState<boolean>(() => {
    const t = loadFromStorage()
    // If expired with a refresh token, we'll need to do an async refresh
    return t !== null && isAccessTokenExpired(t)
  })

  const navigate = useNavigate()
  const navigateRef = useRef(navigate)
  navigateRef.current = navigate
  const queryClient = useQueryClient()

  const login = useCallback((t: AuthTokens) => {
    void queryClient.cancelQueries()
    queryClient.clear()
    localStorage.setItem(STORAGE_KEY, JSON.stringify(t))
    setAuthToken(t.access_token)
    setTokens(t)
  }, [queryClient])

  const logout = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setAuthToken(null)
    setTokens(null)
    void queryClient.cancelQueries()
    queryClient.clear()
    navigateRef.current('/login')
  }, [queryClient])

  // On mount: if stored tokens exist but access token is expired, attempt silent refresh
  useEffect(() => {
    if (!isInitializing) return

    const stored = loadFromStorage()
    if (!stored || !stored.refresh_token) {
      setIsInitializing(false)
      return
    }

    fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { Authorization: `Bearer ${stored.refresh_token}` },
    })
      .then(res => {
        if (!res.ok) throw new Error('refresh failed')
        return res.json() as Promise<AuthTokens>
      })
      .then(newTokens => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(newTokens))
        setAuthToken(newTokens.access_token)
        setTokens(newTokens)
      })
      .catch(() => {
        // Refresh token is also expired or invalid — clear everything and go to login
        localStorage.removeItem(STORAGE_KEY)
        setAuthToken(null)
        setTokens(null)
        navigateRef.current('/login')
      })
      .finally(() => setIsInitializing(false))
  }, [isInitializing])

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
        userId: tokens ? extractUserId(tokens.access_token) : null,
        isAuthenticated: tokens !== null && !isAccessTokenExpired(tokens),
        isInitializing,
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
