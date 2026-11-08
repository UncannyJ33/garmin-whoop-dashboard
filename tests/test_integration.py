"""End-to-end integration tests for the full data pipeline.

Each test covers a complete path from API response → raw table → unified table,
using in-memory SQLite and mocked API clients.  No external network calls are
made; all API responses are injected via mocks.

Scenarios covered:
  1. Whoop pipeline  → unified_daily + unified_sleep + unified_workouts
  2. Garmin pipeline → unified_daily (body battery, stress, VO2 max)
  3. Cross-source workout deduplication → matched unified_workout row
  4. CSV import      → unified_workouts (Garmin-only, no Whoop match)
"""

import csv
import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminActivity,
    UnifiedDaily,
    UnifiedSleep,
    UnifiedWorkout,
    WhoopWorkout,
)
from src.ingestion.csv_import import GarminImporter
from src.ingestion.garmin_pipeline import GarminPipeline
from src.ingestion.whoop_pipeline import WhoopPipeline
from src.normalization.normalizer import Normalizer

IN_MEMORY = "sqlite:///:memory:"


# ---------------------------------------------------------------------------
# DB fixtures — fresh in-memory DB per test
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    Session = get_session_factory(engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Sample Whoop API responses (mirrors test_whoop_pipeline.py fixtures)
# ---------------------------------------------------------------------------

_CYCLE = {
    "id": 1344375740,
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:36.710Z",
    "updated_at": "2024-03-03T14:54:42.636Z",
    "start": "2024-03-03T03:50:11.610Z",
    "end": "2024-03-03T23:59:59.000Z",
    "timezone_offset": "-06:00",
    "score_state": "SCORED",
    "score": {
        "strain": 13.0,
        "kilojoule": 5933.0,
        "average_heart_rate": 71,
        "max_heart_rate": 145,
    },
}

_RECOVERY = {
    "cycle_id": 1344375740,
    "sleep_id": "sleep-abc-001",
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:41.299Z",
    "updated_at": "2024-03-03T12:02:51.647Z",
    "score_state": "SCORED",
    "score": {
        "user_calibrating": False,
        "recovery_score": 75.0,
        "resting_heart_rate": 62.0,
        "hrv_rmssd_milli": 64.1,
        "spo2_percentage": 96.5,
        "skin_temp_celsius": 34.9,
    },
}

_SLEEP = {
    "id": "sleep-abc-001",
    "cycle_id": 1344375740,
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:41.299Z",
    "updated_at": "2024-03-03T12:02:51.647Z",
    "start": "2024-03-03T00:00:00.000Z",
    "end": "2024-03-03T07:30:00.000Z",
    "timezone_offset": "-06:00",
    "nap": False,
    "score_state": "SCORED",
    "score": {
        "stage_summary": {
            "total_in_bed_time_milli": 27_000_000,
            "total_awake_time_milli": 1_800_000,
            "total_no_data_time_milli": 0,
            "total_light_sleep_time_milli": 12_600_000,
            "total_slow_wave_sleep_time_milli": 5_400_000,
            "total_rem_sleep_time_milli": 7_200_000,
        },
        "respiratory_rate": 14.2,
        "sleep_performance_percentage": 80.0,
        "sleep_consistency_percentage": 75.0,
        "sleep_efficiency_percentage": 91.0,
    },
}

_WORKOUT_RUNNING = {
    "id": "workout-run-001",
    "user_id": 30512397,
    "created_at": "2024-03-03T14:54:09.320Z",
    "updated_at": "2024-03-03T14:54:42.636Z",
    "start": "2024-03-03T14:00:00.000Z",
    "end": "2024-03-03T15:00:00.000Z",
    "timezone_offset": "-06:00",
    "sport_id": 1,
    "sport_name": "running",
    "score_state": "SCORED",
    "cycle_id": 1344375740,
    "score": {
        "strain": 14.2,
        "average_heart_rate": 155,
        "max_heart_rate": 182,
        "kilojoule": 1800.0,
        "distance_meter": 10000.0,
        "altitude_gain_meter": 40.0,
        "altitude_change_meter": -2.0,
        "zone_duration": {
            "zone_zero_milli": 0,
            "zone_one_milli": 300_000,
            "zone_two_milli": 1_800_000,
            "zone_three_milli": 900_000,
            "zone_four_milli": 600_000,
            "zone_five_milli": 0,
        },
    },
}


# ---------------------------------------------------------------------------
# Sample Garmin API responses (mirrors test_garmin_pipeline.py fixtures)
# ---------------------------------------------------------------------------

_GARMIN_ACTIVITY = {
    "activityId": 55001,
    "activityName": "Morning Run",
    "startTimeLocal": "2024-03-05 07:00:00",
    "startTimeGMT": "2024-03-05 13:00:00",
    "activityType": {"typeKey": "running"},
    "distance": 5000.0,
    "duration": 1800.0,
    "elapsedDuration": 1800.0,
    "elevationGain": 30.0,
    "elevationLoss": 28.0,
    "averageSpeed": 2.78,
    "maxSpeed": 3.5,
    "calories": 300.0,
    "averageHR": 150.0,
    "maxHR": 172.0,
    "averageRunningCadenceInStepsPerMinute": 160.0,
    "vO2MaxValue": 52.0,
    "aerobicTrainingEffect": 3.2,
    "anaerobicTrainingEffect": 0.8,
    "activityTrainingLoad": 65.0,
    "avgGroundContactTime": 250.0,
    "avgVerticalOscillation": 7.5,
    "avgVerticalRatio": 8.1,
}

_GARMIN_DAILY = {
    "totalSteps": 9800,
    "totalDistanceMeters": 7500,
    "activeKilocalories": 420.0,
    "totalKilocalories": 1950.0,
    "restingHeartRate": 54,
    "minHeartRate": 47,
    "maxHeartRate": 172,
    "averageStressLevel": 30,
    "maxStressLevel": 65,
    "bodyBatteryHighestValue": 88,
    "bodyBatteryLowestValue": 20,
    "averageSpo2": 97.2,
    "lowestSpo2": 94,
}


# ---------------------------------------------------------------------------
# Test 1: Whoop pipeline → unified_daily + unified_sleep + unified_workouts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whoop_pipeline_populates_unified_tables(db):
    """Full Whoop sync: API → raw tables → normalizer → unified tables."""
    mock_client = MagicMock()
    mock_client.get_cycles = AsyncMock(return_value=[_CYCLE])
    mock_client.get_recovery = AsyncMock(return_value=[_RECOVERY])
    mock_client.get_sleep = AsyncMock(return_value=[_SLEEP])
    mock_client.get_workouts = AsyncMock(return_value=[_WORKOUT_RUNNING])

    pipeline = WhoopPipeline(db, client=mock_client)
    log = await pipeline.run(
        start=datetime(2024, 3, 3, tzinfo=UTC),
        end=datetime(2024, 3, 3, tzinfo=UTC),
    )

    assert log.status == "success"

    # unified_daily row for 2024-03-03
    daily = db.get(UnifiedDaily, "2024-03-03")
    assert daily is not None
    assert daily.whoop_recovery_score == pytest.approx(75.0)
    sources = json.loads(daily.data_sources)
    assert "whoop" in sources

    # unified_sleep row for 2024-03-03 (DATE(end_time) = "2024-03-03")
    sleep = db.get(UnifiedSleep, "2024-03-03")
    assert sleep is not None
    assert sleep.whoop_performance == pytest.approx(80.0)
    assert sleep.whoop_efficiency == pytest.approx(91.0)
    assert sleep.total_sleep_minutes == pytest.approx(450.0)  # total_in_bed_ms / 60000
    assert sleep.primary_source == "whoop"

    # unified_workouts row for the running workout (Whoop-only, no Garmin match)
    workout = db.get(UnifiedWorkout, "w_workout-run-001")
    assert workout is not None
    assert workout.whoop_strain == pytest.approx(14.2)
    assert workout.matched == 0
    assert workout.primary_source == "whoop"


# ---------------------------------------------------------------------------
# Test 2: Garmin pipeline → unified_daily
# ---------------------------------------------------------------------------


def test_garmin_pipeline_populates_unified_tables(db):
    """Full Garmin sync: API → raw tables → normalizer → unified tables."""
    mock_client = MagicMock()
    mock_client.get_activities.return_value = [_GARMIN_ACTIVITY]
    mock_client.get_daily_summary.return_value = _GARMIN_DAILY
    mock_client.get_sleep.return_value = None
    mock_client.get_hrv.return_value = None

    pipeline = GarminPipeline(db, client=mock_client)
    log = pipeline.run(start=date(2024, 3, 5), end=date(2024, 3, 5))

    assert log.status == "success"

    # unified_daily populated with Garmin daily metrics
    daily = db.get(UnifiedDaily, "2024-03-05")
    assert daily is not None
    assert daily.garmin_body_battery_high == 88
    assert daily.garmin_body_battery_low == 20
    assert daily.garmin_avg_stress == 30
    sources = json.loads(daily.data_sources)
    assert "garmin" in sources
    assert "whoop" not in sources

    # VO2 max pulled from activities on that date
    assert daily.garmin_vo2_max == pytest.approx(52.0)


# ---------------------------------------------------------------------------
# Test 3: Cross-source workout deduplication
# ---------------------------------------------------------------------------


def test_cross_source_workout_match_creates_unified_row(db):
    """Whoop workout + overlapping Garmin activity → matched unified_workout row."""
    # Whoop workout: 60-min run starting 14:00 UTC
    whoop_w = WhoopWorkout(
        id="w-cross-001",
        start_time="2024-03-07T14:00:00Z",
        end_time="2024-03-07T15:00:00Z",
        sport_name="running",
        strain=13.5,
        avg_heart_rate=158,
        kilojoules=1700.0,
        fetched_at=datetime.now(tz=UTC).isoformat(),
    )
    # Garmin activity: 60-min run starting 14:02 UTC (2 min later — within threshold)
    garmin_a = GarminActivity(
        activity_id="g-cross-001",
        activity_type="running",
        start_time="2024-03-07 07:00:00",
        start_time_gmt="2024-03-07 14:02:00",
        duration_seconds=3600.0,
        distance_meters=10100.0,
        avg_heart_rate=160,
        fetched_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add_all([whoop_w, garmin_a])
    db.commit()

    n = Normalizer(db)
    rows = n.normalize_workouts(date(2024, 3, 7), date(2024, 3, 7))

    assert rows == 1

    row = db.get(UnifiedWorkout, "w_w-cross-001")
    assert row is not None
    assert row.matched == 1
    assert row.match_confidence > 0.5
    assert row.primary_source == "both"
    assert row.whoop_strain == pytest.approx(13.5)
    assert row.garmin_activity_id == "g-cross-001"
    assert row.garmin_distance_m == pytest.approx(10100.0)


def test_matched_workout_removes_garmin_only_row(db):
    """Garmin synced first, Whoop later: the stale g_<aid> row is removed on match."""
    garmin_a = GarminActivity(
        activity_id="g-late-001",
        activity_type="running",
        start_time="2024-03-07 07:00:00",
        start_time_gmt="2024-03-07 14:02:00",
        duration_seconds=3600.0,
        fetched_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(garmin_a)
    db.commit()

    n = Normalizer(db)
    n.normalize_workouts(date(2024, 3, 7), date(2024, 3, 7))
    assert db.get(UnifiedWorkout, "g_g-late-001") is not None

    db.add(
        WhoopWorkout(
            id="w-late-001",
            start_time="2024-03-07T14:00:00Z",
            end_time="2024-03-07T15:00:00Z",
            sport_name="running",
            strain=13.5,
            fetched_at=datetime.now(tz=UTC).isoformat(),
        )
    )
    db.commit()
    n.normalize_workouts(date(2024, 3, 7), date(2024, 3, 7))

    count = db.execute(
        text("SELECT COUNT(*) FROM unified_workouts WHERE garmin_activity_id = :aid"),
        {"aid": "g-late-001"},
    ).scalar()
    assert count == 1
    row = db.execute(
        text("SELECT id FROM unified_workouts WHERE garmin_activity_id = :aid"),
        {"aid": "g-late-001"},
    ).scalar()
    assert row == "w_w-late-001"
    assert db.get(UnifiedWorkout, "g_g-late-001") is None


def test_unmatched_garmin_activity_stored_as_garmin_only(db):
    """Garmin activity with no nearby Whoop workout → Garmin-only unified row."""
    garmin_a = GarminActivity(
        activity_id="g-only-001",
        activity_type="cycling",
        start_time="2024-03-08 06:00:00",
        start_time_gmt="2024-03-08 12:00:00",
        duration_seconds=5400.0,
        fetched_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(garmin_a)
    db.commit()

    n = Normalizer(db)
    rows = n.normalize_workouts(date(2024, 3, 8), date(2024, 3, 8))

    assert rows == 1
    row = db.get(UnifiedWorkout, "g_g-only-001")
    assert row is not None
    assert row.matched == 0
    assert row.primary_source == "garmin"
    assert row.whoop_strain is None


def test_whoop_only_workout_stored_when_no_garmin(db):
    """Whoop workout with no matching Garmin activity → Whoop-only unified row."""
    whoop_w = WhoopWorkout(
        id="w-only-001",
        start_time="2024-03-09T09:00:00Z",
        end_time="2024-03-09T10:00:00Z",
        sport_name="strength_training",
        strain=11.0,
        fetched_at=datetime.now(tz=UTC).isoformat(),
    )
    db.add(whoop_w)
    db.commit()

    n = Normalizer(db)
    rows = n.normalize_workouts(date(2024, 3, 9), date(2024, 3, 9))

    assert rows == 1
    row = db.get(UnifiedWorkout, "w_w-only-001")
    assert row is not None
    assert row.matched == 0
    assert row.primary_source == "whoop"
    assert row.garmin_activity_id is None


# ---------------------------------------------------------------------------
# Test 4: CSV import → normalize
# ---------------------------------------------------------------------------


def test_csv_import_then_normalize(db, tmp_path):
    """Import a Garmin CSV file and verify unified_workouts is populated."""
    csv_file = tmp_path / "garmin_activities.csv"
    with csv_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "activity_id",
                "activity_type",
                "start_time",
                "start_time_gmt",
                "duration_seconds",
                "distance_meters",
                "avg_heart_rate",
            ]
        )
        writer.writerow(
            [
                "csv-act-001",
                "running",
                "2024-04-01 07:00:00",
                "2024-04-01 13:00:00",
                "3600",
                "10000",
                "155",
            ]
        )

    importer = GarminImporter(db, normalize=True)
    summary = importer.import_from(csv_file)

    # Raw table populated
    assert db.get(GarminActivity, "csv-act-001") is not None

    # SyncLog entry created
    assert summary.activities == 1

    # Normalization ran and produced a Garmin-only unified_workout row
    row = db.get(UnifiedWorkout, "g_csv-act-001")
    assert row is not None
    assert row.primary_source == "garmin"
    assert row.matched == 0
    assert row.garmin_distance_m == pytest.approx(10000.0)


def test_csv_import_normalize_false_skips_unified(db, tmp_path):
    """When normalize=False, unified tables are NOT updated after import."""
    csv_file = tmp_path / "garmin_activities.csv"
    with csv_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["activity_id", "start_time_gmt", "duration_seconds"])
        writer.writerow(["csv-no-norm-001", "2024-04-02 13:00:00", "1800"])

    importer = GarminImporter(db, normalize=False)
    importer.import_from(csv_file)

    # Raw table populated
    assert db.get(GarminActivity, "csv-no-norm-001") is not None
    # Unified table NOT populated
    assert db.get(UnifiedWorkout, "g_csv-no-norm-001") is None
