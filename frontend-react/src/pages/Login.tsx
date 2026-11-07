import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { formatDetail } from '../api/client'

interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_at: string
}

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
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
      const loginRes = await fetch(`${BASE_URL}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'ngrok-skip-browser-warning': 'true',
        },
        body: JSON.stringify({ email, password }),
      })
      if (!loginRes.ok) {
        const body = (await loginRes.json()) as { detail?: unknown }
        setError(formatDetail(body.detail) ?? `Login failed (${loginRes.status})`)
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

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm animate-fade-in">
        <div className="text-center mb-8">
          <h1
            style={{
              fontFamily: "'Barlow Condensed', system-ui, sans-serif",
              fontSize: 32,
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: '-0.01em',
            }}
          >
            PulseEngine
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginTop: 4 }}>
            Sign in to your dashboard
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          style={{
            background: 'var(--bg-card)',
            border: '0.5px solid var(--border-subtle)',
            borderRadius: 16,
            padding: 24,
          }}
          className="space-y-4"
        >
          <div>
            <label
              className="block mb-1.5"
              htmlFor="email"
              style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full focus:outline-none"
              style={{
                background: 'var(--bg-primary)',
                border: '0.5px solid var(--border-subtle)',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                color: 'var(--text-primary)',
                transition: 'border-color 150ms ease',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--brand)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
              placeholder="you@example.com"
            />
          </div>

          <div>
            <label
              className="block mb-1.5"
              htmlFor="password"
              style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full focus:outline-none"
              style={{
                background: 'var(--bg-primary)',
                border: '0.5px solid var(--border-subtle)',
                borderRadius: 8,
                padding: '10px 12px',
                fontSize: 14,
                color: 'var(--text-primary)',
                transition: 'border-color 150ms ease',
              }}
              onFocus={e => (e.currentTarget.style.borderColor = 'var(--brand)')}
              onBlur={e => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p style={{
              fontSize: 13,
              color: 'var(--status-alert)',
              background: 'var(--status-alert-muted)',
              border: '0.5px solid rgba(216, 90, 48, 0.25)',
              borderRadius: 8,
              padding: '8px 12px',
            }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              background: 'var(--brand)',
              color: '#fff',
              fontWeight: 600,
              borderRadius: 8,
              padding: '10px 0',
              fontSize: 14,
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'opacity 150ms ease',
            }}
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p style={{ textAlign: 'center', color: 'var(--text-tertiary)', fontSize: 13, marginTop: 16 }}>
          No account? Run <code>make owner EMAIL=you@example.com</code> on the server.
        </p>
      </div>
    </div>
  )
}
