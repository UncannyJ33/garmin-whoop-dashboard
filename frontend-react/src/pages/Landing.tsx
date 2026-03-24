/**
 * PulseEngine pre-launch landing page.
 * Shown at / when the user is not authenticated.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

// ---------------------------------------------------------------------------
// Feature data
// ---------------------------------------------------------------------------

const FEATURES = [
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    title: 'Morning Readiness Score',
    description: 'A single 0–100 composite score from HRV trend, recovery, body battery, sleep quality, and training load. Know in seconds whether to push or recover.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
    title: 'Training Load Balance',
    description: 'Acute:Chronic Workload Ratio (ACWR) shows whether you\'re building fitness or accumulating injury risk. Stay in the green zone automatically.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
      </svg>
    ),
    title: 'Sleep Impact Analysis',
    description: 'See exactly how last night\'s sleep affects today\'s performance. Strain-to-sleep correlations, debt tracking, and consistency trends over time.',
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 16.875h3.375m0 0h3.375m-3.375 0V13.5m0 3.375v3.375M6 10.5h2.25a2.25 2.25 0 002.25-2.25V6a2.25 2.25 0 00-2.25-2.25H6A2.25 2.25 0 003.75 6v2.25A2.25 2.25 0 006 10.5zm0 9.75h2.25A2.25 2.25 0 0010.5 18v-2.25a2.25 2.25 0 00-2.25-2.25H6a2.25 2.25 0 00-2.25 2.25V18A2.25 2.25 0 006 20.25zm9.75-9.75H18a2.25 2.25 0 002.25-2.25V6A2.25 2.25 0 0018 3.75h-2.25A2.25 2.25 0 0013.5 6v2.25a2.25 2.25 0 002.25 2.25z" />
      </svg>
    ),
    title: 'Works with Whoop + Garmin',
    description: 'Connects both devices seamlessly. Whoop handles recovery and sleep quality; Garmin handles workout detail and running dynamics. One dashboard, full picture.',
  },
]

// ---------------------------------------------------------------------------
// App preview mockup (Today page representation)
// ---------------------------------------------------------------------------

function AppPreview() {
  return (
    <div className="relative w-full max-w-sm mx-auto select-none pointer-events-none">
      {/* Glow behind the card */}
      <div className="absolute inset-0 rounded-2xl bg-[var(--brand)] opacity-[0.06] blur-2xl scale-110" />

      <div className="relative rounded-2xl border border-white/8 bg-[var(--bg-card)] shadow-2xl overflow-hidden">
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/6">
          <span className="text-xs font-semibold text-[var(--brand)]" style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif", fontSize: 13 }}>PulseEngine</span>
          <div className="flex items-center gap-1.5">
            <div className="h-1.5 w-1.5 rounded-full bg-[var(--brand)]" />
            <span className="text-2xs text-white/40">Today</span>
          </div>
        </div>

        <div className="p-4 space-y-3">
          {/* Readiness hero */}
          <div className="rounded-xl bg-white/[0.03] border border-white/6 p-4 flex items-center gap-4">
            {/* Arc gauge */}
            <div className="relative flex-shrink-0">
              <svg viewBox="0 0 80 56" className="w-20 h-14">
                {/* Track */}
                <path d="M 8 52 A 32 32 0 0 1 72 52" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="6" strokeLinecap="round" />
                {/* Fill — 78% */}
                <path d="M 8 52 A 32 32 0 0 1 72 52" fill="none" stroke="var(--status-excellent)" strokeWidth="6" strokeLinecap="round"
                  strokeDasharray="100" strokeDashoffset="22" />
                <text x="40" y="46" textAnchor="middle" fill="white" fontSize="14" fontWeight="700" fontFamily="IBM Plex Mono, monospace">78</text>
              </svg>
            </div>
            <div>
              <p className="text-xs text-white/40 uppercase tracking-wider">Readiness</p>
              <p className="text-sm font-semibold text-white mt-0.5">Train normally</p>
              <div className="flex items-center gap-1 mt-1">
                <div className="h-1.5 w-1.5 rounded-full bg-[var(--status-excellent)]" />
                <span className="text-2xs text-[var(--status-excellent)]">HRV in range</span>
              </div>
            </div>
          </div>

          {/* Metric row */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'HRV', value: '62ms', delta: '+4', good: true },
              { label: 'Sleep', value: '7.4h', delta: '-0.2', good: false },
              { label: 'Battery', value: '81%', delta: '+12', good: true },
            ].map(m => (
              <div key={m.label} className="rounded-lg bg-white/[0.03] border border-white/6 p-2 space-y-1">
                <p className="text-2xs text-white/40">{m.label}</p>
                <p className="text-sm font-semibold font-mono text-white">{m.value}</p>
                <p className={`text-2xs font-mono ${m.good ? 'text-[var(--status-excellent)]' : 'text-[var(--status-caution)]'}`}>{m.delta}</p>
              </div>
            ))}
          </div>

          {/* ACWR bar */}
          <div className="rounded-xl bg-white/[0.03] border border-white/6 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-white/40">Training Load</span>
              <span className="text-xs font-mono text-[var(--status-excellent)]">ACWR 1.02</span>
            </div>
            <div className="relative h-1.5 rounded-full bg-white/6 overflow-hidden">
              <div className="absolute inset-y-0 left-0 rounded-full bg-[var(--status-excellent)]" style={{ width: '68%' }} />
            </div>
            <div className="flex justify-between text-2xs text-white/25">
              <span>Under-training</span>
              <span className="text-[var(--status-excellent)]">Optimal</span>
              <span>Over-reaching</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Waitlist form
