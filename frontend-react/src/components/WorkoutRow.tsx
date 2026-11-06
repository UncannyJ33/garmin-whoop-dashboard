/**
 * WorkoutRow — expandable row in the workout log.
 *
 * Design spec §3.6:
 * Collapsed: date (secondary), type (primary), duration, strain (colored), source badge, chevron.
 * Expanded: sections with border-subtle dividers, running dynamics sub-section, HR zone bar.
 * Source badge: 10px, 4px 8px padding, subtle tint, 4px radius.
 * HR zone bar: blue→teal→green→amber→coral gradient, 8px height, rounded.
 */

import { memo, useState } from 'react'
import type { EnrichedWorkout } from '../types/api'
import { DataSourceBadge } from './DataSourceBadge'
import { useExerciseSets } from '../hooks/useApi'
import { activityLabel } from '../utils/formatters'
import { KG_TO_LB, STRENGTH_TYPES } from '../utils/workoutTypes'

function fmtDur(min: number | null): string {
  if (min === null) return '—'
  const h = Math.floor(min / 60)
  const m = Math.round(min % 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

function fmtDist(m: number | null): string {
  if (m === null) return '—'
  return `${(m / 1000).toFixed(2)} km`
}

function fmtVal(v: number | null | undefined, digits = 1, suffix = ''): string {
  return v !== null && v !== undefined ? `${v.toFixed(digits)}${suffix}` : '—'
}

/** Colored strain value — brighter at higher intensity */
function StrainValue({ strain }: { strain: number | null }) {
  if (strain === null) return <span style={{ color: 'var(--text-tertiary)' }}>—</span>
  const color = strain >= 15
    ? 'var(--status-alert)'
    : strain >= 10
    ? 'var(--status-caution)'
    : 'var(--text-secondary)'
  return (
    <span
      style={{
        color,
        fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
        fontVariantNumeric: 'tabular-nums',
        fontSize:           12,
        fontWeight:         600,
      }}
    >
      {strain.toFixed(1)}
    </span>
  )
}

/** Inline detail cell in expanded sections */
function DetailCell({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        background:   'var(--bg-card-elevated)',
        borderRadius: 8,
        padding:      '8px 10px',
      }}
    >
      <p
        style={{
          fontSize:      10,
          fontWeight:    500,
          letterSpacing: '0.07em',
          textTransform: 'uppercase',
          color:         'var(--text-secondary)',
          marginBottom:  2,
        }}
      >
        {label}
      </p>
      <p
        style={{
          fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
          fontVariantNumeric: 'tabular-nums',
          fontSize:           13,
          color:              'var(--text-primary)',
        }}
      >
        {value}
      </p>
    </div>
  )
}

// ── HR Zone bar ────────────────────────────────────────────────────────────

