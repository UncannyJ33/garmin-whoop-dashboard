/**
 * Settings page — sync status, data overview, preferences
 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useChangePassword, useDataStats, useDeleteAccount, useDeleteGarminCredentials, useDisconnectWhoop, useFeatureFlags, useGarminCredentialsStatus, useGarminStatus, useStoreGarminCredentials, useSyncStatus, useTriggerSync, useWhoopStatus, type UploadResult } from '../hooks/useApi'
import { GarminUpload } from '../components/GarminUpload'
import { api } from '../api/client'
import { useTheme } from '../context/ThemeContext'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../context/AuthContext'

// ── helpers ────────────────────────────────────────────────────────────────────

function fmtDatetime(iso: string | null): string {
  if (!iso) return 'Never'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  }) + ' at ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function isStale(iso: string | null): boolean {
  if (!iso) return true
  return Date.now() - new Date(iso).getTime() > 24 * 60 * 60 * 1000
}

function statusLabel(status: string | null): { text: string; color: string; dot: string } {
  switch (status) {
    case 'success':
      return { text: 'Connected', color: 'text-good', dot: 'bg-good' }
    case 'error':
      return { text: 'Error', color: 'text-poor', dot: 'bg-poor' }
    case 'running':
      return { text: 'Syncing…', color: 'text-moderate', dot: 'bg-moderate' }
    case 'never_synced':
      return { text: 'Connected', color: 'text-good', dot: 'bg-good' }
    case null:
      return { text: 'Not connected', color: 'text-slate-400', dot: 'bg-slate-400' }
    default:
      return { text: status, color: 'text-slate-400', dot: 'bg-slate-400' }
  }
}

// ── sub-components ─────────────────────────────────────────────────────────────

function SourceIcon({ source }: { source: string }) {
  if (source === 'whoop') {
    return (
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/10 flex-shrink-0">
        <span className="text-sm font-bold text-red-400">W</span>
      </div>
    )
  }
  return (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 flex-shrink-0">
      <span className="text-sm font-bold text-blue-400">G</span>
    </div>
  )
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
    </svg>
  )
}

function StatRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-surface-border last:border-0">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 font-mono">{value}</span>
    </div>
  )
}

function PlaceholderRow({ label, description }: { label: string; description: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-surface-border last:border-0 opacity-40">
      <div>
        <p className="text-sm text-slate-700 dark:text-slate-300">{label}</p>
        <p className="text-2xs text-slate-500 mt-0.5">{description}</p>
      </div>
      <span className="text-2xs text-slate-400 border border-surface-border rounded px-2 py-0.5">
        Coming soon
      </span>
    </div>
  )
}

// ── sleep target localStorage key ──────────────────────────────────────────────
const SLEEP_TARGET_KEY = 'sleepTargetHours'
const DEFAULT_SLEEP_TARGET = 8

function useSleepTarget() {
  const [hours, setHoursState] = useState<number>(() => {
    const stored = localStorage.getItem(SLEEP_TARGET_KEY)
    const parsed = stored ? parseFloat(stored) : NaN
    return isNaN(parsed) ? DEFAULT_SLEEP_TARGET : Math.min(12, Math.max(4, parsed))
  })

  function setHours(h: number) {
    const clamped = Math.min(12, Math.max(4, h))
    localStorage.setItem(SLEEP_TARGET_KEY, String(clamped))
    setHoursState(clamped)
  }

  return { hours, setHours }
}

// ── page ──────────────────────────────────────────────────────────────────────

export function Settings() {
  const { theme, toggle } = useTheme()
  const { hours: sleepTarget, setHours: setSleepTarget } = useSleepTarget()
  const { userId, logout } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const statusQ = useSyncStatus()
  const statsQ  = useDataStats()
  const trigger = useTriggerSync()
  const flagsQ  = useFeatureFlags()
  const whoopOAuthEnabled = flagsQ.data?.whoop_oauth_enabled ?? false
  const whoopStatus = useWhoopStatus()
  const garminStatus = useGarminStatus()
  const garminCredsStatus = useGarminCredentialsStatus()
  const storeCredentials = useStoreGarminCredentials()
  const deleteCredentials = useDeleteGarminCredentials()
  const disconnectWhoop = useDisconnectWhoop()
  const changePassword = useChangePassword()
  const deleteAccount = useDeleteAccount()

  // Track which sources last completed (for success banner) and any trigger errors
  const [lastSyncedSource, setLastSyncedSource] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<{ source: string; message: string } | null>(null)
  // Ref tracking which sources were running on the previous render — used to detect completion
  const prevRunning = useRef<Set<string>>(new Set())
  const [connectingWhoop, setConnectingWhoop] = useState(false)

  // Whoop disconnect confirmation
  const [showDisconnectWhoop, setShowDisconnectWhoop] = useState(false)

  // Data export
  const [exportLoading, setExportLoading] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  // Change password
  const [showChangePassword, setShowChangePassword] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState(false)

  // Delete account
  const [showDeleteAccount, setShowDeleteAccount] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Handle Whoop OAuth redirect-back params
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    const whoopConnected = searchParams.get('whoop_connected')
    const whoopError = searchParams.get('whoop_error')
    if (whoopConnected === '1') {
      void queryClient.invalidateQueries({ queryKey: ['auth', 'whoop-status', userId] })
      void queryClient.invalidateQueries({ queryKey: ['sync', 'status', userId] })
      setSearchParams({}, { replace: true })
    } else if (whoopError) {
      setSyncError({ source: 'whoop', message: whoopError === 'expired' ? 'Authorization expired — please try connecting again.' : 'Whoop authorization failed. Please try again.' })
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams, queryClient, userId])

  // Garmin upload modal
  const [showCSVModal, setShowCSVModal] = useState(false)
  const [csvResult, setCsvResult] = useState<UploadResult | null>(null)

  // Garmin credential modal state
  type GarminModalMode = 'connect' | 'update' | 'remove-confirm' | null
  const [garminModal, setGarminModal] = useState<GarminModalMode>(null)
  const [garminEmail, setGarminEmail] = useState('')
  const [garminPassword, setGarminPassword] = useState('')
  const [garminConsent, setGarminConsent] = useState(false)
  const [garminCredError, setGarminCredError] = useState<string | null>(null)

  // Detect sync completion: when a source transitions from is_running → false
  useEffect(() => {
    if (!statusQ.data) return
    const nowRunning = new Set(statusQ.data.filter((s) => s.is_running).map((s) => s.source))
    for (const source of prevRunning.current) {
      if (!nowRunning.has(source)) {
        const item = statusQ.data.find((s) => s.source === source)
        if (item?.status === 'error') {
          setSyncError({ source, message: item.error_message ?? 'Sync failed' })
        } else {
          setLastSyncedSource(source)
          // Refresh all data now that the sync has finished
          void queryClient.invalidateQueries({ queryKey: ['sync', 'stats', userId] })
          void queryClient.invalidateQueries({ queryKey: ['readiness'] })
          void queryClient.invalidateQueries({ queryKey: ['workouts'] })
          void queryClient.invalidateQueries({ queryKey: ['sleep'] })
          void queryClient.invalidateQueries({ queryKey: ['trends'] })
        }
      }
    }
    prevRunning.current = nowRunning
  }, [statusQ.data, queryClient, userId])

  function handleSync(source: string) {
    setLastSyncedSource(null)
    setSyncError(null)
    trigger.mutate(source, {
      onError: (err) => setSyncError({ source, message: err instanceof Error ? err.message : 'Sync failed' }),
    })
  }

  async function handleConnectWhoop() {
    setConnectingWhoop(true)
    try {
      const data = await api.get<{ url: string }>('/api/auth/whoop/url')
      window.location.href = data.url
    } catch {
      setSyncError({ source: 'whoop', message: 'Could not start Whoop authorization. Try again.' })
      setConnectingWhoop(false)
    }
  }

  async function handleExportData() {
    setExportLoading(true)
    setExportError(null)
    try {
      const blob = await api.download('/api/account/export')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
      a.href = url
      a.download = `pulseengine_export_${today}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      setExportError('Export failed. Please try again.')
    } finally {
      setExportLoading(false)
    }
  }

  function handleChangePassword() {
    setPasswordError(null)
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match.')
      return
    }
    if (newPassword.length < 8) {
      setPasswordError('New password must be at least 8 characters.')
      return
    }
    changePassword.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: () => {
          setPasswordSuccess(true)
          setCurrentPassword('')
          setNewPassword('')
          setConfirmPassword('')
          setTimeout(() => {
            setShowChangePassword(false)
            setPasswordSuccess(false)
          }, 1500)
        },
        onError: (err) => {
          setPasswordError(err instanceof Error ? err.message : 'Could not change password.')
        },
      },
    )
  }

  function handleDeleteAccount() {
    setDeleteError(null)
    deleteAccount.mutate(undefined, {
      onSuccess: () => {
        logout()
        navigate('/login')
      },
      onError: (err) => {
        setDeleteError(err instanceof Error ? err.message : 'Could not delete account.')
      },
    })
  }

  function openGarminCredModal(mode: 'connect' | 'update') {
    setGarminEmail('')
    setGarminPassword('')
    setGarminConsent(false)
    setGarminCredError(null)
    setGarminModal(mode)
  }

  function handleStoreCredentials() {
    setGarminCredError(null)
    storeCredentials.mutate(
      { email: garminEmail, password: garminPassword, consent: garminConsent },
      {
        onSuccess: () => {
          setGarminModal(null)
          setGarminEmail('')
          setGarminPassword('')
          setGarminConsent(false)
        },
        onError: (err) => {
          setGarminCredError(err instanceof Error ? err.message : 'Could not save credentials.')
        },
      },
    )
  }

  function handleDeleteCredentials() {
    deleteCredentials.mutate(undefined, {
      onSuccess: () => setGarminModal(null),
      onError: (err) => setGarminCredError(err instanceof Error ? err.message : 'Could not remove credentials.'),
    })
  }

  return (
    <div className="space-y-4 pb-16 max-w-2xl">

      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 animate-fade-in">Settings</h1>

      {/* ── SECTION 1: Sync Status ───────────────────────────────────────────── */}
      <div className="space-y-3 animate-fade-in delay-1">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 px-1">
          Data Sources
        </p>

        {statusQ.isLoading && (
          <>
            <div className="card space-y-4">
              <div className="flex items-center gap-3">
                <div className="skeleton h-10 w-10 rounded-xl flex-shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="skeleton h-4 w-16 rounded" />
                  <div className="skeleton h-3 w-24 rounded" />
                </div>
                <div className="skeleton h-7 w-20 rounded-lg" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="skeleton h-14 rounded-lg" />
                <div className="skeleton h-14 rounded-lg" />
              </div>
            </div>
            <div className="card space-y-4">
              <div className="flex items-center gap-3">
                <div className="skeleton h-10 w-10 rounded-xl flex-shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="skeleton h-4 w-16 rounded" />
                  <div className="skeleton h-3 w-24 rounded" />
                </div>
                <div className="skeleton h-7 w-20 rounded-lg" />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="skeleton h-14 rounded-lg" />
                <div className="skeleton h-14 rounded-lg" />
              </div>
            </div>
          </>
        )}

        {(statusQ.data ?? []).map(source => {
          const isSyncing = source.is_running || (trigger.isPending && trigger.variables === source.source)
          const label = source.source === 'whoop' ? 'Whoop' : 'Garmin'
          const isWhoop = source.source === 'whoop'
          const isGarmin = source.source === 'garmin'

          // Drive connection status from token existence (not sync_log) for both sources.
          // Default to false while loading — safer than defaulting to true, which would
          // briefly show "Sync Now" on new unconnected accounts before the query resolves.
          const whoopConnected = whoopStatus.data?.connected ?? false
          const garminConnected = garminStatus.data?.connected ?? false
          const isConnected = isWhoop ? whoopConnected : garminConnected

          const rawStatus = !isConnected ? null : source.status
          const { text, color, dot } = statusLabel(rawStatus)

          return (
            <div key={source.source} className="card space-y-4">
              {/* Header row */}
              <div className="flex items-center gap-3">
                <SourceIcon source={source.source} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{label}</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${dot}`} />
                    <span className={`text-xs ${color}`}>{text}</span>
                  </div>
                </div>

                {/* Show Connect button when not connected, Sync Now when connected */}
                {!isConnected ? (
                  isWhoop && !whoopOAuthEnabled ? (
                    <span className="rounded-lg px-3 py-1.5 text-xs text-slate-500 border border-surface-border">
                      Coming soon
                    </span>
                  ) : (
                    <button
                      onClick={() => {
                        if (isWhoop) void handleConnectWhoop()
                        else openGarminCredModal('connect')
                      }}
                      disabled={isWhoop ? connectingWhoop : false}
                      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                        (isWhoop && connectingWhoop)
                          ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                          : isWhoop ? 'bg-red-500 text-white' : 'bg-blue-600 text-white'
                      }`}
                    >
                      {isWhoop && connectingWhoop
                        ? <><Spinner /> Connecting…</>
                        : isWhoop ? 'Connect Whoop' : 'Connect Garmin'}
                    </button>
                  )
                ) : (
                  <button
                    onClick={() => handleSync(source.source)}
                    disabled={isSyncing}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                      isSyncing
                        ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                        : 'bg-brand text-white'
                    }`}
                  >
                    {isSyncing ? <><Spinner /> Syncing…</> : 'Sync Now'}
                  </button>
                )}
              </div>

              {/* Whoop: disconnect option when connected */}
              {isWhoop && isConnected && (
                <div className="flex justify-end">
                  <button
                    onClick={() => setShowDisconnectWhoop(true)}
                    className="text-2xs text-slate-500 hover:text-poor underline transition-colors"
                  >
                    Disconnect Whoop
                  </button>
                </div>
              )}

              {/* Garmin: credential management */}
              {isGarmin && (
                <div className="space-y-2">
                  {/* Auto-sync status when credentials stored */}
                  {garminCredsStatus.data?.has_credentials ? (
                    <div className="rounded-lg bg-good/5 border border-good/20 px-3 py-2 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium text-good">Auto-sync enabled ✓</span>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => openGarminCredModal('update')}
                            className="text-2xs text-slate-400 hover:text-slate-200 underline transition-colors"
                          >
                            Update
                          </button>
                          <button
                            onClick={() => { setGarminCredError(null); setGarminModal('remove-confirm') }}
                            className="text-2xs text-poor hover:text-red-300 underline transition-colors"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                      {garminCredsStatus.data.last_sync_at && (
                        <p className="text-2xs text-slate-500">
                          Last auto-sync: {fmtDatetime(garminCredsStatus.data.last_sync_at)}
                        </p>
                      )}
                    </div>
                  ) : (
                    /* No credentials — show enable option */
                    !garminConnected && (
                      <button
                        onClick={() => openGarminCredModal('connect')}
                        className="w-full rounded-lg border border-dashed border-blue-500/30 px-3 py-2 text-xs text-blue-400 hover:text-blue-300 hover:border-blue-400/50 transition-colors text-left"
                      >
                        Enable auto-sync →
                      </button>
                    )
                  )}

                  {/* File import option */}
                  {!garminConnected && !garminCredsStatus.data?.has_credentials ? (
                    <div className="space-y-1.5">
                      <button
                        onClick={() => { setCsvResult(null); setShowCSVModal(true) }}
                        className="w-full rounded-lg border border-dashed border-surface-border px-3 py-2 text-xs text-slate-400 hover:text-slate-200 hover:border-blue-500/50 transition-colors text-left"
                      >
                        Or import activities (CSV, JSON, or ZIP export) →
                      </button>
                      {csvResult && (
                        <div className="rounded-lg bg-good/5 border border-good/20 px-3 py-2 text-xs text-good">
                          Imported {csvResult.imported} records
                          {csvResult.date_range ? ` (${csvResult.date_range})` : ''}
                          {csvResult.skipped_duplicates > 0 ? `, ${csvResult.skipped_duplicates} duplicates skipped` : ''}
                        </div>
                      )}
                    </div>
                  ) : garminConnected && (
                    <button
                      onClick={() => { setCsvResult(null); setShowCSVModal(true) }}
                      className="text-2xs text-slate-500 hover:text-slate-300 underline transition-colors"
                    >
                      Import historical activities from file
                    </button>
                  )}
                </div>
              )}

              {/* Stats grid */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-lg bg-surface-overlay px-3 py-2 space-y-0.5">
                  <p className="text-slate-500">Last sync</p>
                  <p className="font-medium text-slate-700 dark:text-slate-300 leading-snug">
                    {fmtDatetime(source.last_sync_at)}
                  </p>
                </div>
                <div className="rounded-lg bg-surface-overlay px-3 py-2 space-y-0.5">
                  <p className="text-slate-500">Records stored</p>
                  <p className="font-mono font-semibold text-slate-800 dark:text-slate-100">
                    {source.records_stored != null ? source.records_stored.toLocaleString() : '—'}
                  </p>
                </div>
              </div>

              {/* Stale sync warning */}
              {isConnected && isStale(source.last_sync_at) && (
                <div className="rounded-lg bg-moderate/10 border border-moderate/30 px-3 py-2 text-xs text-moderate flex items-start gap-2">
                  <span className="mt-0.5 flex-shrink-0">⚠</span>
                  <span>
                    {source.last_sync_at
                      ? 'Last sync was over 24 hours ago — your data may be outdated. Tap Sync Now to refresh.'
                      : 'No sync on record — tap Sync Now to load your data.'}
                  </span>
                </div>
              )}

              {/* Error message */}
              {source.error_message && (
                <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                  <span className="font-semibold">Error: </span>
                  {source.error_message}
                </div>
              )}

              {/* Success toast after sync */}
              {lastSyncedSource === source.source && !isSyncing && (
                <div className="rounded-lg bg-good/5 border border-good/20 px-3 py-2 text-xs text-good">
                  Sync complete
                  {source.records_stored != null ? ` — ${source.records_stored} records stored` : ''}
                </div>
              )}

              {/* Sync trigger error */}
              {syncError?.source === source.source && !isSyncing && (
                <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                  <span className="font-semibold">Sync failed: </span>
                  {syncError.message}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── SECTION 2: Data Overview ─────────────────────────────────────────── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 px-1">
          Data Overview
        </p>

        <div className="card">
          {statsQ.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="skeleton h-9 rounded-lg" />
              ))}
            </div>
          ) : statsQ.isError ? (
            <p className="text-sm text-slate-400">Could not load data overview.</p>
          ) : statsQ.data ? (
            <>
              <StatRow label="Total days of data"      value={statsQ.data.total_days.toLocaleString()} />
              <StatRow label="Total workouts tracked"  value={statsQ.data.total_workouts.toLocaleString()} />
              <StatRow
                label="Dual-source workouts"
                value={
                  statsQ.data.total_workouts > 0
                    ? `${statsQ.data.matched_workouts} (${Math.round((statsQ.data.matched_workouts / statsQ.data.total_workouts) * 100)}%)`
                    : '0'
                }
              />
              <StatRow label="Date range start" value={fmtDate(statsQ.data.date_start)} />
              <StatRow label="Date range end"   value={fmtDate(statsQ.data.date_end)} />
            </>
          ) : null}
        </div>
      </div>

      {/* ── SECTION 3: Preferences ───────────────────────────────────────────── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 px-1">
          Preferences
        </p>

        <div className="card divide-y divide-surface-border">

          {/* Dark / light mode */}
          <div className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Appearance</p>
              <p className="text-2xs text-slate-500 mt-0.5">
                {theme === 'dark' ? 'Dark mode active' : 'Light mode active'}
              </p>
            </div>
            <button
              onClick={toggle}
              className={`relative h-6 w-11 rounded-full transition-colors duration-200 focus:outline-none ${
                theme === 'dark' ? 'bg-brand' : 'bg-slate-300 dark:bg-slate-600'
              }`}
              aria-label="Toggle dark mode"
            >
              <span
                className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 ${
                  theme === 'dark' ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* Sleep target */}
          <div className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
            <div>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Sleep target</p>
              <p className="text-2xs text-slate-500 mt-0.5">Hours per night used for sleep debt estimate</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSleepTarget(sleepTarget - 0.5)}
                disabled={sleepTarget <= 4}
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-30 text-base leading-none transition-colors"
                aria-label="Decrease sleep target"
              >
                −
              </button>
              <span className="w-12 text-center font-mono text-sm font-semibold text-slate-800 dark:text-slate-100">
                {sleepTarget % 1 === 0 ? `${sleepTarget}h` : `${sleepTarget}h`}
              </span>
              <button
                onClick={() => setSleepTarget(sleepTarget + 0.5)}
                disabled={sleepTarget >= 12}
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-30 text-base leading-none transition-colors"
                aria-label="Increase sleep target"
              >
                +
              </button>
            </div>
          </div>

          {/* Placeholders */}
          <PlaceholderRow
            label="Notifications"
            description="Daily readiness alerts and anomaly notifications"
          />
          <PlaceholderRow
            label="Training zones"
            description="Custom heart rate zone thresholds"
          />
        </div>
      </div>

      {/* ── SECTION 4: Data Export ───────────────────────────────────────────── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 px-1">
          Data Export
        </p>
        <div className="card space-y-3">
          <div>
            <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Export My Data</p>
            <p className="text-2xs text-slate-500 mt-0.5 leading-relaxed">
              Download all your fitness data as a ZIP file containing CSV files for workouts, sleep, daily metrics, and recovery.
            </p>
          </div>
          {exportError && (
            <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
              {exportError}
            </div>
          )}
          <button
            onClick={() => void handleExportData()}
            disabled={exportLoading}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-semibold transition-colors ${
              exportLoading
                ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                : 'bg-brand text-white'
            }`}
          >
            {exportLoading ? <><Spinner /> Preparing export…</> : 'Download ZIP'}
          </button>
        </div>
      </div>

      {/* ── SECTION 5: Account Management ────────────────────────────────────── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 px-1">
          Account Management
        </p>
        <div className="card divide-y divide-surface-border">

          {/* Change password */}
          <div className="py-3 first:pt-0 last:pb-0 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-300">Password</p>
                <p className="text-2xs text-slate-500 mt-0.5">Update your login password</p>
              </div>
              <button
                onClick={() => {
                  setCurrentPassword('')
                  setNewPassword('')
                  setConfirmPassword('')
                  setPasswordError(null)
                  setPasswordSuccess(false)
                  setShowChangePassword(!showChangePassword)
                }}
                className="text-xs text-brand hover:text-brand/80 underline transition-colors"
              >
                {showChangePassword ? 'Cancel' : 'Change'}
              </button>
            </div>
            {showChangePassword && (
              <div className="space-y-2.5">
                <input
                  type="password"
                  value={currentPassword}
                  onChange={e => setCurrentPassword(e.target.value)}
                  placeholder="Current password"
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  placeholder="New password (min 8 chars)"
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand"
                />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand"
                  onKeyDown={e => {
                    if (e.key === 'Enter' && currentPassword && newPassword && confirmPassword && !changePassword.isPending)
                      handleChangePassword()
                  }}
                />
                {passwordError && (
                  <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                    {passwordError}
                  </div>
                )}
                {passwordSuccess && (
                  <div className="rounded-lg bg-good/5 border border-good/20 px-3 py-2 text-xs text-good">
                    Password updated successfully.
                  </div>
                )}
                <button
                  onClick={handleChangePassword}
                  disabled={changePassword.isPending || !currentPassword || !newPassword || !confirmPassword}
                  className={`w-full flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                    changePassword.isPending || !currentPassword || !newPassword || !confirmPassword
                      ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                      : 'bg-brand text-white'
                  }`}
                >
                  {changePassword.isPending ? <><Spinner /> Saving…</> : 'Save New Password'}
                </button>
              </div>
            )}
          </div>

        </div>
      </div>

      {/* ── SECTION: Danger Zone ─────────────────────────────────────────────── */}
      <div className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider px-1" style={{ color: 'var(--status-alert)' }}>
          Danger Zone
        </p>
        <div
          className="card"
          style={{ borderColor: 'rgba(232,119,90,0.25)', background: 'rgba(232,119,90,0.04)' }}
        >
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>Delete Account</p>
              <p className="text-2xs text-slate-500 mt-0.5 leading-relaxed">
                Permanently delete your account and all associated data. This cannot be undone.
              </p>
            </div>
            <button
              onClick={() => { setDeleteConfirmText(''); setDeleteError(null); setShowDeleteAccount(true) }}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500/50 ml-4 flex-shrink-0"
              style={{
                color:       'var(--status-alert)',
                borderColor: 'rgba(232,119,90,0.35)',
              }}
            >
              Delete
            </button>
          </div>
        </div>
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <p className="text-center text-xs text-slate-600 pt-2">
        <Link to="/privacy" className="hover:text-slate-400 transition-colors">
          Privacy Policy
        </Link>
      </p>

      {/* ── Garmin Upload Modal ──────────────────────────────────────────────── */}
      {showCSVModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface-card border border-surface-border shadow-2xl p-6 space-y-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Import Garmin Data</h2>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  Upload a CSV, JSON, or ZIP export. No credentials required.
                </p>
              </div>
              <button
                onClick={() => setShowCSVModal(false)}
                className="text-slate-500 hover:text-slate-200 transition-colors mt-0.5 flex-shrink-0"
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <GarminUpload
              onSuccess={(result) => {
                setCsvResult(result)
                setShowCSVModal(false)
              }}
            />
          </div>
        </div>
      )}

      {/* ── Garmin Credential Modal (connect / update) ───────────────────────── */}
      {(garminModal === 'connect' || garminModal === 'update') && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface-card border border-surface-border shadow-2xl p-6 space-y-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">
                  {garminModal === 'update' ? 'Update Garmin Credentials' : 'Enable Garmin Auto-Sync'}
                </h2>
                <p className="text-xs text-slate-500 mt-1">
                  {garminModal === 'update'
                    ? 'Enter your new Garmin Connect email and password.'
                    : 'Sync your Garmin data automatically every 15 minutes.'}
                </p>
              </div>
              <button
                onClick={() => setGarminModal(null)}
                className="text-slate-500 hover:text-slate-200 transition-colors mt-0.5 flex-shrink-0"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {/* Disclosure callout */}
            <div className="rounded-lg bg-blue-500/5 border border-blue-500/20 px-3 py-2.5 text-xs text-slate-400 leading-relaxed space-y-1">
              <p className="font-semibold text-blue-400">How your credentials are protected</p>
              <p>
                Your Garmin email and password are encrypted using AES-128-CBC + HMAC-SHA256 (Fernet)
                before being stored. The encryption key is separate from your data and never logged.
                Your credentials are used only to authenticate with Garmin Connect on your behalf
                during scheduled syncs.
              </p>
              <p>You can remove your credentials at any time from this page.</p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                  Garmin Connect Email
                </label>
                <input
                  type="email"
                  value={garminEmail}
                  onChange={e => setGarminEmail(e.target.value)}
                  placeholder="you@example.com"
                  autoComplete="username"
                  className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                  Garmin Connect Password
                </label>
                <input
                  type="password"
                  value={garminPassword}
                  onChange={e => setGarminPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand"
                  onKeyDown={e => { if (e.key === 'Enter' && garminConsent && garminEmail && garminPassword && !storeCredentials.isPending) handleStoreCredentials() }}
                />
              </div>
            </div>

            {/* Consent checkbox */}
            <label className="flex items-start gap-2.5 cursor-pointer group">
              <input
                type="checkbox"
                checked={garminConsent}
                onChange={e => setGarminConsent(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-surface-border accent-brand flex-shrink-0"
              />
              <span className="text-xs text-slate-400 group-hover:text-slate-300 transition-colors leading-relaxed">
                I consent to my encrypted Garmin credentials being stored for automatic background sync.
              </span>
            </label>

            {garminCredError && (
              <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                {garminCredError}
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setGarminModal(null)}
                disabled={storeCredentials.isPending}
                className="flex-1 rounded-lg border border-surface-border px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-surface-overlay transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleStoreCredentials}
                disabled={storeCredentials.isPending || !garminEmail || !garminPassword || !garminConsent}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                  storeCredentials.isPending || !garminEmail || !garminPassword || !garminConsent
                    ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                    : 'bg-blue-600 text-white'
                }`}
              >
                {storeCredentials.isPending ? <><Spinner /> Saving…</> : garminModal === 'update' ? 'Update' : 'Enable Auto-Sync'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Whoop Disconnect Confirmation Modal ──────────────────────────────── */}
      {showDisconnectWhoop && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface-card border border-surface-border shadow-2xl p-6 space-y-4">
            <div>
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Disconnect Whoop?</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                Your Whoop authorization token will be removed. Automatic sync will stop and your Whoop data will remain in PulseEngine.
                You can reconnect at any time.
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowDisconnectWhoop(false)}
                disabled={disconnectWhoop.isPending}
                className="flex-1 rounded-lg border border-surface-border px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-surface-overlay transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={() => disconnectWhoop.mutate(undefined, { onSuccess: () => setShowDisconnectWhoop(false) })}
                disabled={disconnectWhoop.isPending}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                  disconnectWhoop.isPending
                    ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                    : 'bg-red-600 text-white hover:bg-red-700'
                }`}
              >
                {disconnectWhoop.isPending ? <><Spinner /> Disconnecting…</> : 'Disconnect'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Account Modal ──────────────────────────────────────────────── */}
      {showDeleteAccount && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface-card border border-surface-border shadow-2xl p-6 space-y-4">
            <div>
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Delete Account</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                This will permanently delete your account, all synced data, credentials, and tokens.
                <span className="text-poor font-semibold"> This action cannot be undone.</span>
              </p>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                Type <span className="font-mono font-bold text-poor">DELETE</span> to confirm
              </label>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={e => setDeleteConfirmText(e.target.value)}
                placeholder="DELETE"
                className="w-full rounded-lg border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-poor"
              />
            </div>
            {deleteError && (
              <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                {deleteError}
              </div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => setShowDeleteAccount(false)}
                disabled={deleteAccount.isPending}
                className="flex-1 rounded-lg border border-surface-border px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-surface-overlay transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteAccount}
                disabled={deleteAccount.isPending || deleteConfirmText !== 'DELETE'}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                  deleteAccount.isPending || deleteConfirmText !== 'DELETE'
                    ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                    : 'bg-red-600 text-white hover:bg-red-700'
                }`}
              >
                {deleteAccount.isPending ? <><Spinner /> Deleting…</> : 'Delete My Account'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Garmin Remove Confirmation Modal ─────────────────────────────────── */}
      {garminModal === 'remove-confirm' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl bg-surface-card border border-surface-border shadow-2xl p-6 space-y-4">
            <div>
              <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Remove Garmin Credentials?</h2>
              <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                Your encrypted credentials will be permanently deleted and automatic sync will stop.
                You can re-enable auto-sync at any time by adding your credentials again.
              </p>
            </div>

            {garminCredError && (
              <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                {garminCredError}
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <button
                onClick={() => setGarminModal(null)}
                disabled={deleteCredentials.isPending}
                className="flex-1 rounded-lg border border-surface-border px-3 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-surface-overlay transition-colors disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteCredentials}
                disabled={deleteCredentials.isPending}
                className={`flex-1 flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                  deleteCredentials.isPending
                    ? 'bg-slate-500 text-slate-400 cursor-not-allowed'
                    : 'bg-red-600 text-white hover:bg-red-700'
                }`}
              >
                {deleteCredentials.isPending ? <><Spinner /> Removing…</> : 'Remove Credentials'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
