"""Tests for the Garmin ingestion pipeline."""

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminHRV,
    GarminSleep,
    SyncLog,
)
from src.ingestion.garmin_pipeline import (
    GarminPipeline,
    _ms_to_iso,
    transform_activity,
    transform_daily_summary,
    transform_hrv,
    transform_sleep,
)

IN_MEMORY = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Sample API payloads (mirrors real Garmin responses from live API inspection)
# ---------------------------------------------------------------------------

SAMPLE_ACTIVITY = {
    "activityId": 22058725765,
    "activityName": "McKinney - VO2 Max Intervals",
    "startTimeLocal": "2026-03-04 07:18:03",
    "startTimeGMT": "2026-03-04 13:18:03",
    "activityType": {"typeKey": "running"},
    "distance": 4612.36,
    "duration": 1966.68,
    "elapsedDuration": 1966.68,
    "elevationGain": 23.0,
    "elevationLoss": 19.0,
    "averageSpeed": 2.345,
    "maxSpeed": 4.161,
    "calories": 329.0,
    "averageHR": 146.0,
    "maxHR": 178.0,
    "averageRunningCadenceInStepsPerMinute": 143.8,
    "maxRunningCadenceInStepsPerMinute": 177.0,
    "avgStrideLength": 98.29,
    "vO2MaxValue": 51.0,
    "aerobicTrainingEffect": 3.0,
    "anaerobicTrainingEffect": 1.1,
    "activityTrainingLoad": 77.0,
    "avgGroundContactTime": 265.9,
    "avgVerticalOscillation": 7.9,
    "avgVerticalRatio": 8.54,
}

SAMPLE_DAILY_SUMMARY = {
    "totalSteps": 10234,
    "totalDistanceMeters": 8500,
    "activeKilocalories": 480.0,
    "totalKilocalories": 2100.0,
    "restingHeartRate": 52,
    "minHeartRate": 45,
    "maxHeartRate": 178,
    "averageStressLevel": 28,
    "maxStressLevel": 72,
    "bodyBatteryHighestValue": 88,
    "bodyBatteryLowestValue": 22,
    "averageSpo2": 97.5,
    "lowestSpo2": 94,
}

# sleepStartTimestampGMT / sleepEndTimestampGMT are Unix ms
_SLEEP_START_MS = 1709596200000  # 2024-03-05 00:30:00 UTC
_SLEEP_END_MS = 1709624400000  # 2024-03-05 08:20:00 UTC

SAMPLE_SLEEP = {
    "dailySleepDTO": {
        "calendarDate": "2024-03-05",
        "sleepTimeSeconds": 27000,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 10800,
        "remSleepSeconds": 6300,
        "awakeSleepSeconds": 1800,
        "sleepStartTimestampGMT": _SLEEP_START_MS,
        "sleepEndTimestampGMT": _SLEEP_END_MS,
    }
}

SAMPLE_HRV = {
    "hrvSummary": {
        "weeklyAvg": 58,
        "lastNight": 62,
        "lastNight5MinHigh": 74,
        "baseline": {
            "lowUpper": 48,
            "balancedLow": 52,
            "balancedUpper": 68,
        },
        "status": "BALANCED",
    }
}


# ---------------------------------------------------------------------------
# DB fixtures
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
# _ms_to_iso helper
# ---------------------------------------------------------------------------


def test_ms_to_iso_converts_correctly():
    result = _ms_to_iso(_SLEEP_START_MS)
    # Exact value depends on timezone handling — just verify it's ISO and UTC
    dt = datetime.fromisoformat(result)
    assert dt.tzinfo is not None
    assert dt.year == 2024


def test_ms_to_iso_returns_none_for_none():
    assert _ms_to_iso(None) is None


# ---------------------------------------------------------------------------
# transform_activity
# ---------------------------------------------------------------------------


