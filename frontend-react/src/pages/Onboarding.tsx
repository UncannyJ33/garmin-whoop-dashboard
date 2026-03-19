/**
 * New-user onboarding — connect Whoop + Garmin, trigger initial sync.
 *
 * Garmin card offers two paths:
 *   1. Connect with credentials (garth session — auto-sync going forward)
 *   2. Import CSV (privacy-preserving fallback; no credentials stored)
 *
 * Whoop card shows OAuth or "coming soon" based on WHOOP_PUBLIC_OAUTH_ENABLED.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import {
  useFeatureFlags,
  useGarminStatus,
  useSyncStatus,
  useTriggerSync,
  useWhoopStatus,
  type UploadResult,
} from '../hooks/useApi'
import { useAuth } from '../context/AuthContext'
import { GarminUpload } from '../components/GarminUpload'

// ── helpers ────────────────────────────────────────────────────────────────────

function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  )
}

function CheckIcon({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

// ── Garmin credential modal ────────────────────────────────────────────────────

interface GarminModalProps {
  onClose: () => void
  onSuccess: () => void
}

function GarminCredentialModal({ onClose, onSuccess }: GarminModalProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [consent, setConsent] = useState(false)

  async function handleConnect() {
    if (!consent) {
      setError('Please confirm that you consent to syncing your Garmin data.')
      return
    }
    setConnecting(true)
    setError(null)
    try {
      await api.post('/api/auth/garmin/connect', { email, password })
      onSuccess()
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Could not connect Garmin. Check your credentials.',
      )
    } finally {
      setConnecting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-sm bg-surface-card border border-surface-border rounded-2xl p-6 space-y-4 shadow-xl">
        <div>
          <h2 className="text-base font-semibold text-slate-100">Connect Garmin (auto-sync)</h2>
          <p className="text-xs text-slate-400 mt-1 leading-relaxed">
            Enter your Garmin Connect credentials. Your password is used only to
            authenticate and is never stored — only the session tokens are saved.
          </p>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1" htmlFor="gc-email">
              Garmin Connect email
            </label>
            <input
              id="gc-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-surface-bg border border-surface-border rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1" htmlFor="gc-pw">
              Password
            </label>
            <input
              id="gc-pw"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-surface-bg border border-surface-border rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••"
            />
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-surface-border accent-blue-500"
            />
            <span className="text-xs text-slate-400 leading-relaxed">
              I consent to PulseEngine syncing my Garmin activity, sleep, and health
              data to display personalised insights.
            </span>
          </label>
        </div>

        {error && (
          <p className="text-poor text-xs bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 border border-surface-border rounded-lg py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleConnect()}
            disabled={connecting || !email || !password}
            className="flex-1 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-medium rounded-lg py-2 text-sm transition-colors flex items-center justify-center gap-2"
          >
            {connecting && <Spinner />}
            {connecting ? 'Connecting…' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Garmin upload modal ────────────────────────────────────────────────────────

interface GarminUploadModalProps {
  onClose: () => void
  onSuccess: (result: UploadResult) => void
}

function GarminUploadModal({ onClose, onSuccess }: GarminUploadModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="w-full max-w-sm bg-surface-card border border-surface-border rounded-2xl p-6 space-y-4 shadow-xl">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Import Garmin Data</h2>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              Upload a CSV, JSON, or ZIP export. No credentials required.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-500 hover:text-slate-200 transition-colors mt-0.5 flex-shrink-0"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <GarminUpload onSuccess={onSuccess} />
      </div>
    </div>
  )
}

// ── Upload result banner ───────────────────────────────────────────────────────

function UploadResultBanner({ result, onDismiss }: { result: UploadResult; onDismiss: () => void }) {
  return (
    <div className="rounded-xl bg-green-900/20 border border-green-700/40 px-4 py-3 space-y-1">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-good">
          Imported {result.imported} {result.imported === 1 ? 'record' : 'records'}
        </p>
        <button type="button" onClick={onDismiss} className="text-slate-500 hover:text-slate-300 text-xs">
          ✕
        </button>
      </div>
      {result.date_range && (
        <p className="text-xs text-slate-400">{result.date_range}</p>
      )}
      {result.skipped_duplicates > 0 && (
        <p className="text-xs text-slate-500">{result.skipped_duplicates} duplicates skipped</p>
      )}
      {result.skipped_errors > 0 && (
        <p className="text-xs text-slate-500">{result.skipped_errors} rows could not be parsed</p>
      )}
      {result.training_load_note && (
        <p className="text-2xs text-slate-600 leading-relaxed">{result.training_load_note}</p>
      )}
    </div>
  )
}

// ── Sync progress step ────────────────────────────────────────────────────────

interface SyncStepProps {
  sourcesConnected: Array<'whoop' | 'garmin'>
  onDone: () => void
}

function SyncStep({ sourcesConnected, onDone }: SyncStepProps) {
  const trigger = useTriggerSync()
  const statusQ = useSyncStatus()
  const { userId } = useAuth()
  const queryClient = useQueryClient()
  const triggered = useRef(false)
  const prevRunning = useRef<Set<string>>(new Set())
  const [completedSources, setCompletedSources] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    if (triggered.current) return
    triggered.current = true
    for (const source of sourcesConnected) {
      trigger.mutate(source)
    }
  }, [sourcesConnected, trigger])

  useEffect(() => {
    if (!statusQ.data) return
    const nowRunning = new Set(statusQ.data.filter((s) => s.is_running).map((s) => s.source))
    for (const source of prevRunning.current) {
      if (!nowRunning.has(source)) {
        const item = statusQ.data.find((s) => s.source === source)
        if (item?.status === 'error') {
          setErrors((prev) => ({ ...prev, [source]: item.error_message ?? 'Sync failed' }))
        } else {
          setCompletedSources((prev) => new Set([...prev, source]))
        }
      }
    }
    prevRunning.current = nowRunning
  }, [statusQ.data])

  useEffect(() => {
    const settled = completedSources.size + Object.keys(errors).length
    if (settled >= sourcesConnected.length && settled > 0) {
      void queryClient.invalidateQueries({ queryKey: ['readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['workouts'] })
      void queryClient.invalidateQueries({ queryKey: ['sleep'] })
      void queryClient.invalidateQueries({ queryKey: ['trends'] })
      void queryClient.invalidateQueries({ queryKey: ['sync', 'stats', userId] })
      const timer = setTimeout(onDone, 1200)
      return () => clearTimeout(timer)
    }
  }, [completedSources, errors, sourcesConnected.length, queryClient, userId, onDone])

  const sourceLabels: Record<string, string> = { whoop: 'Whoop', garmin: 'Garmin' }

  return (
    <div className="space-y-6 text-center">
      <div>
        <h2 className="text-xl font-bold text-slate-100">Syncing your data</h2>
        <p className="text-sm text-slate-400 mt-1">
          This may take a minute — fetching the last 30 days.
        </p>
      </div>

      <div className="space-y-3 text-left">
        {sourcesConnected.map((source) => {
          const isRunning =
            statusQ.data?.find((s) => s.source === source)?.is_running ??
            (!completedSources.has(source) && !errors[source])
          const isDone = completedSources.has(source)
          const hasError = !!errors[source]

          return (
            <div
              key={source}
              className="flex items-center gap-3 bg-surface-card border border-surface-border rounded-xl px-4 py-3"
            >
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-lg flex-shrink-0 ${
                  source === 'whoop' ? 'bg-red-500/10' : 'bg-blue-500/10'
                }`}
              >
                <span
                  className={`text-sm font-bold ${
                    source === 'whoop' ? 'text-red-400' : 'text-blue-400'
                  }`}
                >
                  {source === 'whoop' ? 'W' : 'G'}
                </span>
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-200">{sourceLabels[source]}</p>
                <p className="text-xs text-slate-500">
                  {isDone ? 'Sync complete' : hasError ? errors[source] : 'Syncing…'}
                </p>
              </div>
              <div className="flex-shrink-0">
                {isDone && <CheckIcon className="h-5 w-5 text-good" />}
                {hasError && <span className="text-poor text-lg">✕</span>}
                {isRunning && !isDone && !hasError && (
                  <Spinner className="h-5 w-5 text-slate-400" />
                )}
              </div>
            </div>
          )
        })}
      </div>

      <p className="text-xs text-slate-500">Taking you to your dashboard when ready…</p>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

type GarminModal = 'credentials' | 'upload' | null

export function Onboarding() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { userId } = useAuth()

  const flagsQ = useFeatureFlags()
  const whoopStatusQ = useWhoopStatus()
  const garminStatusQ = useGarminStatus()

  const whoopOAuthEnabled = flagsQ.data?.whoop_oauth_enabled ?? false
  const whoopConnected = whoopStatusQ.data?.connected ?? false
  const garminConnected = garminStatusQ.data?.connected ?? false

  const [step, setStep] = useState<'connect' | 'syncing'>('connect')
  const [garminModal, setGarminModal] = useState<GarminModal>(null)
  const [connectingWhoop, setConnectingWhoop] = useState(false)
  const [whoopError, setWhoopError] = useState<string | null>(null)
  const [csvResult, setCsvResult] = useState<UploadResult | null>(null)

  // Detect Whoop OAuth redirect-back
  useEffect(() => {
    const connected = searchParams.get('whoop_connected')
    const error = searchParams.get('whoop_error')
    if (connected === '1') {
      void queryClient.invalidateQueries({ queryKey: ['auth', 'whoop-status', userId] })
      setSearchParams({}, { replace: true })
    } else if (error) {
      setWhoopError(
        error === 'expired'
          ? 'Authorization expired — please try again.'
          : 'Whoop authorization failed. Please try again.',
      )
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams, queryClient, userId])

  async function handleConnectWhoop() {
    setConnectingWhoop(true)
    setWhoopError(null)
    try {
      const data = await api.get<{ url: string }>('/api/auth/whoop/url')
      window.location.href = data.url
    } catch {
      setWhoopError('Could not start Whoop authorization. Try again.')
      setConnectingWhoop(false)
    }
  }

  function handleGarminCredentialSuccess() {
    setGarminModal(null)
    void queryClient.invalidateQueries({ queryKey: ['auth', 'garmin-status', userId] })
  }

  function handleCSVSuccess(result: UploadResult) {
    setGarminModal(null)
    setCsvResult(result)
    // Treat CSV import as "garmin connected" for the onboarding flow
    void queryClient.invalidateQueries({ queryKey: ['auth', 'garmin-status', userId] })
    void queryClient.invalidateQueries({ queryKey: ['workouts'] })
  }

  function handleStartSync() {
    const sources: Array<'whoop' | 'garmin'> = []
    if (whoopConnected) sources.push('whoop')
    // Garmin credential sync — CSV users' data is already in DB, skip re-sync
    if (garminConnected && !csvResult) sources.push('garmin')

    if (sources.length === 0) {
      navigate('/', { replace: true })
      return
    }
    setStep('syncing')
  }

  if (step === 'syncing') {
    const sources: Array<'whoop' | 'garmin'> = []
    if (whoopConnected) sources.push('whoop')
    if (garminConnected && !csvResult) sources.push('garmin')

    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-bg px-4">
        <div className="w-full max-w-sm">
          <SyncStep sourcesConnected={sources} onDone={() => navigate('/', { replace: true })} />
        </div>
      </div>
    )
  }

  const anyConnected = whoopConnected || garminConnected || !!csvResult

  return (
    <>
      {garminModal === 'credentials' && (
        <GarminCredentialModal
          onClose={() => setGarminModal(null)}
          onSuccess={handleGarminCredentialSuccess}
        />
      )}
      {garminModal === 'upload' && (
        <GarminUploadModal
          onClose={() => setGarminModal(null)}
          onSuccess={handleCSVSuccess}
        />
      )}

      <div className="min-h-screen flex items-center justify-center bg-surface-bg px-4 py-12">
        <div className="w-full max-w-sm space-y-6">

          {/* Header */}
          <div className="text-center">
            <h1 className="text-2xl font-bold text-slate-100">Welcome to PulseEngine</h1>
            <p className="text-sm text-slate-400 mt-2 leading-relaxed">
              Connect your devices to start seeing personalised insights. You can always
              add or change these in Settings.
            </p>
          </div>

          {/* Whoop card */}
          <div className="bg-surface-card border border-surface-border rounded-2xl p-5 space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/10 flex-shrink-0">
                <span className="text-sm font-bold text-red-400">W</span>
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-semibold text-slate-100">Whoop</h2>
                <p className="text-xs text-slate-400">Recovery, HRV, sleep quality</p>
              </div>
              {whoopConnected && (
                <span className="flex items-center gap-1 text-xs text-good font-medium">
                  <CheckIcon className="h-4 w-4" /> Connected
                </span>
              )}
            </div>

            {whoopError && (
              <p className="text-poor text-xs bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2">
                {whoopError}
              </p>
            )}

            {!whoopConnected && (
              whoopOAuthEnabled ? (
                <button
                  type="button"
                  onClick={() => void handleConnectWhoop()}
                  disabled={connectingWhoop}
                  className="w-full bg-red-600 hover:bg-red-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-medium rounded-lg py-2 text-sm transition-colors flex items-center justify-center gap-2"
                >
                  {connectingWhoop && <Spinner />}
                  {connectingWhoop ? 'Redirecting…' : 'Connect Whoop'}
                </button>
              ) : (
                <div className="rounded-lg bg-surface-bg border border-surface-border px-4 py-3 text-center">
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Whoop OAuth is coming soon. You can connect Whoop from{' '}
                    <span className="text-slate-300">Settings</span> once approved.
                  </p>
                </div>
              )
            )}
          </div>

          {/* Garmin card */}
          <div className="bg-surface-card border border-surface-border rounded-2xl p-5 space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 flex-shrink-0">
                <span className="text-sm font-bold text-blue-400">G</span>
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-semibold text-slate-100">Garmin</h2>
                <p className="text-xs text-slate-400">Activities, training load, Body Battery</p>
              </div>
              {(garminConnected || !!csvResult) && (
                <span className="flex items-center gap-1 text-xs text-good font-medium">
                  <CheckIcon className="h-4 w-4" />
                  {csvResult ? 'Imported' : 'Connected'}
                </span>
              )}
            </div>

            {/* Upload result */}
            {csvResult && (
              <UploadResultBanner result={csvResult} onDismiss={() => setCsvResult(null)} />
            )}

            {/* Connection options — shown until connected */}
            {!garminConnected && !csvResult && (
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setGarminModal('credentials')}
                  className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg py-2 text-sm transition-colors"
                >
                  Connect with credentials
                </button>
                <button
                  type="button"
                  onClick={() => setGarminModal('upload')}
                  className="w-full border border-surface-border hover:border-blue-500/50 text-slate-300 hover:text-slate-100 font-medium rounded-lg py-2 text-sm transition-colors"
                >
                  Import from file (CSV / ZIP)
                </button>
                <p className="text-2xs text-slate-600 text-center leading-relaxed">
                  Credentials enable automatic background sync. File import is a
                  one-time privacy-preserving alternative.
                </p>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="space-y-2 pt-1">
            <button
              type="button"
              onClick={handleStartSync}
              disabled={!anyConnected}
              className="w-full bg-slate-100 hover:bg-white disabled:bg-slate-700 disabled:cursor-not-allowed text-slate-900 disabled:text-slate-400 font-semibold rounded-xl py-3 text-sm transition-colors"
            >
              {anyConnected ? 'Go to dashboard' : 'Connect a device above to continue'}
            </button>

            <button
              type="button"
              onClick={() => navigate('/', { replace: true })}
              className="w-full text-slate-500 hover:text-slate-300 py-2 text-sm transition-colors"
            >
              Skip for now
            </button>
          </div>

          <p className="text-center text-xs text-slate-600">
            You can connect or import data any time in{' '}
            <button
              type="button"
              onClick={() => navigate('/settings', { replace: true })}
              className="text-slate-400 underline hover:text-slate-200"
            >
              Settings
            </button>
            .
          </p>

        </div>
      </div>
    </>
  )
}
