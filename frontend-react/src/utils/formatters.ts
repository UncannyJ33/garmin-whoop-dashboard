/** Format a snake_case activity type to Title Case (e.g. "strength_training" → "Strength Training"). */
export function activityLabel(type: string): string {
  return type.split('_').map(s => s[0].toUpperCase() + s.slice(1)).join(' ')
}

/** Format minutes into "Xh Ym" or "—" if null. */
export function fmtDuration(minutes: number | null): string {
  if (minutes == null) return '—'
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

/** "Mar 5" — accepts YYYY-MM-DD or a full ISO timestamp (date-only gets noon appended to avoid UTC day shift). */
export function fmtDate(iso: string): string {
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** "Mar 5, 2026", or "—" when null. */
export function fmtDateFull(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
