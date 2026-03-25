import type { ReactNode } from 'react'
import { useEffect } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  /** Optional short description rendered below the title. Accepts ReactNode for inline formatting. */
  description?: ReactNode
  children?: ReactNode
}

export function Modal({ open, onClose, title, description, children }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm"
        style={{
          background:    'var(--bg-card-elevated)',
          border:        '0.5px solid var(--border-hover)',
          borderRadius:  16,
          padding:       24,
          boxShadow:     '0 24px 48px rgba(0,0,0,0.6)',
          display:       'flex',
          flexDirection: 'column',
          gap:           16,
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', marginBottom: description ? 4 : 0 }}>
              {title}
            </h2>
            {description && (
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {description}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background:  'none',
              border:      'none',
              cursor:      'pointer',
              color:       'var(--text-tertiary)',
              flexShrink:  0,
              marginTop:   2,
              fontSize:    14,
              lineHeight:  1,
              padding:     4,
              transition:  'color 150ms ease',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-tertiary)')}
          >
            ✕
          </button>
        </div>

        {/* Content */}
        {children}
      </div>
    </div>
  )
}
