from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class WhoopCycle(Base):
    """Daily physiological cycle from the Whoop API (/v2/cycle)."""

    __tablename__ = "whoop_cycles"

    id = Column(String, primary_key=True)  # Whoop cycle UUID
    user_id = Column(Integer, nullable=False)
    start_time = Column(String, nullable=False)  # ISO 8601
    end_time = Column(String)
    timezone_offset = Column(String)
    score_state = Column(String)  # SCORED, PENDING, etc.
    strain = Column(Float)
    kilojoules = Column(Float)
    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    recovery = relationship("WhoopRecovery", back_populates="cycle", uselist=False)
    sleep = relationship("WhoopSleep", back_populates="cycle")
    workouts = relationship("WhoopWorkout", back_populates="cycle")


class WhoopRecovery(Base):
    """Recovery data from the Whoop API (/v2/recovery)."""

    __tablename__ = "whoop_recovery"

    id = Column(String, primary_key=True)
    cycle_id = Column(String, ForeignKey("whoop_cycles.id"))
    sleep_id = Column(String)
    score_state = Column(String)
    recovery_score = Column(Float)  # 0–100%
    resting_heart_rate = Column(Float)  # bpm
    hrv_rmssd = Column(Float)  # ms
    spo2_pct = Column(Float)
    skin_temp_celsius = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="recovery")


class WhoopSleep(Base):
    """Sleep event from the Whoop API (/v2/activity/sleep)."""

    __tablename__ = "whoop_sleep"

    id = Column(String, primary_key=True)  # Whoop sleep UUID
    cycle_id = Column(String, ForeignKey("whoop_cycles.id"))
    start_time = Column(String, nullable=False)
    end_time = Column(String)
    timezone_offset = Column(String)
    nap = Column(Integer)  # boolean: 0 or 1
    score_state = Column(String)
    total_in_bed_ms = Column(Integer)
    total_awake_ms = Column(Integer)
    total_light_ms = Column(Integer)
    total_sws_ms = Column(Integer)  # slow wave / deep sleep
    total_rem_ms = Column(Integer)
    total_no_data_ms = Column(Integer)
    sleep_performance = Column(Float)  # percentage
    sleep_consistency = Column(Float)
    sleep_efficiency = Column(Float)
    respiratory_rate = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="sleep")


class WhoopWorkout(Base):
    """Workout event from the Whoop API (/v2/activity/workout)."""

    __tablename__ = "whoop_workouts"

    id = Column(String, primary_key=True)  # Whoop workout UUID
    cycle_id = Column(String, ForeignKey("whoop_cycles.id"))
    start_time = Column(String, nullable=False)
    end_time = Column(String)
    timezone_offset = Column(String)
    sport_id = Column(Integer)
    sport_name = Column(String)
    score_state = Column(String)
    strain = Column(Float)
    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    kilojoules = Column(Float)
    distance_meter = Column(Float)
    altitude_gain_meter = Column(Float)
    altitude_change_meter = Column(Float)
    zone_durations_json = Column(Text)  # HR zone times as JSON array
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="workouts")


class GarminActivity(Base):
    """Activity record from the Garmin Connect API."""

    __tablename__ = "garmin_activities"

    activity_id = Column(String, primary_key=True)  # Garmin activity ID (large int as str)
    activity_type = Column(String)
    activity_name = Column(String)
    start_time = Column(String)  # ISO 8601 local time
    start_time_gmt = Column(String)  # ISO 8601 UTC
    duration_seconds = Column(Float)
    elapsed_seconds = Column(Float)
    distance_meters = Column(Float)
    avg_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    avg_running_cadence = Column(Float)
    max_running_cadence = Column(Float)
    calories = Column(Float)
    avg_speed = Column(Float)
    max_speed = Column(Float)
    elevation_gain = Column(Float)
    elevation_loss = Column(Float)
    avg_stride_length = Column(Float)
    vo2_max = Column(Float)
    training_effect_aerobic = Column(Float)
    training_effect_anaerobic = Column(Float)
    training_load = Column(Float)
    avg_ground_contact_time = Column(Float)
    avg_vertical_oscillation = Column(Float)
    avg_vertical_ratio = Column(Float)
    avg_ground_contact_balance = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)


class GarminDailySummary(Base):
    """Daily wellness summary from the Garmin Connect API."""

    __tablename__ = "garmin_daily_summary"

    date = Column(String, primary_key=True)  # YYYY-MM-DD
    total_steps = Column(Integer)
    total_distance_m = Column(Float)
    active_calories = Column(Float)
    total_calories = Column(Float)
    resting_heart_rate = Column(Integer)
    min_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    avg_stress_level = Column(Integer)
    max_stress_level = Column(Integer)
    body_battery_high = Column(Integer)
    body_battery_low = Column(Integer)
    avg_spo2 = Column(Float)
    lowest_spo2 = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)


class GarminSleep(Base):
    """Sleep data from the Garmin Connect API (when watch is worn during sleep)."""

    __tablename__ = "garmin_sleep"

    date = Column(String, primary_key=True)  # YYYY-MM-DD (calendar date of the sleep)
    start_time = Column(String)
    end_time = Column(String)
    total_sleep_seconds = Column(Integer)
    deep_sleep_seconds = Column(Integer)
    light_sleep_seconds = Column(Integer)
    rem_sleep_seconds = Column(Integer)
    awake_seconds = Column(Integer)
    sleep_score = Column(Float)
    avg_spo2_sleep = Column(Float)
    avg_respiration = Column(Float)
    lowest_respiration = Column(Float)
    avg_stress_sleep = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)


class GarminHRV(Base):
    """HRV summary from the Garmin Connect API (when watch is worn during sleep)."""

    __tablename__ = "garmin_hrv"

    date = Column(String, primary_key=True)  # YYYY-MM-DD
    weekly_avg_ms = Column(Float)
    last_night_avg_ms = Column(Float)
    last_night_5min_high = Column(Float)
    baseline_low_ms = Column(Float)
    baseline_balanced_low = Column(Float)
    baseline_balanced_up = Column(Float)
    status = Column(String)  # BALANCED, UNBALANCED, POOR, etc.
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)


class SyncLog(Base):
    """Audit log for all data sync operations."""

    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)  # whoop, garmin, csv_import
    sync_type = Column(String, nullable=False)  # full, incremental, manual
    started_at = Column(String, nullable=False)
    completed_at = Column(String)
    records_fetched = Column(Integer, default=0)
    records_stored = Column(Integer, default=0)
    status = Column(String, default="running")  # running, success, error
    error_message = Column(Text)
    metadata_json = Column(Text)


class TokenStore(Base):
    """OAuth token storage for external API services."""

    __tablename__ = "token_store"

    service = Column(String, primary_key=True)  # whoop or garmin
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(String)
    token_data_json = Column(Text)  # full token blob
    updated_at = Column(String, nullable=False)