// ---------------------------------------------------------------------------

function WaitlistForm() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email) return
    setState('loading')
    setErrorMsg('')
    try {
      await api.post('/api/waitlist', { email })
      setState('success')
      setEmail('')
    } catch (err) {
      setState('error')
      setErrorMsg(err instanceof Error ? err.message : 'Something went wrong. Try again.')
    }
  }

  if (state === 'success') {
    return (
      <div className="rounded-xl border border-[var(--brand)]/30 bg-[var(--brand)]/5 px-5 py-4 text-center space-y-1">
        <p className="text-sm font-semibold text-[var(--brand)]">You're on the list</p>
        <p className="text-xs text-white/50">We'll reach out when PulseEngine opens for new accounts.</p>
      </div>
    )
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
      <div className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="your@email.com"
          required
          className="flex-1 min-w-0 rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-[var(--brand)]/50"
        />
        <button
          type="submit"
          disabled={state === 'loading' || !email}
          className="flex-shrink-0 rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
        >
          {state === 'loading' ? '…' : 'Join'}
        </button>
      </div>
      {state === 'error' && (
        <p className="text-xs text-[var(--status-alert)]">{errorMsg}</p>
      )}
    </form>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function Landing() {
  return (
    <div className="min-h-screen bg-[var(--bg-primary)] text-white flex flex-col">

      {/* ── Nav ──────────────────────────────────────────────────────────────── */}
      <nav className="sticky top-0 z-10 border-b border-white/6 bg-[var(--bg-primary)]/90 backdrop-blur-sm">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <span className="font-semibold text-[var(--brand)] tracking-tight" style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif" }}>
            PulseEngine
          </span>
          <Link
            to="/login"
            className="text-xs font-medium text-white/60 hover:text-white transition-colors"
          >
            Sign in
          </Link>
        </div>
      </nav>

      <main className="flex-1">

        {/* ── Hero ─────────────────────────────────────────────────────────── */}
        <section className="mx-auto max-w-5xl px-6 pt-20 pb-16 text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--brand)]/20 bg-[var(--brand)]/5 px-3 py-1 mb-8">
            <div className="h-1.5 w-1.5 rounded-full bg-[var(--brand)] animate-pulse" />
            <span className="text-xs font-medium text-[var(--brand)]">Early access — join the waitlist</span>
          </div>

          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight leading-tight mb-4" style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif" }}>
            Your data,{' '}
            <span className="text-[var(--brand)]">finally useful</span>
          </h1>

          <p className="mx-auto max-w-lg text-base text-white/55 leading-relaxed mb-10">
            The dashboard that unifies your Whoop and Garmin data into actionable training insights —
            so every morning you know exactly how hard to train.
          </p>

          {/* CTA */}
          <div className="mx-auto max-w-sm space-y-3">
            <WaitlistForm />
            <p className="text-xs text-white/35">
              Already have an account?{' '}
              <Link to="/login" className="text-white/60 underline hover:text-white transition-colors">
                Sign in
              </Link>
            </p>
          </div>
        </section>

        {/* ── App Preview ──────────────────────────────────────────────────── */}
        <section className="mx-auto max-w-5xl px-6 pb-20">
          <AppPreview />
        </section>

        {/* ── Features ─────────────────────────────────────────────────────── */}
        <section className="border-t border-white/6 bg-white/[0.015]">
          <div className="mx-auto max-w-5xl px-6 py-20">
            <h2 className="text-center text-lg font-semibold text-white/80 mb-12">
              Everything your devices measure, finally in one place
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {FEATURES.map(f => (
                <div
                  key={f.title}
                  className="rounded-xl border border-white/6 bg-white/[0.025] p-5 space-y-2 hover:border-[var(--brand)]/20 transition-colors"
                >
                  <div className="flex items-center gap-2.5 text-[var(--brand)]">
                    {f.icon}
                    <h3 className="text-sm font-semibold text-white">{f.title}</h3>
                  </div>
                  <p className="text-xs text-white/50 leading-relaxed">{f.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ── Bottom CTA ───────────────────────────────────────────────────── */}
        <section className="mx-auto max-w-5xl px-6 py-20 text-center">
          <h2 className="text-2xl font-bold mb-3">
            Ready to train smarter?
          </h2>
          <p className="text-sm text-white/50 mb-8">
            Join the waitlist and be first to know when we open new accounts.
          </p>
          <div className="mx-auto max-w-sm">
            <WaitlistForm />
          </div>
        </section>

      </main>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <footer className="border-t border-white/6 py-6">
        <div className="mx-auto max-w-5xl px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-white/30">
          <span>
            Built by{' '}
            <a
              href="https://pulsebuilt.net"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-white/60 transition-colors"
            >
              Pulse Built
            </a>
          </span>
          <Link to="/privacy" className="hover:text-white/60 transition-colors">
            Privacy Policy
          </Link>
        </div>
      </footer>

    </div>
  )
}
