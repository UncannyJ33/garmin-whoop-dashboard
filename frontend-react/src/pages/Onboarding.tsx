/**
 * New-user onboarding — connect Whoop + Garmin, trigger initial sync.
 *
 * The device-connection cards live in ConnectDevicesPanel (also used by Today
 * as a persistent empty state until the user has data).
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  useSyncStatus,
  useTriggerSync,
} from '../hooks/useApi'
import { useAuth } from '../context/AuthContext'
import { ConnectDevicesPanel } from '../components/ConnectDevicesPanel'

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

export function Onboarding() {
  const navigate = useNavigate()
  const [step, setStep] = useState<'connect' | 'syncing'>('connect')
  const [syncSources, setSyncSources] = useState<Array<'whoop' | 'garmin'>>([])

  function handleStartSync(sources: Array<'whoop' | 'garmin'>) {
    if (sources.length === 0) {
      navigate('/', { replace: true })
      return
    }
    setSyncSources(sources)
    setStep('syncing')
  }

  if (step === 'syncing') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-bg px-4">
        <div className="w-full max-w-sm">
          <SyncStep sourcesConnected={syncSources} onDone={() => navigate('/', { replace: true })} />
        </div>
      </div>
    )
  }

  return (
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

        <ConnectDevicesPanel
          onStartSync={handleStartSync}
          onSkip={() => navigate('/', { replace: true })}
        />

      </div>
    </div>
  )
}
