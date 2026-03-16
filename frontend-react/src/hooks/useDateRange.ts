import { useMemo } from 'react'

function toISO(d: Date): string {
  return d.toLocaleDateString('en-CA')
}

/**
 * Local date range hook for components that need an independent range
 * (e.g. a chart with its own N-day selector). For the shared page-level
 * range, use useDateRangeContext() from DateRangeContext instead.
 */
export function useDateRange(days: number = 30): { start: string; end: string } {
  return useMemo(() => {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - days + 1)
    return { start: toISO(start), end: toISO(end) }
  }, [days])
}

export function todayISO(): string {
  return toISO(new Date())
}
