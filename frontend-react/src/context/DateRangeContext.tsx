import { createContext, useContext, useMemo, useState } from 'react'

function toISO(d: Date): string {
  return d.toLocaleDateString('en-CA')
}

function rangeFromDays(days: number): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - days + 1)
  return { start: toISO(start), end: toISO(end) }
}

interface DateRangeContextValue {
  days: number
  setDays: (days: number) => void
  start: string
  end: string
}

const DateRangeContext = createContext<DateRangeContextValue>({
  days: 30,
  setDays: () => {},
  ...rangeFromDays(30),
})

export function DateRangeProvider({ children }: { children: React.ReactNode }) {
  const [days, setDays] = useState(30)

  const { start, end } = useMemo(() => rangeFromDays(days), [days])

  return (
    <DateRangeContext.Provider value={{ days, setDays, start, end }}>
      {children}
    </DateRangeContext.Provider>
  )
}

/** Shared date range state. Pages use this for consistent filtering. */
export function useDateRangeContext() {
  return useContext(DateRangeContext)
}

export function todayISO(): string {
  return toISO(new Date())
}
