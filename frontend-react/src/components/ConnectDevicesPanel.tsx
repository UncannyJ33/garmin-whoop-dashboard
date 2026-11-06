/**
 * ConnectDevicesPanel — Whoop + Garmin connection cards.
 *
 * Used in Today.tsx as the empty state until at least one device is connected.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import {
  useGarminStatus,
  useWhoopStatus,
} from '../hooks/useApi'
import { useAuth } from '../context/AuthContext'
import type { UploadResult } from '../types/api'
import { Spinner } from './Spinner'
import { GarminUpload } from './GarminUpload'
import { GARMIN_KEY_LABEL, GarminKeyHint, garminKeyState } from './GarminKeyStatus'

// ── helpers ─────────────────────────────────────────────────────────────────

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

export function ConnectDevicesPanel() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { userId } = useAuth()

  const whoopStatusQ = useWhoopStatus()
  const garminStatusQ = useGarminStatus()

  const whoopConnected = whoopStatusQ.data?.connected ?? false
  const garminConnected = garminStatusQ.data?.connected ?? false

  const [garminModal, setGarminModal] = useState<GarminModal>(null)
  const [connectingWhoop, setConnectingWhoop] = useState(false)
  const [whoopError, setWhoopError] = useState<string | null>(null)
  const [csvResult, setCsvResult] = useState<UploadResult | null>(null)

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
            <button
              type="button"
              onClick={() => void handleConnectWhoop()}
              disabled={connectingWhoop}
              className="w-full bg-red-600 hover:bg-red-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white font-medium rounded-lg py-2 text-sm transition-colors flex items-center justify-center gap-2"
            >
              {connectingWhoop && <Spinner />}
              {connectingWhoop ? 'Redirecting…' : 'Connect Whoop'}
            </button>
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
