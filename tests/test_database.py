"""Tests for the database layer: connection, models, and migration."""

import pytest
from sqlalchemy import inspect

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migration
from src.database.models import (
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
    """All six Phase 1 tables must exist after running the migration."""
    existing = inspect(engine).get_table_names()
    expected = {
        "whoop_cycles",
        "whoop_recovery",
        "whoop_sleep",
        "whoop_workouts",
        "sync_log",
        "token_store",
    }
    assert expected.issubset(set(existing))


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
