/** Garmin Personal API key status helpers + hint block (shared by Settings and ConnectDevicesPanel). */

export const GARMIN_KEY_PAGE_URL = 'https://connect.garmin.com/app/settings/personalApiToken'

export interface GarminKeyStatusData {
  connected: boolean
  configured: boolean
  error: string | null
}

export type GarminKeyState = 'connected' | 'not_set' | 'rejected' | 'unreachable'

export function garminKeyState(data: GarminKeyStatusData | undefined): GarminKeyState {
  if (!data || !data.configured) return 'not_set'
  if (data.connected) return 'connected'
  const err = (data.error ?? '').toLowerCase()
  return err.includes('personalapitoken') || err.includes('rejected') ? 'rejected' : 'unreachable'
}

export const GARMIN_KEY_LABEL: Record<GarminKeyState, string> = {
  connected: 'Connected',
  not_set: 'Key not set',
  rejected: 'Key rejected',
  unreachable: "Can't reach Garmin",
}

export function GarminKeyHint({ data }: { data: GarminKeyStatusData | undefined }) {
  const state = garminKeyState(data)
  return (
    <div className="space-y-1.5 text-xs text-slate-400 leading-relaxed">
      {(state === 'rejected' || state === 'unreachable') && data?.error && (
        <p className="rounded-lg bg-poor/5 border border-poor/20 px-3 py-2 text-poor">
          <span className="font-semibold">{GARMIN_KEY_LABEL[state]}: </span>
          {data.error}
        </p>
      )}
      <p>
        Set <code className="font-mono">GARMIN_PERSONAL_API_KEY</code> in <code className="font-mono">.env</code> and restart.
      </p>
      <a
        href={GARMIN_KEY_PAGE_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-400 hover:text-blue-300 underline"
      >
        Get your Personal API key from Garmin Connect
      </a>
    </div>
  )
}