function HRZoneBar({ zones }: { zones: EnrichedWorkout['hr_zone_minutes'] }) {
  // Blue → Teal → Green → Amber → Coral
  const ZONE_COLORS = ['#3b82f6', 'var(--status-excellent)', '#22c55e', 'var(--status-caution)', 'var(--status-alert)']
  const ZONE_LABELS = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']

  const values = [
    zones.zone1 ?? 0,
    zones.zone2 ?? 0,
    zones.zone3 ?? 0,
    zones.zone4 ?? 0,
    zones.zone5 ?? 0,
  ]
  const total = values.reduce((a, b) => a + b, 0)
  if (total === 0) {
    return <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>No HR zone data</p>
  }

  return (
    <div className="space-y-1.5">
      <div
        className="flex w-full overflow-hidden rounded-full"
        style={{ height: 8, gap: 1 }}
      >
        {values.map((v, i) =>
          v > 0 ? (
            <div
              key={i}
              title={`${ZONE_LABELS[i]}: ${v.toFixed(0)}m`}
              style={{
                width:           `${(v / total) * 100}%`,
                backgroundColor: ZONE_COLORS[i],
                flexShrink:      0,
              }}
            />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        {values.map((v, i) =>
          v > 0 ? (
            <span key={i} style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
              <span style={{ color: ZONE_COLORS[i] }}>●</span> {ZONE_LABELS[i]} {v.toFixed(0)}m
            </span>
          ) : null,
        )}
      </div>
    </div>
  )
}

// ── Exercise Sets ──────────────────────────────────────────────────────────

function ExerciseSets({ workoutId }: { workoutId: string }) {
  const setsQ = useExerciseSets(workoutId, true)

  if (setsQ.isLoading) {
    return <div className="skeleton h-16 rounded-lg" />
  }
  if (!setsQ.data?.length) {
    return (
      <p style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
        No exercise set data — run a sync to fetch strength set details.
      </p>
    )
  }

  // Group by exercise name
  const grouped: Record<string, typeof setsQ.data> = {}
  for (const s of setsQ.data) {
    const key = (s.exercise_name || s.exercise_category || 'Unknown')
      .replace(/_/g, ' ')
      .split(' ')
      .map(w => w[0].toUpperCase() + w.slice(1).toLowerCase())
      .join(' ')
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(s)
  }

  return (
    <div className="space-y-3">
      {Object.entries(grouped).map(([exName, sets]) => {
        const totalVolumeLb = sets.reduce((sum, s) => {
          return sum + (s.repetition_count ?? 0) * (s.weight_kg ?? 0) * KG_TO_LB
        }, 0)
        return (
          <div key={exName}>
            <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 4 }}>
              {exName}
              {totalVolumeLb > 0 && (
                <span style={{ marginLeft: 8, fontWeight: 400, color: 'var(--text-tertiary)' }}>
                  · {totalVolumeLb.toFixed(0)} lb total
                </span>
              )}
            </p>
            <table className="w-full" style={{ fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '0.5px solid var(--border-subtle)' }}>
                  {['Set', 'Reps', 'Weight (lb)', 'Volume (lb)'].map(h => (
                    <th
                      key={h}
                      className="pb-1 pr-4 text-left last:hidden sm:last:table-cell"
                      style={{ fontWeight: 500, color: 'var(--text-tertiary)' }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sets.map((s, i) => {
                  const lb  = s.weight_kg !== null ? s.weight_kg * KG_TO_LB : null
                  const vol = s.repetition_count !== null && lb !== null
                    ? s.repetition_count * lb : null
                  return (
                    <tr
                      key={i}
                      style={{ borderBottom: i < sets.length - 1 ? '0.5px solid var(--border-subtle)' : 'none' }}
                    >
                      <td className="py-1.5 pr-4" style={{ fontFamily: "'IBM Plex Mono'", color: 'var(--text-tertiary)' }}>{i + 1}</td>
                      <td className="py-1.5 pr-4" style={{ fontFamily: "'IBM Plex Mono'", color: 'var(--text-primary)' }}>{s.repetition_count ?? '—'}</td>
                      <td className="py-1.5 pr-4" style={{ fontFamily: "'IBM Plex Mono'", color: 'var(--text-primary)' }}>{lb !== null ? lb.toFixed(1) : 'BW'}</td>
                      <td className="py-1.5 hidden sm:table-cell" style={{ fontFamily: "'IBM Plex Mono'", color: 'var(--text-primary)' }}>{vol !== null ? vol.toFixed(0) : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      })}
    </div>
  )
}

// ── WorkoutRow ─────────────────────────────────────────────────────────────

interface WorkoutRowProps {
  workout: EnrichedWorkout
}

export const WorkoutRow = memo(function WorkoutRow({ workout: w }: WorkoutRowProps) {
  const [expanded, setExpanded] = useState(false)

  const source = w.matched ? 'both' : w.primary_source as 'whoop' | 'garmin' | 'both'
  const label = activityLabel(w.activity_type ?? 'Unknown')
  const isRun      = (w.activity_type ?? '').toLowerCase().includes('run')
  const isStrength = STRENGTH_TYPES.has((w.activity_type ?? '').toLowerCase())

  return (
    <div
      style={{
        background:   'var(--bg-card)',
        border:       `0.5px solid ${expanded ? 'var(--border-hover)' : 'var(--border-subtle)'}`,
        borderRadius: 12,
        overflow:     'hidden',
        transition:   'border-color 150ms ease',
      }}
    >
      {/* Collapsed row */}
      <button
        className="flex w-full items-center gap-3 text-left"
        style={{ padding: '12px 16px' }}
        onClick={() => setExpanded(e => !e)}
      >
        {/* Date */}
        <span
          style={{
            fontFamily:         "'IBM Plex Mono', ui-monospace, monospace",
            fontSize:           11,
            color:              'var(--text-tertiary)',
            width:              52,
            flexShrink:         0,
          }}
        >
          {new Date(w.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </span>

        {/* Activity type */}
        <span
          className="flex-1 truncate"
          style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}
        >
          {label}
        </span>

        {/* Duration */}
        <span
          style={{ fontSize: 12, color: 'var(--text-secondary)', width: 52, textAlign: 'right', flexShrink: 0 }}
        >
          {fmtDur(w.duration_minutes)}
        </span>

        {/* Strain */}
        <span style={{ width: 36, textAlign: 'right', flexShrink: 0 }}>
          <StrainValue strain={w.strain} />
        </span>

        <DataSourceBadge source={source} />

        {/* Chevron */}
        <svg
          className={`flex-shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
          style={{ width: 16, height: 16, color: 'var(--text-tertiary)' }}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div
          className="animate-fade-in"
          style={{
            borderTop: '0.5px solid var(--border-subtle)',
            padding:   '16px',
            display:   'flex',
            flexDirection: 'column',
            gap: 16,
          }}
        >
          {/* Physiological Load */}
          <div>
            <p
              style={{
                fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                textTransform: 'uppercase', color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              Physiological Load
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                ['Strain',   fmtVal(w.strain)],
                ['Avg HR',   w.avg_hr  ? `${w.avg_hr} bpm`  : '—'],
                ['Max HR',   w.max_hr  ? `${w.max_hr} bpm`  : '—'],
                ['Calories', fmtVal(w.calories_kj, 0, ' kJ')],
              ].map(([label, val]) => (
                <DetailCell key={label} label={label} value={val} />
              ))}
            </div>
          </div>

          {/* Performance */}
          <div>
            <p
              style={{
                fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                textTransform: 'uppercase', color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              Performance
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                ['Distance',       fmtDist(w.distance_m)],
                ['Pace',           fmtVal(w.avg_pace_min_per_km, 2, ' /km')],
                ['Elevation',      fmtVal(w.elevation_gain_m, 0, ' m')],
                ['Cadence',        fmtVal(w.avg_cadence, 0, ' spm')],
                ['Training Load',  fmtVal(w.training_load)],
                ['Aerobic Effect', fmtVal(w.training_effect_aerobic)],
                ['VO2 Max',        fmtVal(w.vo2_max)],
                ['Intensity',      w.strain_per_minute ? `${w.strain_per_minute.toFixed(3)}/min` : '—'],
              ].map(([label, val]) => (
                <DetailCell key={label} label={label} value={val} />
              ))}
            </div>
          </div>

          {/* Running Dynamics */}
          {isRun && (
            <div>
              <p
                style={{
                  fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                  textTransform: 'uppercase', color: 'var(--text-secondary)',
                  marginBottom: 8,
                }}
              >
                Running Dynamics
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  ['Ground Contact',    fmtVal(w.avg_ground_contact_time_ms, 0, ' ms')],
                  ['Vert Oscillation',  fmtVal(w.avg_vertical_oscillation_cm, 1, ' cm')],
                  ['Vert Ratio',        fmtVal(w.avg_vertical_ratio_pct, 1, '%')],
                  ['Stride Length',     fmtVal(w.avg_stride_length !== null ? w.avg_stride_length / 100 : null, 2, ' m')],
                ].map(([label, val]) => (
                  <DetailCell key={label} label={label} value={val} />
                ))}
              </div>
            </div>
          )}

          {/* Exercise Sets */}
          {isStrength && (
            <div>
              <p
                style={{
                  fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                  textTransform: 'uppercase', color: 'var(--text-secondary)',
                  marginBottom: 8,
                }}
              >
                Exercise Sets
              </p>
              <ExerciseSets workoutId={w.id} />
            </div>
          )}

          {/* HR Zones */}
          <div>
            <p
              style={{
                fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                textTransform: 'uppercase', color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              HR Zones
            </p>
            <HRZoneBar zones={w.hr_zone_minutes} />
          </div>

          {/* Recovery Impact */}
          {w.next_day_recovery !== null && (
            <div
              style={{
                background:   'var(--bg-card-elevated)',
                borderRadius: 8,
                padding:      '12px',
              }}
            >
              <p
                style={{
                  fontSize: 10, fontWeight: 500, letterSpacing: '0.07em',
                  textTransform: 'uppercase', color: 'var(--text-secondary)',
                  marginBottom: 4,
                }}
              >
                Recovery Impact
              </p>
              <p style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                Next-day recovery:{' '}
                <span
                  style={{
                    fontFamily:         "'IBM Plex Mono'",
                    fontVariantNumeric: 'tabular-nums',
                    fontWeight:         600,
                    color:              'var(--text-primary)',
                  }}
                >
                  {w.next_day_recovery.toFixed(0)}%
                </span>
                {w.recovery_impact !== null && (
                  <span
                    style={{
                      marginLeft: 8,
                      fontFamily: "'IBM Plex Mono'",
                      fontSize:   12,
                      color:      w.recovery_impact >= 0
                        ? 'var(--status-excellent)'
                        : 'var(--status-alert)',
                    }}
                  >
                    ({w.recovery_impact >= 0 ? '+' : ''}{w.recovery_impact.toFixed(1)} vs 7d avg)
                  </span>
                )}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
})
