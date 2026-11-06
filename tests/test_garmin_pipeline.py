"""Tests for the Garmin ingestion pipeline."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.clients.garmin_personal_auth import (
    GarminKeyError,
    GarminRateLimitError,
    GarminTransientError,
)
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminExerciseSummary,
    GarminHRV,
    GarminSleep,
    SyncLog,
)
from src.ingestion import garmin_pipeline
from src.ingestion.garmin_pipeline import (
    GarminPipeline,
    _ms_to_iso,
    _ts_to_iso,
    transform_activity,
    transform_daily_summary,
    transform_exercise_summaries,
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
    result = transform_daily_summary(
        "2024-03-05", SAMPLE_DAILY_SUMMARY, "2024-03-05T23:00:00+00:00"
    )

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


def test_sync_window_overlaps_previous_end(db):
    d = datetime.now(tz=UTC).date() - timedelta(days=1)
    log = SyncLog(
        source="garmin",
        sync_type="incremental",
        started_at="2024-03-04T00:00:00+00:00",
        status="success",
        metadata_json=json.dumps({"sync_start": "2024-03-01", "sync_end": d.isoformat()}),
    )
    db.add(log)
    db.commit()

    pipeline = GarminPipeline(db, client=MagicMock())
    start, end = pipeline._get_sync_window()
    assert start == d - timedelta(days=2)
    assert end == datetime.now(tz=UTC).date()


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


# ---------------------------------------------------------------------------
# Personal API shapes (Task 4)
# ---------------------------------------------------------------------------

_PFIX = Path(__file__).parent / "fixtures" / "garmin_personal"
_TS = "2026-11-06T09:00:00+00:00"


def _fx(name: str):
    return json.loads((_PFIX / name).read_text())


def test_transform_sleep_flat_fixture():
    rec = _fx("sleep.json")
    out = transform_sleep("2026-04-10", rec, _TS)
    assert out["total_sleep_seconds"] == rec["sleepTimeSeconds"]
    assert out["deep_sleep_seconds"] == rec["deepSleepSeconds"]
    assert out["sleep_score"] == rec["sleepScores"]["overall"]["value"]
    assert out["avg_stress_sleep"] == rec["avgSleepStress"]
    assert out["start_time"] == "2026-04-10T04:30:00+00:00"


@pytest.mark.parametrize("value", [1762387200000, "2025-11-06T00:00:00.0"])
def test_transform_sleep_accepts_ms_and_iso_timestamps(value):
    out = transform_sleep("2025-11-06", {"sleepStartTimestampGMT": value}, _TS)
    assert out["start_time"] == "2025-11-06T00:00:00+00:00"
    assert _ts_to_iso(None) is None


def test_transform_sleep_flat_empty():
    out = transform_sleep("2026-11-01", {"calendarDate": "2026-11-01"}, _TS)
    assert out["start_time"] is None
    assert out["total_sleep_seconds"] is None


def test_transform_sleep_legacy_wrapper():
    out = transform_sleep("2024-03-05", SAMPLE_SLEEP, _TS)
    assert out["total_sleep_seconds"] == 27000
    assert out["start_time"] is not None


def test_transform_hrv_lastnightavg():
    assert (
        transform_hrv("2026-11-01", {"hrvSummary": {"lastNightAvg": 55}}, _TS)["last_night_avg_ms"]
        == 55
    )


def test_transform_hrv_legacy_lastnight():
    assert (
        transform_hrv("2026-11-01", {"hrvSummary": {"lastNight": 62}}, _TS)["last_night_avg_ms"]
        == 62
    )


def test_transform_exercise_summaries_maps_fixture():
    acts = _fx("activities.json")
    acts = acts if isinstance(acts, list) else acts.get("activities", acts)
    rec = next(a for a in acts if a.get("summarizedExerciseSets"))
    src = rec["summarizedExerciseSets"]
    rows = transform_exercise_summaries("123", rec, _TS)
    assert len(rows) == len(src)
    for row, s in zip(rows, src, strict=True):
        assert row["activity_id"] == "123"
        assert row["exercise_category"] == s["category"]
        assert row["exercise_name"] == (s.get("subCategory") or s["category"])
        assert row["set_count"] == s["sets"]
        assert row["repetition_count"] == s["reps"]
        assert row["max_weight_kg"] == s["maxWeight"] / 1000
        assert row["volume_kg"] == s["volume"] / 1000
        assert row["duration_seconds"] == s["duration"] / 1000
        assert row["fetched_at"] == _TS


def test_transform_exercise_summaries_absent_field():
    assert transform_exercise_summaries("1", {"activityId": 1}, _TS) == []


def test_migration_014_creates_table_idempotent():
    from sqlalchemy import inspect

    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    run_migrations(engine=eng)
    cols = {c["name"] for c in inspect(eng).get_columns("garmin_exercise_summaries")}
    assert cols == {
        "id",
        "activity_id",
        "exercise_category",
        "exercise_name",
        "set_count",
        "repetition_count",
        "volume_kg",
        "max_weight_kg",
        "duration_seconds",
        "fetched_at",
        "user_id",
    }


# ---------------------------------------------------------------------------
# Pipeline wiring on the Personal API client (Task 5)
# ---------------------------------------------------------------------------


class FakeClient:
    """Records every call; no network."""

    def __init__(self, activities=None, summary=None, sleep=None, hrv=None):
        self.activities = activities or []
        self.summary = SAMPLE_DAILY_SUMMARY if summary is None else summary
        self.sleep = sleep
        self.hrv = hrv
        self.calls: list[str] = []
        self.activities_exc: Exception | None = None
        self.summary_exc: Exception | None = None

    def get_activities(self, start, end):
        self.calls.append("get_activities")
        if self.activities_exc:
            raise self.activities_exc
        return self.activities

    def get_daily_summary(self, d):
        self.calls.append("get_daily_summary")
        if self.summary_exc:
            raise self.summary_exc
        return self.summary

    def get_sleep(self, d):
        self.calls.append("get_sleep")
        return self.sleep

    def get_hrv(self, d):
        self.calls.append("get_hrv")
        return self.hrv


def _strength_record() -> dict:
    acts = _fx("activities.json")
    acts = acts if isinstance(acts, list) else acts.get("activities", acts)
    return next(a for a in acts if a.get("summarizedExerciseSets"))


def test_strength_activity_writes_summaries_without_extra_call(db):
    rec = _strength_record()
    client = FakeClient(activities=[rec])
    d = date(2024, 3, 5)
    log = GarminPipeline(db, client=client, user_id="u1").run(start=d, end=d)
    assert log.status == "success"
    rows = db.query(GarminExerciseSummary).all()
    assert len(rows) == len(rec["summarizedExerciseSets"])
    assert {r.user_id for r in rows} == {"u1"}
    assert set(client.calls) <= {"get_activities", "get_daily_summary", "get_sleep", "get_hrv"}
    assert client.calls.count("get_activities") == 1


def test_resync_replaces_summaries(db):
    rec = _strength_record()
    d = date(2024, 3, 5)
    for _ in range(2):
        GarminPipeline(db, client=FakeClient(activities=[rec])).run(start=d, end=d)
    assert db.query(GarminExerciseSummary).count() == len(rec["summarizedExerciseSets"])


def test_resync_with_emptied_summaries_removes_stale_rows(db):
    rec = _strength_record()
    d = date(2024, 3, 5)
    GarminPipeline(db, client=FakeClient(activities=[rec])).run(start=d, end=d)
    assert db.query(GarminExerciseSummary).count() > 0
    edited = {**rec, "summarizedExerciseSets": []}
    GarminPipeline(db, client=FakeClient(activities=[edited])).run(start=d, end=d)
    assert db.query(GarminExerciseSummary).count() == 0


def test_run_records_key_error(db):
    client = FakeClient()
    client.activities_exc = GarminKeyError("key rejected - see settings")
    d = date(2024, 3, 5)
    log = GarminPipeline(db, client=client).run(start=d, end=d)
    assert log.status == "error"
    assert "key rejected" in log.error_message


def test_run_aborts_on_rate_limit(db):
    client = FakeClient(activities=[SAMPLE_ACTIVITY])
    client.summary_exc = GarminRateLimitError("429")
    log = GarminPipeline(db, client=client).run(start=date(2024, 3, 1), end=date(2024, 3, 5))
    assert client.calls.count("get_daily_summary") == 1
    assert log.status == "error"


def test_run_records_transient_error(db):
    client = FakeClient()
    client.activities_exc = GarminTransientError("503")
    d = date(2024, 3, 5)
    log = GarminPipeline(db, client=client).run(start=d, end=d)
    assert log.status == "error"


def test_failed_run_does_not_advance_window(db):
    client = FakeClient()
    client.activities_exc = GarminTransientError("503")
    GarminPipeline(db, client=client).run()
    start, _ = GarminPipeline(db, client=MagicMock())._get_sync_window()
    assert (datetime.now(tz=UTC).date() - start).days == 30


def test_no_watch_night_writes_no_sleep_or_hrv_rows(db):
    client = FakeClient(sleep=None, hrv=None)
    d = date(2024, 3, 5)
    GarminPipeline(db, client=client).run(start=d, end=d)
    assert db.query(GarminSleep).count() == 0
    assert db.query(GarminHRV).count() == 0
    assert db.get(GarminDailySummary, "2024-03-05") is not None


def test_concurrent_run_skipped(db):
    client = FakeClient()
    assert garmin_pipeline._RUN_LOCK.acquire(blocking=False)
    try:
        assert GarminPipeline(db, client=client).run() is None
    finally:
        garmin_pipeline._RUN_LOCK.release()
    assert client.calls == []
    assert db.query(SyncLog).count() == 0


def test_lock_released_after_exception(db):
    client = FakeClient()
    client.activities_exc = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        GarminPipeline(db, client=client).run()
    assert garmin_pipeline._RUN_LOCK.acquire(blocking=False)
    garmin_pipeline._RUN_LOCK.release()
