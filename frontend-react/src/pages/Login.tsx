import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at: string
}

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (mode === 'register') {
        // Register first, then auto-login
        const regRes = await fetch(`${BASE_URL}/api/auth/register`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'ngrok-skip-browser-warning': 'true',
          },
          body: JSON.stringify({ email, password }),
        })
        if (!regRes.ok) {
          const body = (await regRes.json()) as { detail?: string }
          setError(body.detail ?? `Registration failed (${regRes.status})`)
          return
        }
      }

      // Login (after register or directly)
      const loginRes = await fetch(`${BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({ email, password }),
      })
      if (!loginRes.ok) {
        const body = (await loginRes.json()) as { detail?: string }
        setError(body.detail ?? `Login failed (${loginRes.status})`)
        return
      }
      const tokens = (await loginRes.json()) as LoginResponse
      login(tokens)
      navigate('/', { replace: true })
    } catch {
      setError('Could not reach the server. Check your connection.')
    } finally {
      setLoading(false)
    }
  }

  const isLogin = mode === 'login'

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-bg px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1
            className="text-2xl font-bold text-slate-100"
            style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif", letterSpacing: '-0.01em' }}
          >
            PulseEngine
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            {isLogin ? 'Sign in to your dashboard' : 'Create a new account'}
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-card border border-surface-border rounded-2xl p-6 space-y-4"
        >
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface-bg border border-surface-border rounded-lg px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none"
              style={{ ['--tw-ring-color' as string]: 'var(--data-primary)' }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--data-primary)')}
              onBlur={e => (e.currentTarget.style.borderColor = '')}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1.5" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface-bg border border-surface-border rounded-lg px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none"
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--data-primary)')}
              onBlur={e => (e.currentTarget.style.borderColor = '')}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="text-poor text-sm bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg py-2.5 text-sm transition-opacity"
            style={{ background: 'var(--data-primary)' }}
          >
            {loading
              ? isLogin
                ? 'Signing in…'
                : 'Creating account…'
              : isLogin
                ? 'Sign in'
                : 'Create account'}
          </button>

          {!isLogin && (
            <p className="text-center text-slate-500 text-xs leading-relaxed">
              By creating an account, you agree to our{' '}
              <Link to="/privacy" className="text-slate-400 underline hover:text-slate-200">
                Privacy Policy
              </Link>
              .
            </p>
          )}
        </form>

        <p className="text-center text-slate-500 text-sm mt-4">
          {isLogin ? (
            <>
              Don&apos;t have an account?{' '}
              <button
                type="button"
                onClick={() => { setMode('register'); setError(null) }}
                className="underline"
                style={{ color: 'var(--data-primary)' }}
              >
                Create one
              </button>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => { setMode('login'); setError(null) }}
                className="underline"
                style={{ color: 'var(--data-primary)' }}
              >
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  )
}
