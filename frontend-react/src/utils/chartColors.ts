/**
 * Activity type color palette — mapped to the PulseEngine design system.
 *
 * Primary activities use solid design-system hues.
 * Secondary/less-common activities use muted variants of the same palette.
 * Recharts can't consume CSS variables directly, so these are resolved hex/rgba values.
 *
 * Design system reference:
 *   --data-primary:   #5dcaa5  (teal)
 *   --data-secondary: #ef9f27  (amber)
 *   --data-anomaly:   #e8775a  (coral)
 *   --brand:          #2563ff  (blue)
 *   --status-good:    #1d9e75  (dark teal)
 */
export const TYPE_COLORS: Record<string, string> = {
  running:           '#5dcaa5',               // data-primary (teal)
  strength_training: '#ef9f27',               // data-secondary (amber)
  cycling:           '#2563ff',               // brand (blue)
  walking:           '#1d9e75',               // status-good (dark teal)
  swimming:          '#e8775a',               // data-anomaly (coral)
  yoga:              'rgba(239,159,39,0.55)', // muted amber — restorative
  hiit:              'rgba(232,119,90,0.90)', // near-coral — high intensity
  pilates:           'rgba(93,202,165,0.55)', // muted teal — controlled movement
  indoor_cardio:     'rgba(37,99,255,0.65)',  // muted blue — cardio machine
}

export const FALLBACK_COLORS: string[] = [
  'rgba(93,202,165,0.70)',  // teal
  'rgba(239,159,39,0.70)',  // amber
  'rgba(232,119,90,0.70)',  // coral
  'rgba(37,99,255,0.70)',   // blue
  'rgba(29,158,117,0.70)',  // dark teal
]

/** Return a design-system color for an activity type. Falls back to the FALLBACK_COLORS cycle. */
export function colorForType(type: string, allTypes: string[]): string {
  if (TYPE_COLORS[type]) return TYPE_COLORS[type]
  const idx = allTypes.filter(t => !TYPE_COLORS[t]).indexOf(type)
  return FALLBACK_COLORS[idx % FALLBACK_COLORS.length]
}