def test_transform_activity_maps_fields():
    result = transform_activity(SAMPLE_ACTIVITY, "2026-03-04T10:00:00+00:00")

    assert result["activity_id"] == "22058725765"
    assert result["activity_type"] == "running"
    assert result["activity_name"] == "McKinney - VO2 Max Intervals"
    assert result["start_time"] == "2026-03-04 07:18:03"
    assert result["start_time_gmt"] == "2026-03-04 13:18:03"
    assert result["duration_seconds"] == 1966.68
    assert result["distance_meters"] == 4612.36
    assert result["avg_heart_rate"] == 146  # cast to int
    assert result["max_heart_rate"] == 178
    assert result["calories"] == 329.0
    assert result["vo2_max"] == 51.0
    assert result["training_load"] == 77.0
    assert result["avg_ground_contact_time"] == 265.9
    assert result["avg_ground_contact_balance"] is None  # never available
    assert result["raw_json"] is not None


def test_transform_activity_heart_rate_cast_to_int():
    """averageHR comes as float from the API — must be stored as int."""
    record = {**SAMPLE_ACTIVITY, "averageHR": 155.7, "maxHR": 180.2}
    result = transform_activity(record, "2026-03-04T10:00:00+00:00")
    assert result["avg_heart_rate"] == 155
    assert result["max_heart_rate"] == 180


def test_transform_activity_missing_optional_fields():
    """Activities without running dynamics must not raise."""
    minimal = {"activityId": 99, "activityType": {"typeKey": "cycling"}}
    result = transform_activity(minimal, "2026-03-04T10:00:00+00:00")
    assert result["activity_id"] == "99"
    assert result["avg_running_cadence"] is None
    assert result["vo2_max"] is None


def test_transform_activity_missing_activity_type():
    """Missing activityType dict must not raise."""
    record = {**SAMPLE_ACTIVITY}
    del record["activityType"]
    result = transform_activity(record, "2026-03-04T10:00:00+00:00")
    assert result["activity_type"] is None


# ---------------------------------------------------------------------------
# transform_daily_summary
# ---------------------------------------------------------------------------


def test_transform_daily_summary_maps_fields():
    result = transform_daily_summary("2024-03-05", SAMPLE_DAILY_SUMMARY, "2024-03-05T23:00:00+00:00")

    assert result["date"] == "2024-03-05"
    assert result["total_steps"] == 10234
    assert result["total_distance_m"] == 8500
    assert result["active_calories"] == 480.0
    assert result["resting_heart_rate"] == 52
    assert result["avg_stress_level"] == 28
    assert result["body_battery_high"] == 88
    assert result["body_battery_low"] == 22
    assert result["avg_spo2"] == 97.5
    assert result["lowest_spo2"] == 94


def test_transform_daily_summary_empty_record():
    """An empty merged dict (all endpoints failed) stores NULLs without raising."""
    result = transform_daily_summary("2024-03-05", {}, "2024-03-05T23:00:00+00:00")
    assert result["date"] == "2024-03-05"
    assert result["total_steps"] is None
    assert result["resting_heart_rate"] is None


# ---------------------------------------------------------------------------
# transform_sleep
# ---------------------------------------------------------------------------


def test_transform_sleep_converts_timestamps():
    result = transform_sleep("2024-03-05", SAMPLE_SLEEP, "2024-03-05T09:00:00+00:00")

    assert result["date"] == "2024-03-05"
    assert result["total_sleep_seconds"] == 27000
    assert result["deep_sleep_seconds"] == 5400
    assert result["rem_sleep_seconds"] == 6300
    # Timestamps must be ISO strings, not raw ints
    assert isinstance(result["start_time"], str)
    assert isinstance(result["end_time"], str)
    assert "T" in result["start_time"]  # ISO 8601 format


def test_transform_sleep_null_timestamps():
    """Missing timestamps (watch not worn) must produce None, not an error."""
    empty_sleep = {"dailySleepDTO": {"calendarDate": "2024-03-05"}}
    result = transform_sleep("2024-03-05", empty_sleep, "2024-03-05T09:00:00+00:00")
    assert result["start_time"] is None
    assert result["end_time"] is None
    assert result["total_sleep_seconds"] is None


# ---------------------------------------------------------------------------
# transform_hrv
# ---------------------------------------------------------------------------


