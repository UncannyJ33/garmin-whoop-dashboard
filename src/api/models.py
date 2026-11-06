"""Pydantic response models for all API endpoints."""

from typing import Any, Literal

from pydantic import BaseModel

from src.analytics.limiting_factors import Severity
from src.analytics.readiness_score import Recommendation
from src.analytics.sleep_analysis import SleepDebtTrend
from src.analytics.training_load import AcwrTrend, Zone
from src.analytics.trends import AnomalyDirection, TrendDirection
from src.analytics.workout_analysis import PrimarySource

# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


class ContributingFactor(BaseModel):
    name: str
    raw_value: float | None = None
    normalized_value: float | None = None
    weight: float
    effective_weight: float


class ReadinessResponse(BaseModel):
    date: str
    score: float | None = None
    recommendation: Recommendation
    contributing_factors: dict[str, ContributingFactor]
    confidence: float


class ReadinessHistoryItem(BaseModel):
    date: str
    score: float | None = None
    recommendation: Recommendation
    confidence: float


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------


class HRZoneMinutes(BaseModel):
    zone1: float | None = None
    zone2: float | None = None
    zone3: float | None = None
    zone4: float | None = None
    zone5: float | None = None


class EnrichedWorkoutResponse(BaseModel):
    id: str
    date: str
    start_time: str | None = None
    activity_type: str | None = None
    duration_minutes: float | None = None
    primary_source: PrimarySource
    matched: bool
    # Physiological load
    strain: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories_kj: float | None = None
    hr_zone_minutes: HRZoneMinutes
    # Performance metrics
    distance_m: float | None = None
    avg_pace_min_per_km: float | None = None
    elevation_gain_m: float | None = None
    avg_cadence: float | None = None
    avg_stride_length: float | None = None
    training_effect_aerobic: float | None = None
    training_effect_anaerobic: float | None = None
    training_load: float | None = None
    vo2_max: float | None = None
    # Running dynamics
    avg_ground_contact_time_ms: float | None = None
    avg_vertical_oscillation_cm: float | None = None
    avg_vertical_ratio_pct: float | None = None
    # Computed insights
    strain_per_minute: float | None = None
    efficiency_score: float | None = None
    next_day_recovery: float | None = None
    recovery_impact: float | None = None


class WorkoutTypeSummaryItem(BaseModel):
    activity_type: str
    count: int
    avg_duration_minutes: float | None = None
    avg_strain: float | None = None
    avg_distance_m: float | None = None
    avg_pace_min_per_km: float | None = None
    avg_training_load: float | None = None
    avg_training_effect_aerobic: float | None = None
    avg_next_day_recovery: float | None = None
    avg_recovery_impact: float | None = None
    avg_strain_per_minute: float | None = None
    avg_efficiency_score: float | None = None


# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------


class SleepInsightResponse(BaseModel):
    date: str
    total_sleep_minutes: float | None = None
    deep_minutes: float | None = None
    light_minutes: float | None = None
    rem_minutes: float | None = None
    awake_minutes: float | None = None
    sleep_performance: float | None = None
    sleep_efficiency: float | None = None
    previous_day_strain: float | None = None
    previous_day_training_load: float | None = None
    next_day_recovery_score: float | None = None
    next_day_body_battery: int | None = None
    sleep_debt_estimate: float | None = None


class CorrelationResult(BaseModel):
    r: float | None = None
    n: int
    sufficient_data: bool
    message: str | None = None


class SleepCorrelationResponse(BaseModel):
    strain_vs_total_sleep: CorrelationResult
    strain_vs_deep_sleep: CorrelationResult
    strain_vs_next_day_recovery: CorrelationResult
    days_analyzed: int


class SleepConsistencyResponse(BaseModel):
    insufficient_data: bool
    message: str | None = None
    sample_size: int | None = None
    avg_bedtime_hour: float | None = None
    bedtime_std_hours: float | None = None
    avg_wake_hour: float | None = None
    wake_time_std_hours: float | None = None
    avg_total_sleep_minutes: float | None = None
    sleep_debt_trend: SleepDebtTrend | None = None
    sleep_debt_trend_slope_min_per_day: float | None = None


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


class AnomalyPoint(BaseModel):
    date: str
    value: float
    direction: AnomalyDirection
    severity: float


class MetricTrendResponse(BaseModel):
    metric_name: str
    dates: list[str]
    values: list[float | None]
    rolling_avg_7d: list[float | None]
    rolling_avg_30d: list[float | None]
    rolling_std_7d: list[float | None]
    anomalies: list[AnomalyPoint]
    trend_direction: TrendDirection


