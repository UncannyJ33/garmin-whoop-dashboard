/**
 * ConnectDevicesPanel — Whoop + Garmin connection cards.
 *
 * Used in:
 *   - Today.tsx  (empty state until at least one device is connected)
 *   - Onboarding.tsx  (one-time new-user flow, with action buttons)
 *
 * Pass `onStartSync` / `onSkip` to show the "Go to dashboard" / "Skip for now"
 * action row (Onboarding only). Omit them for the inline Today empty state.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import {
  useFeatureFlags,
  useGarminStatus,
  useWhoopStatus,
  type UploadResult,
} from '../hooks/useApi'
import { useAuth } from '../context/AuthContext'
import { GarminUpload } from './GarminUpload'
import { GARMIN_KEY_LABEL, GarminKeyHint, garminKeyState } from './GarminKeyStatus'

// ── helpers ─────────────────────────────────────────────────────────────────

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

// ── Garmin upload modal ──────────────────────────────────────────────────────

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

// ── Upload result banner ─────────────────────────────────────────────────────

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

// ── Main component ───────────────────────────────────────────────────────────

type GarminModal = 'upload' | null

export interface ConnectDevicesPanelProps {
  /**
   * Onboarding-only: called with the list of connected sources when the user
   * clicks "Go to dashboard". When omitted the action row is hidden.
   */
  onStartSync?: (sources: Array<'whoop' | 'garmin'>) => void
  /** Onboarding-only: called when the user clicks "Skip for now". */
  onSkip?: () => void
}

export function ConnectDevicesPanel({ onStartSync, onSkip }: ConnectDevicesPanelProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { userId } = useAuth()

  const flagsQ = useFeatureFlags()
  const whoopStatusQ = useWhoopStatus()
  const garminStatusQ = useGarminStatus()

  const whoopOAuthEnabled = flagsQ.data?.whoop_oauth_enabled ?? false
  const whoopConnected = whoopStatusQ.data?.connected ?? false
  const garminConnected = garminStatusQ.data?.connected ?? false

  const [garminModal, setGarminModal] = useState<GarminModal>(null)
  const [connectingWhoop, setConnectingWhoop] = useState(false)
  const [whoopError, setWhoopError] = useState<string | null>(null)
  const [csvResult, setCsvResult] = useState<UploadResult | null>(null)

  // Detect Whoop OAuth redirect-back (e.g. from /onboarding?whoop_connected=1)
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

  function handleCSVSuccess(result: UploadResult) {
    setGarminModal(null)
    setCsvResult(result)
    void queryClient.invalidateQueries({ queryKey: ['auth', 'garmin-status', userId] })
    void queryClient.invalidateQueries({ queryKey: ['workouts'] })
  }

  const anyConnected = whoopConnected || garminConnected || !!csvResult
  const showActions = !!onStartSync

  function handleStartSync() {
    if (!onStartSync) return
    const sources: Array<'whoop' | 'garmin'> = []
    if (whoopConnected) sources.push('whoop')
    if (garminConnected && !csvResult) sources.push('garmin')
    if (sources.length === 0) {
      navigate('/', { replace: true })
      return
    }
    onStartSync(sources)
  }

  return (
    <>
      {garminModal === 'upload' && (
        <GarminUploadModal
          onClose={() => setGarminModal(null)}
          onSuccess={handleCSVSuccess}
        />
      )}

      <div className="space-y-4">
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
                  Whoop integration coming soon.
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
            {!garminConnected && !csvResult && garminStatusQ.data?.configured && (
              <span className="text-xs text-poor font-medium">
                {GARMIN_KEY_LABEL[garminKeyState(garminStatusQ.data)]}
              </span>
            )}
            {(garminConnected || !!csvResult) && (
              <span className="flex items-center gap-1 text-xs text-good font-medium">
                <CheckIcon className="h-4 w-4" />
                {csvResult ? 'Imported' : 'Connected'}
              </span>
            )}
          </div>

          {csvResult && (
            <UploadResultBanner result={csvResult} onDismiss={() => setCsvResult(null)} />
          )}

          {!garminConnected && !csvResult && (
            <div className="space-y-2">
              <GarminKeyHint data={garminStatusQ.data} />
              <button
                type="button"
                onClick={() => setGarminModal('upload')}
                className="w-full border border-surface-border hover:border-slate-500 text-slate-300 hover:text-slate-100 font-medium rounded-lg py-2 text-sm transition-colors"
              >
                Import from file (CSV / ZIP)
              </button>
              <p className="text-2xs text-slate-600 text-center leading-relaxed">
                A Personal API key enables automatic background sync. File import is a
                one-time alternative.
              </p>
            </div>
          )}
        </div>

        {/* Action row — Onboarding only */}
        {showActions && (
          <div className="space-y-2 pt-1">
            <button
              type="button"
              onClick={handleStartSync}
              disabled={!anyConnected}
              className="w-full bg-slate-100 hover:bg-white disabled:bg-slate-700 disabled:cursor-not-allowed text-slate-900 disabled:text-slate-400 font-semibold rounded-xl py-3 text-sm transition-colors"
            >
              {anyConnected ? 'Go to dashboard' : 'Connect a device above to continue'}
            </button>

            {onSkip && (
              <button
                type="button"
                onClick={onSkip}
                className="w-full text-slate-500 hover:text-slate-300 py-2 text-sm transition-colors"
              >
                Skip for now
              </button>
            )}
          </div>
        )}

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
    </>
  )
}
