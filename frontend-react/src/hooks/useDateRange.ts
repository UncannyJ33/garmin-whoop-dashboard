import { useEffect, useMemo, useState } from 'react'

function toISO(d: Date): string {
  return d.toLocaleDateString('en-CA')
}

/** Today's local ISO date; re-renders the caller when the date rolls over (checked each minute and on tab focus). */
export function useLocalToday(): string {
  const [today, setToday] = useState(() => toISO(new Date()))
  useEffect(() => {
    const check = () => setToday(toISO(new Date()))
    const id = window.setInterval(check, 60_000)
    document.addEventListener('visibilitychange', check)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', check)
    }
  }, [])
  return today
}

/**
 * Local date range hook for components that need an independent range
 * (e.g. a chart with its own N-day selector). For the shared page-level
 * range, use useDateRangeContext() from DateRangeContext instead.
 */
export function useDateRange(days: number = 30): { start: string; end: string } {
  const today = useLocalToday()
  return useMemo(() => {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - days + 1)
    return { start: toISO(start), end: toISO(end) }
  }, [days, today])
}

export function todayISO(): string {
  return toISO(new Date())
}
