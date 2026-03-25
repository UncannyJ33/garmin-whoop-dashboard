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
