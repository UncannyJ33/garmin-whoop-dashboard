from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class WhoopCycle(Base):
    """Daily physiological cycle from the Whoop API (/v2/cycle)."""

    __tablename__ = "whoop_cycles"

    id = Column(String, primary_key=True)          # Whoop cycle UUID
    user_id = Column(Integer, nullable=False)
    start_time = Column(String, nullable=False)    # ISO 8601
    end_time = Column(String)
    timezone_offset = Column(String)
    score_state = Column(String)                   # SCORED, PENDING, etc.
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
    recovery_score = Column(Float)                 # 0–100%
    resting_heart_rate = Column(Float)             # bpm
    hrv_rmssd = Column(Float)                      # ms
    spo2_pct = Column(Float)
    skin_temp_celsius = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="recovery")


class WhoopSleep(Base):
    """Sleep event from the Whoop API (/v2/activity/sleep)."""

    __tablename__ = "whoop_sleep"

    id = Column(String, primary_key=True)          # Whoop sleep UUID
    cycle_id = Column(String, ForeignKey("whoop_cycles.id"))
    start_time = Column(String, nullable=False)
    end_time = Column(String)
    timezone_offset = Column(String)
    nap = Column(Integer)                          # boolean: 0 or 1
    score_state = Column(String)
    total_in_bed_ms = Column(Integer)
    total_awake_ms = Column(Integer)
    total_light_ms = Column(Integer)
    total_sws_ms = Column(Integer)                 # slow wave / deep sleep
    total_rem_ms = Column(Integer)
    total_no_data_ms = Column(Integer)
    sleep_performance = Column(Float)              # percentage
    sleep_consistency = Column(Float)
    sleep_efficiency = Column(Float)
    respiratory_rate = Column(Float)
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="sleep")


class WhoopWorkout(Base):
    """Workout event from the Whoop API (/v2/activity/workout)."""

    __tablename__ = "whoop_workouts"

    id = Column(String, primary_key=True)          # Whoop workout UUID
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
    zone_durations_json = Column(Text)             # HR zone times as JSON array
    fetched_at = Column(String, nullable=False)
    raw_json = Column(Text)

    cycle = relationship("WhoopCycle", back_populates="workouts")


class SyncLog(Base):
    """Audit log for all data sync operations."""

    __tablename__ = "sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)        # whoop, garmin, csv_import
    sync_type = Column(String, nullable=False)     # full, incremental, manual
    started_at = Column(String, nullable=False)
    completed_at = Column(String)
    records_fetched = Column(Integer, default=0)
    records_stored = Column(Integer, default=0)
    status = Column(String, default="running")     # running, success, error
    error_message = Column(Text)
    metadata_json = Column(Text)


class TokenStore(Base):
    """OAuth token storage for external API services."""

    __tablename__ = "token_store"

    service = Column(String, primary_key=True)     # whoop or garmin
    access_token = Column(Text)
    refresh_token = Column(Text)
    expires_at = Column(String)
    token_data_json = Column(Text)                 # full token blob
    updated_at = Column(String, nullable=False)
