import { useState } from 'react'
import { TodayPage } from './pages/Today'
import { TrainingPage } from './pages/Training'
import { RecoveryPage } from './pages/Recovery'
import { InsightsPage } from './pages/Insights'

const PAGES = ['Today', 'Training', 'Recovery', 'Insights'] as const
type Page = typeof PAGES[number]

const NAV_ICONS: Record<Page, JSX.Element> = {
  Today: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="12" x2="15" y2="15" />
    </svg>
  ),
  Training: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 4v16M18 4v16M6 12h12M2 7h4M18 7h4M2 17h4M18 17h4" />
    </svg>
  ),
  Recovery: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
    </svg>
  ),
  Insights: (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
}

export default function App() {
  const [page, setPage] = useState<Page>('Today')

  return (
    <div className="min-h-screen flex">
      {/* Sidebar — desktop */}
      <aside
        className="hidden lg:flex flex-col flex-shrink-0 fixed inset-y-0 left-0 z-10"
        style={{ width: 216, background: 'var(--bg-card)', borderRight: '0.5px solid var(--border-subtle)' }}
      >
        {/* Logo — properly contained */}
        <div style={{
          borderBottom: '0.5px solid var(--border-subtle)',
          padding: '20px 20px 14px',
          display: 'flex',
          alignItems: 'center',
          height: 60,
          overflow: 'hidden',
        }}>
          <div style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif", display: 'flex', alignItems: 'baseline', gap: 6, whiteSpace: 'nowrap' }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: 'var(--brand)', letterSpacing: '0.04em' }}>PULSE</span>
            <span style={{ color: 'var(--text-tertiary)', fontWeight: 300, fontSize: 18 }}>|</span>
            <span style={{ fontSize: 18, fontWeight: 300, color: 'var(--text-secondary)', letterSpacing: '0.04em' }}>ENGINE</span>
          </div>
        </div>

        <nav style={{ flex: 1, padding: '10px 8px', display: 'flex', flexDirection: 'column', gap: 1 }}>
          {PAGES.map(p => {
            const a = page === p
            return (
              <button key={p} onClick={() => setPage(p)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, fontSize: 14, fontWeight: a ? 500 : 400, color: a ? 'var(--status-excellent)' : 'var(--text-secondary)', background: a ? 'var(--status-excellent-muted)' : 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', width: '100%', transition: 'all 150ms' }}>
                <span style={{ opacity: a ? 1 : 0.5 }}>{NAV_ICONS[p]}</span>
                <span>{p}</span>
              </button>
            )
          })}
        </nav>
        <div style={{ padding: '12px 16px', borderTop: '0.5px solid var(--border-subtle)' }}>
          <p style={{ fontSize: 10, color: 'var(--text-tertiary)', letterSpacing: '0.05em' }}>INTERACTIVE DEMO</p>
          <p style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>Sample data shown</p>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-10" style={{
        background: 'var(--bg-card)',
        borderBottom: '0.5px solid var(--border-subtle)',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 48,
      }}>
        <div style={{ fontFamily: "'Barlow Condensed', system-ui, sans-serif", display: 'flex', alignItems: 'baseline', gap: 4, whiteSpace: 'nowrap' }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--brand)', letterSpacing: '0.04em' }}>PULSE</span>
          <span style={{ color: 'var(--text-tertiary)', fontWeight: 300, fontSize: 16 }}>|</span>
          <span style={{ fontSize: 16, fontWeight: 300, color: 'var(--text-secondary)', letterSpacing: '0.04em' }}>ENGINE</span>
        </div>
        <span style={{ fontSize: 10, color: 'var(--text-tertiary)', letterSpacing: '0.04em' }}>DEMO</span>
      </div>

      {/* Mobile bottom tabs */}
      <div className="lg:hidden fixed bottom-0 left-0 right-0 z-10" style={{
        background: 'var(--bg-card)',
        borderTop: '0.5px solid var(--border-subtle)',
        display: 'flex',
        paddingBottom: 'max(env(safe-area-inset-bottom, 0px), 4px)',
      }}>
        {PAGES.map(p => {
          const a = page === p
          return (
            <button key={p} onClick={() => setPage(p)} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, padding: '8px 0 4px', background: 'transparent', border: 'none', cursor: 'pointer', color: a ? 'var(--status-excellent)' : 'var(--text-tertiary)', fontSize: 10, transition: 'color 150ms' }}>
              {NAV_ICONS[p]}
              <span>{p}</span>
            </button>
          )
        })}
      </div>

      {/* Main content — with proper padding to avoid overlap */}
      <main className="flex-1 lg:ml-[216px]" style={{ paddingTop: 48, paddingBottom: 80 }}>
        <div className="lg:pt-0" style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px 24px' }}>
          {page === 'Today' && <TodayPage />}
          {page === 'Training' && <TrainingPage />}
          {page === 'Recovery' && <RecoveryPage />}
          {page === 'Insights' && <InsightsPage />}
        </div>
      </main>
    </div>
  )
}
