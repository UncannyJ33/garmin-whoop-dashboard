/**
 * Settings page — sync status, data overview, preferences
 */
import { useState } from 'react'
import { useDataStats, useSyncStatus, useTriggerSync } from '../hooks/useApi'
import { useTheme } from '../context/ThemeContext'

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

function statusLabel(status: string | null): { text: string; color: string; dot: string } {
  switch (status) {
    case 'success':
      return { text: 'Connected', color: 'text-good', dot: 'bg-good' }
    case 'error':
      return { text: 'Error', color: 'text-poor', dot: 'bg-poor' }
    case 'running':
      return { text: 'Syncing…', color: 'text-moderate', dot: 'bg-moderate' }
    case 'never_synced':
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

  const statusQ = useSyncStatus()
  const statsQ  = useDataStats()
  const trigger = useTriggerSync()

  // Track which source is currently being synced + which last succeeded
  const [syncingSource, setSyncingSource] = useState<string | null>(null)
  const [lastSyncedSource, setLastSyncedSource] = useState<string | null>(null)

  function handleSync(source: string) {
    setSyncingSource(source)
    setLastSyncedSource(null)
    trigger.mutate(source, {
      onSuccess: () => setLastSyncedSource(source),
      onSettled: () => setSyncingSource(null),
    })
  }

  return (
    <div className="space-y-4 pb-16 max-w-2xl">

      <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Settings</h1>

      {/* ── SECTION 1: Sync Status ───────────────────────────────────────────── */}
      <div className="space-y-3">
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
          const { text, color, dot } = statusLabel(source.status)
          const isSyncing = syncingSource === source.source
          const label = source.source === 'whoop' ? 'Whoop' : 'Garmin'

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
                <button
                  onClick={() => handleSync(source.source)}
                  disabled={isSyncing || trigger.isPending}
                  className="flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60 transition-opacity"
                >
                  {isSyncing ? <><Spinner /> Syncing…</> : 'Sync Now'}
                </button>
              </div>

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

              {/* Error message */}
              {source.error_message && (
                <div className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-xs text-poor">
                  <span className="font-semibold">Error: </span>
                  {source.error_message}
                </div>
              )}

              {/* Success toast after sync */}
              {lastSyncedSource === source.source && !isSyncing && trigger.data && (
                <div className="rounded-lg bg-good/5 border border-good/20 px-3 py-2 text-xs text-good">
                  Sync complete — {trigger.data.records_stored} records stored
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
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-30 text-base leading-none transition-colors"
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
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-surface-overlay text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-30 text-base leading-none transition-colors"
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
            label="Export data"
            description="Download your fitness data as CSV or JSON"
          />
          <PlaceholderRow
            label="Training zones"
            description="Custom heart rate zone thresholds"
          />
        </div>
      </div>

    </div>
  )
}