def test_transform_hrv_maps_fields():
    result = transform_hrv("2024-03-05", SAMPLE_HRV, "2024-03-05T09:00:00+00:00")

    assert result["date"] == "2024-03-05"
    assert result["weekly_avg_ms"] == 58
    assert result["last_night_avg_ms"] == 62
    assert result["last_night_5min_high"] == 74
    assert result["baseline_low_ms"] == 48
    assert result["baseline_balanced_low"] == 52
    assert result["baseline_balanced_up"] == 68
    assert result["status"] == "BALANCED"


def test_transform_hrv_missing_baseline():
    """Missing baseline sub-dict must not raise."""
    record = {"hrvSummary": {"weeklyAvg": 55, "status": "POOR"}}
    result = transform_hrv("2024-03-05", record, "2024-03-05T09:00:00+00:00")
    assert result["weekly_avg_ms"] == 55
    assert result["baseline_low_ms"] is None


# ---------------------------------------------------------------------------
# Upsert behaviour
# ---------------------------------------------------------------------------


def test_upsert_creates_new_activity(db):
    pipeline = GarminPipeline(db, client=MagicMock())
    data = transform_activity(SAMPLE_ACTIVITY, "2026-03-04T10:00:00+00:00")
    pipeline._upsert(GarminActivity, "activity_id", data)
    db.commit()

    result = db.get(GarminActivity, "22058725765")
    assert result is not None
    assert result.activity_name == "McKinney - VO2 Max Intervals"


def test_upsert_updates_existing_activity(db):
    pipeline = GarminPipeline(db, client=MagicMock())
    data = transform_activity(SAMPLE_ACTIVITY, "2026-03-04T10:00:00+00:00")
    pipeline._upsert(GarminActivity, "activity_id", data)
    db.commit()

    updated = {**data, "activity_name": "Updated Name", "calories": 999.0}
    pipeline._upsert(GarminActivity, "activity_id", updated)
    db.commit()

    result = db.get(GarminActivity, "22058725765")
    assert result.activity_name == "Updated Name"
    assert result.calories == 999.0


def test_upsert_creates_daily_summary(db):
    pipeline = GarminPipeline(db, client=MagicMock())
    data = transform_daily_summary("2024-03-05", SAMPLE_DAILY_SUMMARY, "2024-03-05T23:00:00+00:00")
    pipeline._upsert(GarminDailySummary, "date", data)
    db.commit()

    result = db.get(GarminDailySummary, "2024-03-05")
    assert result is not None
    assert result.total_steps == 10234


# ---------------------------------------------------------------------------
# None-return handling (broken endpoints)
# ---------------------------------------------------------------------------


def test_sync_daily_skips_on_none_summary(db):
    """None return from get_daily_summary must not store a row or raise."""
    mock_client = MagicMock()
    mock_client.get_daily_summary.return_value = None
    mock_client.get_sleep.return_value = None
    mock_client.get_hrv.return_value = None

    pipeline = GarminPipeline(db, client=mock_client)
    fetched, stored = pipeline._sync_daily(date(2024, 3, 5), "2024-03-05T23:00:00+00:00")

    assert fetched == 0
    assert stored == 0
    assert db.get(GarminDailySummary, "2024-03-05") is None


def test_sync_daily_stores_summary_when_sleep_fails(db):
    """A None sleep return must not prevent daily summary from being stored."""
    mock_client = MagicMock()
    mock_client.get_daily_summary.return_value = SAMPLE_DAILY_SUMMARY
    mock_client.get_sleep.return_value = None
    mock_client.get_hrv.return_value = None

    pipeline = GarminPipeline(db, client=mock_client)
    fetched, stored = pipeline._sync_daily(date(2024, 3, 5), "2024-03-05T23:00:00+00:00")

    assert stored == 1
    assert db.get(GarminDailySummary, "2024-03-05") is not None
    assert db.get(GarminSleep, "2024-03-05") is None


