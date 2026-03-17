/**
 * DigestCard — displays one weekly takeaway on the Insights page.
 *
 * Design spec §3.8:
 * - bg-card background, border-subtle, 12px radius, 16px 20px padding
 * - 6px category dot (teal=recovery, amber=training, indigo=sleep, coral=anomaly)
 * - Insight text 14px text-primary, supporting data 12px text-tertiary
 */

type DigestCategory = 'recovery' | 'training' | 'sleep' | 'readiness' | 'anomaly'

interface DigestCardProps {
  insight: string
  supportingData?: string
  category?: DigestCategory
  className?: string
}

const CATEGORY_COLOR: Record<DigestCategory, string> = {
  recovery: 'var(--status-excellent)',  // teal
  readiness:'var(--status-excellent)',  // teal
  training: 'var(--status-caution)',    // amber
  sleep:    '#8b5fbf',                  // indigo/purple
  anomaly:  'var(--status-alert)',      // coral
}

function inferCategory(text: string): DigestCategory {
  const t = text.toLowerCase()
  if (t.includes('sleep'))      return 'sleep'
  if (t.includes('train') || t.includes('session') || t.includes('acwr') || t.includes('workout')) return 'training'
  if (t.includes('recover'))    return 'recovery'
  if (t.includes('notable') || t.includes('anomal')) return 'anomaly'
  return 'readiness'
}

export function DigestCard({ insight, supportingData, category, className = '' }: DigestCardProps) {
  const cat = category ?? inferCategory(insight)
  const dotColor = CATEGORY_COLOR[cat]

  return (
    <div
      className={`${className}`}
      style={{
        background:   'var(--bg-card)',
        border:       '0.5px solid var(--border-subtle)',
        borderRadius: 12,
        padding:      '16px 20px',
        transition:   'border-color 150ms ease',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--border-hover)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border-subtle)')}
    >
      <div className="flex items-start gap-3">
        {/* Category dot */}
        <span
          className="flex-shrink-0 mt-1.5"
          style={{
            width:        6,
            height:       6,
            borderRadius: '50%',
            backgroundColor: dotColor,
            display:      'block',
          }}
        />
        <div className="space-y-1">
          <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.5 }}>
            {insight}
          </p>
          {supportingData && (
            <p style={{ fontSize: 12, color: 'var(--text-tertiary)', lineHeight: 1.4 }}>
              {supportingData}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
