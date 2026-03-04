"""Tests for the database layer: connection, models, and migration."""

import pytest
from sqlalchemy import inspect

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migration
from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminHRV,
    GarminSleep,
    SyncLog,
    TokenStore,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
    WhoopWorkout,
)

IN_MEMORY = "sqlite:///:memory:"


@pytest.fixture
def engine():
    """Provide a shared in-memory SQLite engine with all tables created."""
    eng = get_engine(IN_MEMORY)
    run_migration(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Provide a database session bound to the shared in-memory engine."""
    Session = get_session_factory(engine)
    db = Session()
    yield db
    db.close()


def test_migration_creates_all_tables(engine):
    """All Phase 1 and Phase 2 tables must exist after running the migration."""
    existing = inspect(engine).get_table_names()
    expected = {
        "whoop_cycles",
        "whoop_recovery",
        "whoop_sleep",
        "whoop_workouts",
        "sync_log",
        "token_store",
        "garmin_activities",
        "garmin_daily_summary",
        "garmin_sleep",
        "garmin_hrv",
    }
    assert expected.issubset(set(existing))


def test_migration_is_idempotent(engine):
    """Running all migrations a second time must not raise or drop any data."""
    from src.database.migrations import run as run_migration  # noqa: PLC0415

    run_migration(engine=engine)  # second run — should be a no-op
    existing = inspect(engine).get_table_names()
    assert "garmin_activities" in existing


def test_whoop_cycle_insert_and_retrieve(session):
    cycle = WhoopCycle(
        id="cycle-001",
        user_id=12345,
        start_time="2024-03-01T00:00:00Z",
        end_time="2024-03-01T23:59:59Z",
        score_state="SCORED",
        strain=12.4,
        kilojoules=2100.0,
        avg_heart_rate=62,
        max_heart_rate=175,
        fetched_at="2024-03-02T08:00:00Z",
        raw_json='{"id": "cycle-001"}',
    )
    session.add(cycle)
    session.commit()

    result = session.get(WhoopCycle, "cycle-001")
    assert result is not None
    assert result.user_id == 12345
    assert result.strain == 12.4


def test_whoop_recovery_insert_and_retrieve(session):
    cycle = WhoopCycle(
        id="cycle-002",
        user_id=12345,
        start_time="2024-03-02T00:00:00Z",
        fetched_at="2024-03-03T08:00:00Z",
    )
    session.add(cycle)

    recovery = WhoopRecovery(
        id="recovery-001",
        cycle_id="cycle-002",
        sleep_id="sleep-001",
        score_state="SCORED",
        recovery_score=78.5,
        resting_heart_rate=52.0,
        hrv_rmssd=65.3,
        spo2_pct=98.0,
        skin_temp_celsius=33.8,
        fetched_at="2024-03-03T08:00:00Z",
    )
    session.add(recovery)
    session.commit()

    result = session.get(WhoopRecovery, "recovery-001")
    assert result is not None
    assert result.recovery_score == 78.5
    assert result.cycle_id == "cycle-002"


def test_whoop_sleep_insert_and_retrieve(session):
    cycle = WhoopCycle(
        id="cycle-003",
        user_id=12345,
        start_time="2024-03-03T00:00:00Z",
        fetched_at="2024-03-04T08:00:00Z",
    )
    session.add(cycle)

    sleep = WhoopSleep(
        id="sleep-001",
        cycle_id="cycle-003",
        start_time="2024-03-03T22:00:00Z",
        end_time="2024-03-04T06:30:00Z",
        nap=0,
        score_state="SCORED",
        total_in_bed_ms=30600000,
        total_sws_ms=5400000,
        total_rem_ms=7200000,
        sleep_performance=85.0,
        sleep_efficiency=92.0,
        fetched_at="2024-03-04T08:00:00Z",
    )
    session.add(sleep)
    session.commit()

    result = session.get(WhoopSleep, "sleep-001")
    assert result is not None
    assert result.nap == 0
    assert result.sleep_performance == 85.0


def test_whoop_workout_insert_and_retrieve(session):
    cycle = WhoopCycle(
        id="cycle-004",
        user_id=12345,
        start_time="2024-03-04T00:00:00Z",
        fetched_at="2024-03-05T08:00:00Z",
    )
    session.add(cycle)

    workout = WhoopWorkout(
        id="workout-001",
        cycle_id="cycle-004",
        start_time="2024-03-04T07:00:00Z",
        end_time="2024-03-04T08:00:00Z",
        sport_id=1,
        sport_name="Running",
        score_state="SCORED",
        strain=14.2,
        avg_heart_rate=155,
        max_heart_rate=182,
        kilojoules=1800.0,
        distance_meter=10200.0,
        fetched_at="2024-03-05T08:00:00Z",
        zone_durations_json="[0, 300000, 1800000, 900000, 600000]",
    )
    session.add(workout)
    session.commit()

    result = session.get(WhoopWorkout, "workout-001")
    assert result is not None
    assert result.sport_name == "Running"
    assert result.distance_meter == 10200.0


def test_sync_log_insert_and_retrieve(session):
    log = SyncLog(
        source="whoop",
        sync_type="full",
        started_at="2024-03-05T08:00:00Z",
        completed_at="2024-03-05T08:00:45Z",
        records_fetched=30,
        records_stored=30,
        status="success",
    )
    session.add(log)
    session.commit()

    result = session.query(SyncLog).filter_by(source="whoop").first()
    assert result is not None
    assert result.status == "success"
    assert result.records_fetched == 30
    assert result.id is not None  # autoincrement assigned


def test_token_store_insert_and_retrieve(session):
    token = TokenStore(
        service="whoop",
        access_token="access-abc123",
        refresh_token="refresh-xyz789",
        expires_at="2024-03-05T09:00:00Z",
        token_data_json='{"token_type": "Bearer"}',
        updated_at="2024-03-05T08:00:00Z",
    )
    session.add(token)
    session.commit()

    result = session.get(TokenStore, "whoop")
    assert result is not None
    assert result.access_token == "access-abc123"
    assert result.refresh_token == "refresh-xyz789"


def test_garmin_activity_insert_and_retrieve(session):
    activity = GarminActivity(
        activity_id="22058725765",
        activity_type="running",
        activity_name="Morning Run",
        start_time="2024-03-05T07:00:00",
        start_time_gmt="2024-03-05T13:00:00",
        duration_seconds=3600.0,
        elapsed_seconds=3650.0,
        distance_meters=10200.0,
        avg_heart_rate=155,
        max_heart_rate=182,
        avg_running_cadence=172.0,
        max_running_cadence=190.0,
        calories=620.0,
        avg_speed=2.83,
        max_speed=4.1,
        elevation_gain=45.0,
        elevation_loss=43.0,
        avg_stride_length=1.15,
        vo2_max=54.0,
        training_effect_aerobic=3.5,
        training_effect_anaerobic=0.8,
        training_load=112.0,
        avg_ground_contact_time=245.0,
        avg_vertical_oscillation=9.2,
        avg_vertical_ratio=8.4,
        avg_ground_contact_balance=50.1,
        fetched_at="2024-03-05T10:00:00Z",
        raw_json='{"activityId": 22058725765}',
    )
    session.add(activity)
    session.commit()

    result = session.get(GarminActivity, "22058725765")
    assert result is not None
    assert result.activity_name == "Morning Run"
    assert result.distance_meters == 10200.0
    assert result.vo2_max == 54.0


def test_garmin_daily_summary_insert_and_retrieve(session):
    summary = GarminDailySummary(
        date="2024-03-05",
        total_steps=10234,
        total_distance_m=8500.0,
        active_calories=480.0,
        total_calories=2100.0,
        resting_heart_rate=52,
        min_heart_rate=45,
        max_heart_rate=178,
        avg_stress_level=28,
        max_stress_level=72,
        body_battery_high=88,
        body_battery_low=22,
        avg_spo2=97.5,
        lowest_spo2=94.0,
        fetched_at="2024-03-05T23:00:00Z",
        raw_json='{"calendarDate": "2024-03-05"}',
    )
    session.add(summary)
    session.commit()

    result = session.get(GarminDailySummary, "2024-03-05")
    assert result is not None
    assert result.total_steps == 10234
    assert result.resting_heart_rate == 52
    assert result.body_battery_high == 88


def test_garmin_sleep_insert_and_retrieve(session):
    sleep = GarminSleep(
        date="2024-03-05",
        start_time="2024-03-04T22:30:00",
        end_time="2024-03-05T06:15:00",
        total_sleep_seconds=27000,
        deep_sleep_seconds=5400,
        light_sleep_seconds=10800,
        rem_sleep_seconds=6300,
        awake_seconds=1800,
        sleep_score=78.0,
        avg_spo2_sleep=96.8,
        avg_respiration=14.2,
        lowest_respiration=12.0,
        avg_stress_sleep=18.5,
        fetched_at="2024-03-05T09:00:00Z",
        raw_json='{"calendarDate": "2024-03-05"}',
    )
    session.add(sleep)
    session.commit()

    result = session.get(GarminSleep, "2024-03-05")
    assert result is not None
    assert result.total_sleep_seconds == 27000
    assert result.sleep_score == 78.0
    assert result.rem_sleep_seconds == 6300


def test_garmin_hrv_insert_and_retrieve(session):
    hrv = GarminHRV(
        date="2024-03-05",
        weekly_avg_ms=58.0,
        last_night_avg_ms=62.0,
        last_night_5min_high=74.0,
        baseline_low_ms=48.0,
        baseline_balanced_low=52.0,
        baseline_balanced_up=68.0,
        status="BALANCED",
        fetched_at="2024-03-05T09:00:00Z",
        raw_json='{"startTimestampGMT": "2024-03-04T22:30:00"}',
    )
    session.add(hrv)
    session.commit()

    result = session.get(GarminHRV, "2024-03-05")
    assert result is not None
    assert result.last_night_avg_ms == 62.0
    assert result.status == "BALANCED"


def test_garmin_daily_summary_upsert(session):
    """A second insert with the same date PK must update, not create a duplicate."""
    summary = GarminDailySummary(
        date="2024-03-06",
        total_steps=5000,
        fetched_at="2024-03-06T12:00:00Z",
    )
    session.add(summary)
    session.commit()

    # Update via merge (upsert pattern)
    updated = GarminDailySummary(
        date="2024-03-06",
        total_steps=12000,
        fetched_at="2024-03-06T23:00:00Z",
    )
    session.merge(updated)
    session.commit()

    results = session.query(GarminDailySummary).filter_by(date="2024-03-06").all()
    assert len(results) == 1
    assert results[0].total_steps == 12000