class WeeklySummaryResponse(BaseModel):
    period_start: str
    period_end: str
    avg_readiness: float | None = None
    avg_recovery: float | None = None
    avg_hrv: float | None = None
    avg_rhr: float | None = None
    total_strain: float | None = None
    workout_count: int = 0
    total_training_minutes: float | None = None
    avg_sleep_duration: float | None = None
    avg_deep_sleep: float | None = None
    notable_anomalies: list[dict[str, Any]] = []
    comparison: dict[str, float | None] = {}


class AnomalyItem(BaseModel):
    date: str
    metric: str
    value: float
    direction: AnomalyDirection
    severity: float


class EnrichedAnomalyResponse(BaseModel):
    date: str
    metric: str
    metric_label: str
    value: float
    direction: AnomalyDirection
    severity: float
    context: dict[str, Any]
    explanation: str


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


# Values written to SyncLog.status; "never_synced" is API-only (no row yet).
SyncState = Literal["running", "success", "error"]


class SyncStatusItem(BaseModel):
    source: str
    last_sync_at: str | None = None
    status: SyncState | Literal["never_synced"] | None = None
    records_stored: int | None = None
    error_message: str | None = None
    next_sync_at: str | None = None
    scheduler_running: bool | None = None
    is_running: bool = False


class SyncTriggerResponse(BaseModel):
    source: str
    status: SyncState
    records_fetched: int
    records_stored: int
    started_at: str
    completed_at: str | None = None
    error_message: str | None = None


class DataStatsResponse(BaseModel):
    total_days: int
    total_workouts: int
    matched_workouts: int
    date_start: str | None = None
    date_end: str | None = None


# ---------------------------------------------------------------------------
# Exercise Sets / Strength
# ---------------------------------------------------------------------------


class ExerciseSetItem(BaseModel):
    set_order: int | None = None
    exercise_category: str | None = None
    exercise_name: str | None = None
    repetition_count: int | None = None
    weight_kg: float | None = None
    duration_seconds: float | None = None


class ExerciseSummaryItem(BaseModel):
    exercise_category: str | None = None
    exercise_name: str | None = None
    set_count: int | None = None
    repetition_count: int | None = None
    volume_kg: float | None = None
    max_weight_kg: float | None = None
    duration_seconds: float | None = None


class StrengthVolumeItem(BaseModel):
    date: str
    total_volume_kg: float


class StrengthMaxWeightItem(BaseModel):
    date: str
    exercise_name: str
    max_weight_kg: float


# ---------------------------------------------------------------------------
# Limiting Factors
# ---------------------------------------------------------------------------


class LimitingFactorResponse(BaseModel):
    factor_name: str
    current_value: float
    current_value_display: str
    normalized_score: float
    seven_day_avg: float
    seven_day_avg_display: str
    deviation_pct: float
    explanation: str
    severity: Severity


# ---------------------------------------------------------------------------
# Training Load (ACWR)
# ---------------------------------------------------------------------------


class WeeklyLoadItem(BaseModel):
    week_start_date: str
    total_strain: float
    workout_count: int


class TrainingLoadResponse(BaseModel):
    acwr: float | None = None
    acute_load: float
    chronic_load: float
    zone: Zone | None = None
    zone_description: str | None = None
    trend: AcwrTrend
    weekly_loads: list[WeeklyLoadItem]
    confidence_note: str | None = None


class TrainingLoadHistoryItem(BaseModel):
    date: str
    acwr: float | None = None
    acute_load: float
    chronic_load: float
    zone: Zone | None = None


# ---------------------------------------------------------------------------
# Recovery Activities
# ---------------------------------------------------------------------------


class RecoveryActivityItem(BaseModel):
    date: str
    activity: str
    dur_min: float | None = None
    same_day_recovery: float | None = None
    next_day_recovery: float | None = None
    next_day_hrv: float | None = None
    next_day_sleep_perf: float | None = None
    next_day_sleep_min: float | None = None


class WithWithoutResponse(BaseModel):
    with_avg: float | None = None
    without_avg: float | None = None
    with_count: int
    without_count: int


# ---------------------------------------------------------------------------
# Insights / Weekly Digest
# ---------------------------------------------------------------------------


class WeeklyDigestMetricsResponse(BaseModel):
    avg_readiness: float | None = None
    avg_recovery: float | None = None
    avg_hrv: float | None = None
    total_strain: float | None = None
    workout_count: int
    total_training_hours: float | None = None
    avg_sleep_hours: float | None = None
    avg_deep_sleep_minutes: float | None = None
    acwr: float | None = None
    acwr_zone: Zone | None = None


class WeeklyDigestResponse(BaseModel):
    week_start: str
    week_end: str
    takeaways: list[str]
    metrics_snapshot: WeeklyDigestMetricsResponse
