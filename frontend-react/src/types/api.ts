// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------

export interface DateRange {
  start: string // ISO date string YYYY-MM-DD
  end: string
}

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export interface ContributingFactor {
  name: string
  raw_value: number | null
  normalized_value: number | null
  weight: number
  effective_weight: number
}

export interface ReadinessResult {
  date: string
  score: number
  recommendation: string
  contributing_factors: Record<string, ContributingFactor>
  confidence: number
}

export interface ReadinessHistoryPoint {
  date: string
  score: number
  recommendation: string
  confidence: number
}

// ---------------------------------------------------------------------------
// Workouts
// ---------------------------------------------------------------------------

export interface HRZoneMinutes {
  zone1?: number | null
  zone2?: number | null
  zone3?: number | null
  zone4?: number | null
  zone5?: number | null
}

export interface EnrichedWorkout {
  id: string
  date: string
  start_time: string | null
  activity_type: string | null
  duration_minutes: number | null
  primary_source: string
  matched: boolean
  // Physiological load
  strain: number | null
  avg_hr: number | null
  max_hr: number | null
  calories_kj: number | null
  hr_zone_minutes: HRZoneMinutes
  // Performance
  distance_m: number | null
  avg_pace_min_per_km: number | null
  elevation_gain_m: number | null
  avg_cadence: number | null
  avg_stride_length: number | null
  training_effect_aerobic: number | null
  training_effect_anaerobic: number | null
  training_load: number | null
  vo2_max: number | null
  // Running dynamics
  avg_ground_contact_time_ms: number | null
  avg_vertical_oscillation_cm: number | null
  avg_vertical_ratio_pct: number | null
  // Computed insights
  strain_per_minute: number | null
  efficiency_score: number | null
  next_day_recovery: number | null
  recovery_impact: number | null
}

// Backend returns list[WorkoutTypeSummaryItem] (an array, not a record)
export interface WorkoutTypeSummary {
  activity_type: string
  count: number
  avg_duration_minutes: number | null
  avg_strain: number | null
  avg_distance_m: number | null
  avg_pace_min_per_km: number | null
  avg_training_load: number | null
  avg_training_effect_aerobic: number | null
  avg_next_day_recovery: number | null
  avg_recovery_impact: number | null
  avg_strain_per_minute: number | null
  avg_efficiency_score: number | null
}

// ---------------------------------------------------------------------------
// Sleep
// ---------------------------------------------------------------------------

export interface SleepInsight {
  date: string
  total_sleep_minutes: number | null
  deep_minutes: number | null        // was deep_sleep_minutes
  light_minutes: number | null       // was light_sleep_minutes
  rem_minutes: number | null         // was rem_sleep_minutes
  awake_minutes: number | null
  sleep_performance: number | null
  sleep_efficiency: number | null
  previous_day_strain: number | null
  previous_day_training_load: number | null
  next_day_recovery_score: number | null   // was next_day_recovery
  next_day_body_battery: number | null
  sleep_debt_estimate: number | null       // was sleep_debt_minutes
}

export interface CorrelationResult {
  r: number | null
  n: number
  sufficient_data: boolean
  message: string | null
}

// Backend: SleepCorrelationResponse — correlation fields are CorrelationResult objects
export interface SleepCorrelations {
  strain_vs_total_sleep: CorrelationResult
  strain_vs_deep_sleep: CorrelationResult
  strain_vs_next_day_recovery: CorrelationResult
  days_analyzed: number
}

// Backend: SleepConsistencyResponse
export interface SleepConsistency {
  insufficient_data: boolean
  message: string | null
  sample_size: number | null
  avg_bedtime_hour: number | null
  bedtime_std_hours: number | null      // hours, not minutes
  avg_wake_hour: number | null
  wake_time_std_hours: number | null    // hours, not minutes
  avg_total_sleep_minutes: number | null
  sleep_debt_trend: string | null       // was trend_direction
  sleep_debt_trend_slope_min_per_day: number | null
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export interface AnomalyPoint {
  date: string
  value: number
  direction: string
  severity: number
}

export interface MetricTrend {
  metric_name: string
  dates: string[]
  values: (number | null)[]
  rolling_avg_7d: (number | null)[]
  rolling_avg_30d: (number | null)[]
  rolling_std_7d: (number | null)[]    // newly added
  anomalies: AnomalyPoint[]
  trend_direction: string
}

// Backend: WeeklySummaryResponse
export interface WeeklySummary {
  period_start: string
  period_end: string
  avg_readiness: number | null
  avg_recovery: number | null
  avg_hrv: number | null
  avg_rhr: number | null
  total_strain: number | null
  workout_count: number
  total_training_minutes: number | null
  avg_sleep_duration: number | null
  avg_deep_sleep: number | null
  notable_anomalies: Array<Record<string, unknown>>
  // comparison is a flat dict of metric -> value (week-over-week % changes)
  comparison: Record<string, number | null>
}

// ---------------------------------------------------------------------------
// Sync / Settings
// ---------------------------------------------------------------------------

// Backend: SyncStatusItem — one per source (whoop/garmin)
export interface SyncStatusItem {
  source: string
  last_sync_at: string | null
  status: string | null
  records_stored: number | null
  error_message: string | null
}

// GET /api/sync/status returns list[SyncStatusItem]
export type SyncStatus = SyncStatusItem[]

export interface DataStats {
  total_days: number
  total_workouts: number
  matched_workouts: number
  date_start: string | null
  date_end: string | null
}

export interface SyncTriggerResponse {
  source: string
  status: string
  records_fetched: number
  records_stored: number
  started_at: string
  completed_at: string | null
  error_message: string | null
}

// ---------------------------------------------------------------------------
// Exercise Sets / Strength
// ---------------------------------------------------------------------------

export interface ExerciseSet {
  set_order: number | null
  exercise_category: string | null
  exercise_name: string | null
  repetition_count: number | null
  weight_kg: number | null
  duration_seconds: number | null
}

export interface StrengthVolume {
  date: string
  total_volume_kg: number
}

export interface StrengthMaxWeight {
  date: string
  exercise_name: string
  max_weight_kg: number
}

// ---------------------------------------------------------------------------
// Recovery Activities
// ---------------------------------------------------------------------------

export interface RecoveryActivity {
  date: string
  activity: string
  dur_min: number | null
  same_day_recovery: number | null
  next_day_recovery: number | null
  next_day_hrv: number | null
  next_day_sleep_perf: number | null
  next_day_sleep_min: number | null
}

export interface WithWithoutResponse {
  with_avg: number | null
  without_avg: number | null
  with_count: number
  without_count: number
}