def test_sync_daily_stores_all_when_all_available(db):
    """When all three endpoints return data, all three rows are stored."""
    mock_client = MagicMock()
    mock_client.get_daily_summary.return_value = SAMPLE_DAILY_SUMMARY
    mock_client.get_sleep.return_value = SAMPLE_SLEEP
    mock_client.get_hrv.return_value = SAMPLE_HRV

    pipeline = GarminPipeline(db, client=mock_client)
    fetched, stored = pipeline._sync_daily(date(2024, 3, 5), "2024-03-05T23:00:00+00:00")

    assert stored == 3
    assert db.get(GarminDailySummary, "2024-03-05") is not None
    assert db.get(GarminSleep, "2024-03-05") is not None
    assert db.get(GarminHRV, "2024-03-05") is not None


def test_sync_activities_skips_on_empty_list(db):
    """An empty activity list must not raise and must return (0, 0)."""
    mock_client = MagicMock()
    mock_client.get_activities.return_value = []

    pipeline = GarminPipeline(db, client=mock_client)
    fetched, stored = pipeline._sync_activities(date(2024, 3, 1), date(2024, 3, 5), "ts")

    assert fetched == 0
    assert stored == 0


def test_sync_activities_stores_multiple(db):
    mock_client = MagicMock()
    second_activity = {**SAMPLE_ACTIVITY, "activityId": 99999}
    mock_client.get_activities.return_value = [SAMPLE_ACTIVITY, second_activity]

    pipeline = GarminPipeline(db, client=mock_client)
    fetched, stored = pipeline._sync_activities(date(2024, 3, 1), date(2024, 3, 5), "ts")

    assert fetched == 2
    assert stored == 2
    assert db.get(GarminActivity, "22058725765") is not None
    assert db.get(GarminActivity, "99999") is not None


# ---------------------------------------------------------------------------
# Sync window
# ---------------------------------------------------------------------------


def test_sync_window_defaults_to_30_days(db):
    pipeline = GarminPipeline(db, client=MagicMock())
    start, end = pipeline._get_sync_window()
    assert (end - start).days == 30
    assert end == datetime.now(tz=UTC).date()


def test_sync_window_uses_last_successful_sync(db):
    yesterday = (datetime.now(tz=UTC).date() - timedelta(days=1)).isoformat()
    log = SyncLog(
        source="garmin",
        sync_type="incremental",
        started_at="2024-03-04T00:00:00+00:00",
        status="success",
        metadata_json=json.dumps({"sync_start": "2024-03-01", "sync_end": yesterday}),
    )
    db.add(log)
    db.commit()

    pipeline = GarminPipeline(db, client=MagicMock())
    start, end = pipeline._get_sync_window()
    assert start.isoformat() == yesterday


def test_sync_window_ignores_failed_syncs(db):
    """A failed sync entry must not be used to compute the next window."""
    log = SyncLog(
        source="garmin",
        sync_type="incremental",
        started_at="2024-03-04T00:00:00+00:00",
        status="error",
        metadata_json=json.dumps({"sync_start": "2024-03-01", "sync_end": "2024-03-04"}),
    )
    db.add(log)
    db.commit()

    pipeline = GarminPipeline(db, client=MagicMock())
    start, end = pipeline._get_sync_window()
    assert (end - start).days == 30  # fell back to default


# ---------------------------------------------------------------------------
# Full pipeline run
# ---------------------------------------------------------------------------


def test_run_creates_sync_log_on_success(db):
    mock_client = MagicMock()
    mock_client.get_activities.return_value = [SAMPLE_ACTIVITY]
    mock_client.get_daily_summary.return_value = SAMPLE_DAILY_SUMMARY
    mock_client.get_sleep.return_value = None
    mock_client.get_hrv.return_value = None

    pipeline = GarminPipeline(db, client=mock_client)
    log = pipeline.run(start=date(2024, 3, 5), end=date(2024, 3, 5))

    assert log.status == "success"
    assert log.source == "garmin"
    assert log.records_stored > 0
    assert log.completed_at is not None


def test_run_marks_error_on_exception(db):
    mock_client = MagicMock()
    mock_client.get_activities.side_effect = RuntimeError("API exploded")

    pipeline = GarminPipeline(db, client=mock_client)
    with pytest.raises(RuntimeError):
        pipeline.run(start=date(2024, 3, 5), end=date(2024, 3, 5))

    log = db.query(SyncLog).filter_by(source="garmin").first()
    assert log.status == "error"
    assert "API exploded" in log.error_message
