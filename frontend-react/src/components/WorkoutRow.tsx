import { useState } from 'react'
import type { EnrichedWorkout } from '../types/api'
import { DataSourceBadge } from './DataSourceBadge'

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

// HR Zone bar
function HRZoneBar({ zones }: { zones: EnrichedWorkout['hr_zone_minutes'] }) {
  const ZONE_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#f97316', '#ef4444']
  const ZONE_LABELS = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']

  const values = [
    zones.zone1 ?? 0,
    zones.zone2 ?? 0,
    zones.zone3 ?? 0,
    zones.zone4 ?? 0,
    zones.zone5 ?? 0,
  ]
  const total = values.reduce((a, b) => a + b, 0)
  if (total === 0) return <p className="text-xs text-slate-500">No HR zone data</p>

  return (
    <div className="space-y-1.5">
      <div className="flex h-4 w-full overflow-hidden rounded gap-px">
        {values.map((v, i) =>
          v > 0 ? (
            <div
              key={i}
              title={`${ZONE_LABELS[i]}: ${v.toFixed(0)}m`}
              style={{ width: `${(v / total) * 100}%`, backgroundColor: ZONE_COLORS[i] }}
            />
          ) : null,
        )}
      </div>
      <div className="flex gap-3">
        {values.map((v, i) =>
          v > 0 ? (
            <span key={i} className="text-2xs text-slate-500">
              <span style={{ color: ZONE_COLORS[i] }}>●</span> {ZONE_LABELS[i]} {v.toFixed(0)}m
            </span>
          ) : null,
        )}
      </div>
    </div>
  )
}

interface WorkoutRowProps {
  workout: EnrichedWorkout
}

export function WorkoutRow({ workout: w }: WorkoutRowProps) {
  const [expanded, setExpanded] = useState(false)

  const source = w.matched ? 'both' : w.primary_source as 'whoop' | 'garmin' | 'both'
  const activityLabel = (w.activity_type ?? 'Unknown')
    .split('_').map(s => s[0].toUpperCase() + s.slice(1)).join(' ')
  const isRun = (w.activity_type ?? '').toLowerCase().includes('run')

  return (
    <div className="card-sm border border-surface-border overflow-hidden">
      {/* Collapsed row — always visible */}
      <button
        className="flex w-full items-center gap-3 text-left"
        onClick={() => setExpanded(e => !e)}
      >
        {/* Date */}
        <span className="font-mono text-xs text-slate-400 w-16 flex-shrink-0">
          {new Date(w.date + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </span>

        {/* Activity type */}
        <span className="flex-1 text-sm font-medium text-slate-700 dark:text-slate-200 truncate">{activityLabel}</span>

        {/* Duration */}
        <span className="text-xs text-slate-400 w-14 text-right flex-shrink-0">
          {fmtDur(w.duration_minutes)}
        </span>

        {/* Strain */}
        <span className="font-mono text-xs font-semibold text-chart-orange w-10 text-right flex-shrink-0">
          {w.strain !== null ? w.strain.toFixed(1) : '—'}
        </span>

        <DataSourceBadge source={source} />

        {/* Chevron */}
        <svg
          className={`h-4 w-4 text-slate-500 flex-shrink-0 transition-transform ${expanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="mt-3 pt-3 border-t border-surface-border space-y-4 animate-fade-in">
          {/* Physiological */}
          <div>
            <p className="metric-label mb-2">Physiological Load</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                ['Strain', fmtVal(w.strain)],
                ['Avg HR', w.avg_hr ? `${w.avg_hr} bpm` : '—'],
                ['Max HR', w.max_hr ? `${w.max_hr} bpm` : '—'],
                ['Calories', fmtVal(w.calories_kj, 0, ' kJ')],
              ].map(([label, val]) => (
                <div key={label} className="bg-surface-overlay rounded-lg p-2">
                  <p className="metric-label">{label}</p>
                  <p className="font-mono text-sm text-slate-800 dark:text-slate-200 mt-0.5">{val}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Performance */}
          <div>
            <p className="metric-label mb-2">Performance</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[
                ['Distance', fmtDist(w.distance_m)],
                ['Pace', fmtVal(w.avg_pace_min_per_km, 2, ' /km')],
                ['Elevation', fmtVal(w.elevation_gain_m, 0, ' m')],
                ['Cadence', fmtVal(w.avg_cadence, 0, ' spm')],
                ['Training Load', fmtVal(w.training_load)],
                ['Aerobic Effect', fmtVal(w.training_effect_aerobic)],
                ['VO2 Max', fmtVal(w.vo2_max)],
                ['Intensity', w.strain_per_minute ? `${w.strain_per_minute.toFixed(3)}/min` : '—'],
              ].map(([label, val]) => (
                <div key={label} className="bg-surface-overlay rounded-lg p-2">
                  <p className="metric-label">{label}</p>
                  <p className="font-mono text-sm text-slate-800 dark:text-slate-200 mt-0.5">{val}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Running dynamics — only for runs */}
          {isRun && (
            <div>
              <p className="metric-label mb-2">Running Dynamics</p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {[
                  ['Ground Contact', fmtVal(w.avg_ground_contact_time_ms, 0, ' ms')],
                  ['Vert Oscillation', fmtVal(w.avg_vertical_oscillation_cm, 1, ' cm')],
                  ['Vert Ratio', fmtVal(w.avg_vertical_ratio_pct, 1, '%')],
                  ['Stride Length', fmtVal(w.avg_stride_length, 2, ' m')],
                ].map(([label, val]) => (
                  <div key={label} className="bg-surface-overlay rounded-lg p-2">
                    <p className="metric-label">{label}</p>
                    <p className="font-mono text-sm text-slate-800 dark:text-slate-200 mt-0.5">{val}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* HR Zones */}
          <div>
            <p className="metric-label mb-2">HR Zones</p>
            <HRZoneBar zones={w.hr_zone_minutes} />
          </div>

          {/* Recovery impact */}
          {w.next_day_recovery !== null && (
            <div className="rounded-lg bg-surface-overlay p-3">
              <p className="metric-label mb-1">Recovery Impact</p>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                Next-day recovery:{' '}
                <span className="font-mono font-semibold text-slate-800 dark:text-slate-100">
                  {w.next_day_recovery.toFixed(0)}
                </span>
                {w.recovery_impact !== null && (
                  <span className={`ml-2 font-mono text-xs ${w.recovery_impact >= 0 ? 'text-good' : 'text-poor'}`}>
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
}
