"""Tests for the Whoop ingestion pipeline — transforms, upserts, and sync logging."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import SyncLog, WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout
from src.ingestion.whoop_pipeline import (
    WhoopPipeline,
    transform_cycle,
    transform_recovery,
    transform_sleep,
    transform_workout,
)

IN_MEMORY = "sqlite:///:memory:"
FETCHED_AT = "2024-03-05T08:00:00+00:00"

# ---------------------------------------------------------------------------
# Sample API response fixtures (matching real Whoop v2 field names)
# ---------------------------------------------------------------------------

CYCLE_SCORED = {
    "id": 1344375740,
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:36.710Z",
    "updated_at": "2024-03-03T14:54:42.636Z",
    "start": "2024-03-03T03:50:11.610Z",
    "end": "2024-03-03T23:59:59.000Z",
    "timezone_offset": "-06:00",
    "score_state": "SCORED",
    "score": {
        "strain": 13.023597,
        "kilojoule": 5933.488,
        "average_heart_rate": 71,
        "max_heart_rate": 145,
    },
}

CYCLE_PENDING = {
    "id": 1344375741,
    "user_id": 30512397,
    "created_at": "2024-03-04T11:00:00.000Z",
    "updated_at": "2024-03-04T11:00:00.000Z",
    "start": "2024-03-04T03:50:00.000Z",
    "end": None,
    "timezone_offset": "-06:00",
    "score_state": "PENDING_AVAILABILITY",
    "score": None,
}

RECOVERY = {
    "cycle_id": 1344375740,
    "sleep_id": "cff40ed8-5816-4001-a3cc-501fba8e8b03",
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:41.299Z",
    "updated_at": "2024-03-03T12:02:51.647Z",
    "score_state": "SCORED",
    "score": {
        "user_calibrating": False,
        "recovery_score": 75.0,
        "resting_heart_rate": 62.0,
        "hrv_rmssd_milli": 64.12548,
        "spo2_percentage": 96.57895,
        "skin_temp_celsius": 34.946667,
    },
}

SLEEP = {
    "id": "cff40ed8-5816-4001-a3cc-501fba8e8b03",
    "cycle_id": 1344375740,
    "user_id": 30512397,
    "created_at": "2024-03-03T11:09:41.299Z",
    "updated_at": "2024-03-03T12:02:51.647Z",
    "start": "2024-03-03T03:50:11.610Z",
    "end": "2024-03-03T12:00:21.300Z",
    "timezone_offset": "-06:00",
    "nap": False,
    "score_state": "SCORED",
    "score": {
        "stage_summary": {
            "total_in_bed_time_milli": 29409690,
            "total_awake_time_milli": 4355110,
            "total_no_data_time_milli": 0,
            "total_light_sleep_time_milli": 12772340,
            "total_slow_wave_sleep_time_milli": 7747190,
            "total_rem_sleep_time_milli": 4535050,
        },
        "respiratory_rate": 12.832031,
        "sleep_performance_percentage": 80.0,
        "sleep_consistency_percentage": 84.0,
        "sleep_efficiency_percentage": 85.19158,
    },
}

WORKOUT_SCORED = {
    "id": "80e8023c-b3d4-4c15-993c-1ce41ad51001",
    "user_id": 30512397,
    "created_at": "2024-03-03T14:54:09.320Z",
    "updated_at": "2024-03-03T14:54:42.636Z",
    "start": "2024-03-03T14:42:51.802Z",
    "end": "2024-03-03T15:42:51.802Z",
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
        "distance_meter": 10200.0,
        "altitude_gain_meter": 50.0,
        "altitude_change_meter": -2.0,
        "zone_duration": {
            "zone_zero_milli": 0,
            "zone_one_milli": 300000,
            "zone_two_milli": 1800000,
            "zone_three_milli": 900000,
            "zone_four_milli": 600000,
            "zone_five_milli": 0,
        },
    },
}

WORKOUT_NULL_SCORE = {
    "id": "80e8023c-b3d4-4c15-993c-1ce41ad51002",
    "user_id": 30512397,
    "created_at": "2024-03-03T14:54:09.320Z",
    "updated_at": "2024-03-03T14:54:42.636Z",
    "start": "2024-03-03T14:42:51.802Z",
    "end": "2024-03-03T14:54:08.587Z",
    "timezone_offset": "-06:00",
    "sport_id": 128,
    "sport_name": "stretching",
    "score_state": "SCORED",
    "cycle_id": 1344375740,
    "score": None,
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
# Transform: cycle
# ---------------------------------------------------------------------------


def test_transform_cycle_scored():
    result = transform_cycle(CYCLE_SCORED, FETCHED_AT)
    assert result["id"] == "1344375740"
    assert result["user_id"] == 30512397
    assert result["start_time"] == "2024-03-03T03:50:11.610Z"
    assert result["end_time"] == "2024-03-03T23:59:59.000Z"
    assert result["score_state"] == "SCORED"
    assert result["strain"] == pytest.approx(13.023597)
    assert result["kilojoules"] == pytest.approx(5933.488)
    assert result["avg_heart_rate"] == 71
    assert result["max_heart_rate"] == 145
    assert result["fetched_at"] == FETCHED_AT
    assert json.loads(result["raw_json"])["id"] == 1344375740


def test_transform_cycle_pending_score_is_null():
    """Pending cycles have a null score — all score fields must be None, not raise."""
    result = transform_cycle(CYCLE_PENDING, FETCHED_AT)
    assert result["score_state"] == "PENDING_AVAILABILITY"
    assert result["strain"] is None
    assert result["kilojoules"] is None
    assert result["avg_heart_rate"] is None
    assert result["end_time"] is None


# ---------------------------------------------------------------------------
# Transform: recovery
# ---------------------------------------------------------------------------


def test_transform_recovery_fields():
    result = transform_recovery(RECOVERY, FETCHED_AT)
    assert result["id"] == "1344375740"  # synthetic from cycle_id
    assert result["cycle_id"] == "1344375740"
    assert result["sleep_id"] == "cff40ed8-5816-4001-a3cc-501fba8e8b03"
    assert result["recovery_score"] == pytest.approx(75.0)
    assert result["resting_heart_rate"] == pytest.approx(62.0)
    assert result["hrv_rmssd"] == pytest.approx(64.12548)
    assert result["spo2_pct"] == pytest.approx(96.57895)
    assert result["skin_temp_celsius"] == pytest.approx(34.946667)


def test_transform_recovery_null_score():
    record = {**RECOVERY, "score": None}
    result = transform_recovery(record, FETCHED_AT)
    assert result["recovery_score"] is None
    assert result["hrv_rmssd"] is None


# ---------------------------------------------------------------------------
# Transform: sleep
# ---------------------------------------------------------------------------


def test_transform_sleep_fields():
    result = transform_sleep(SLEEP, FETCHED_AT)
    assert result["id"] == "cff40ed8-5816-4001-a3cc-501fba8e8b03"
    assert result["cycle_id"] == "1344375740"
    assert result["nap"] == 0
    assert result["total_in_bed_ms"] == 29409690
    assert result["total_sws_ms"] == 7747190
    assert result["total_rem_ms"] == 4535050
    assert result["sleep_performance"] == pytest.approx(80.0)
    assert result["sleep_efficiency"] == pytest.approx(85.19158)
    assert result["respiratory_rate"] == pytest.approx(12.832031)


def test_transform_sleep_nap_true():
    record = {**SLEEP, "nap": True}
    assert transform_sleep(record, FETCHED_AT)["nap"] == 1


def test_transform_sleep_null_score():
    record = {**SLEEP, "score": None}
    result = transform_sleep(record, FETCHED_AT)
    assert result["total_in_bed_ms"] is None
    assert result["sleep_performance"] is None


# ---------------------------------------------------------------------------
# Transform: workout
# ---------------------------------------------------------------------------


def test_transform_workout_scored():
    result = transform_workout(WORKOUT_SCORED, FETCHED_AT)
    assert result["id"] == "80e8023c-b3d4-4c15-993c-1ce41ad51001"
    assert result["sport_name"] == "running"
    assert result["strain"] == pytest.approx(14.2)
    assert result["avg_heart_rate"] == 155
    assert result["distance_meter"] == pytest.approx(10200.0)
    zones = json.loads(result["zone_durations_json"])
    assert zones == [0, 300000, 1800000, 900000, 600000, 0]


def test_transform_workout_null_score():
    result = transform_workout(WORKOUT_NULL_SCORE, FETCHED_AT)
    assert result["strain"] is None
    assert result["avg_heart_rate"] is None
    assert result["zone_durations_json"] is None


# ---------------------------------------------------------------------------
# Upsert: no duplicates on re-run
# ---------------------------------------------------------------------------


def test_upsert_cycle_no_duplicates(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_cycles([CYCLE_SCORED], FETCHED_AT)
    pipeline._store_cycles([CYCLE_SCORED], FETCHED_AT)  # second run, same data
    count = db.query(WhoopCycle).count()
    assert count == 1


def test_upsert_recovery_no_duplicates(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_recovery([RECOVERY], FETCHED_AT)
    pipeline._store_recovery([RECOVERY], FETCHED_AT)
    assert db.query(WhoopRecovery).count() == 1


def test_upsert_sleep_no_duplicates(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_sleep([SLEEP], FETCHED_AT)
    pipeline._store_sleep([SLEEP], FETCHED_AT)
    assert db.query(WhoopSleep).count() == 1


def test_upsert_workout_no_duplicates(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_workouts([WORKOUT_SCORED, WORKOUT_NULL_SCORE], FETCHED_AT)
    pipeline._store_workouts([WORKOUT_SCORED, WORKOUT_NULL_SCORE], FETCHED_AT)
    assert db.query(WhoopWorkout).count() == 2


def test_upsert_updates_existing_row(db):
    """Re-running with updated data overwrites the existing row."""
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_cycles([CYCLE_SCORED], FETCHED_AT)

    updated = {**CYCLE_SCORED, "score": {**CYCLE_SCORED["score"], "strain": 99.9}}
    pipeline._store_cycles([updated], FETCHED_AT)

    row = db.get(WhoopCycle, "1344375740")
    assert row.strain == pytest.approx(99.9)
    assert db.query(WhoopCycle).count() == 1


# ---------------------------------------------------------------------------
# Sync log tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_log_success(db):
    """A successful run writes a 'success' sync_log entry with record counts."""
    mock_client = MagicMock()
    mock_client.get_cycles = AsyncMock(return_value=[CYCLE_SCORED])
    mock_client.get_recovery = AsyncMock(return_value=[RECOVERY])
    mock_client.get_sleep = AsyncMock(return_value=[SLEEP])
    mock_client.get_workouts = AsyncMock(return_value=[WORKOUT_SCORED])

    pipeline = WhoopPipeline(db, client=mock_client)
    log = await pipeline.run(
        start=datetime(2024, 3, 1, tzinfo=UTC),
        end=datetime(2024, 3, 5, tzinfo=UTC),
    )

    assert log.status == "success"
    assert log.records_fetched == 4
    assert log.records_stored == 4
    assert log.completed_at is not None
    assert log.error_message is None


@pytest.mark.asyncio
async def test_sync_log_error(db):
    """A failing sync writes an 'error' entry with the exception message."""
    mock_client = MagicMock()
    mock_client.get_cycles = AsyncMock(side_effect=RuntimeError("API down"))

    pipeline = WhoopPipeline(db, client=mock_client)
    with pytest.raises(RuntimeError, match="API down"):
        await pipeline.run(
            start=datetime(2024, 3, 1, tzinfo=UTC),
            end=datetime(2024, 3, 5, tzinfo=UTC),
        )

    log = db.query(SyncLog).filter_by(source="whoop").first()
    assert log.status == "error"
    assert "API down" in log.error_message
    assert log.completed_at is not None


# ---------------------------------------------------------------------------
# Sync window determination
# ---------------------------------------------------------------------------


def test_sync_window_defaults_to_30_days(db):
    """With no prior sync, window starts 30 days ago."""
    pipeline = WhoopPipeline(db, client=MagicMock())
    start, end = pipeline._get_sync_window()
    expected_start = datetime.now(tz=UTC) - timedelta(days=30)
    assert abs((start - expected_start).total_seconds()) < 5


def test_sync_window_uses_last_successful_sync(db):
    """With a prior successful sync, window starts from its sync_end."""
    sync_end = datetime(2024, 3, 1, 12, 0, 0, tzinfo=UTC)
    log = SyncLog(
        source="whoop",
        sync_type="incremental",
        started_at="2024-03-01T11:00:00+00:00",
        status="success",
        metadata_json=json.dumps({"sync_end": sync_end.isoformat()}),
    )
    db.add(log)
    db.commit()

    pipeline = WhoopPipeline(db, client=MagicMock())
    start, _ = pipeline._get_sync_window()
    assert start == sync_end


def test_sync_window_ignores_failed_syncs(db):
    """A failed sync must not affect the window — falls back to 30 days ago."""
    log = SyncLog(
        source="whoop",
        sync_type="incremental",
        started_at="2024-03-01T11:00:00+00:00",
        status="error",
        metadata_json=json.dumps({"sync_end": "2024-03-01T12:00:00+00:00"}),
    )
    db.add(log)
    db.commit()

    pipeline = WhoopPipeline(db, client=MagicMock())
    start, _ = pipeline._get_sync_window()
    expected = datetime.now(tz=UTC) - timedelta(days=30)
    assert abs((start - expected).total_seconds()) < 5


def test_sync_window_malformed_metadata_falls_back(db):
    """Malformed metadata_json (missing sync_end key) falls back to 30-day default."""
    log = SyncLog(
        source="whoop",
        sync_type="incremental",
        started_at="2024-03-01T11:00:00+00:00",
        status="success",
        metadata_json=json.dumps({"unexpected_key": "value"}),
    )
    db.add(log)
    db.commit()

    pipeline = WhoopPipeline(db, client=MagicMock())
    start, _ = pipeline._get_sync_window()
    expected = datetime.now(tz=UTC) - timedelta(days=30)
    assert abs((start - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Transform: additional edge cases
# ---------------------------------------------------------------------------


def test_transform_sleep_no_cycle_id():
    """Sleep records without a cycle_id should map to None, not raise."""
    record = {**SLEEP}
    del record["cycle_id"]
    result = transform_sleep(record, FETCHED_AT)
    assert result["cycle_id"] is None


def test_transform_workout_partial_zone_dict():
    """A zone_duration dict with only some keys present fills missing zones as None."""
    partial_zones = {**WORKOUT_SCORED}
    partial_zones["score"] = {
        **WORKOUT_SCORED["score"],
        "zone_duration": {"zone_zero_milli": 5000},  # only one key
    }
    result = transform_workout(partial_zones, FETCHED_AT)
    zones = json.loads(result["zone_durations_json"])
    assert zones[0] == 5000
    assert zones[1] is None
    assert zones[5] is None


def test_transform_workout_empty_zone_dict():
    """An empty zone_duration dict (falsy) results in None zone_durations_json."""
    no_zones = {**WORKOUT_SCORED}
    no_zones["score"] = {**WORKOUT_SCORED["score"], "zone_duration": {}}
    result = transform_workout(no_zones, FETCHED_AT)
    assert result["zone_durations_json"] is None


def test_transform_cycle_id_is_stringified():
    """Cycle id from the API is an integer and must be stored as a string PK."""
    result = transform_cycle(CYCLE_SCORED, FETCHED_AT)
    assert isinstance(result["id"], str)
    assert result["id"] == str(CYCLE_SCORED["id"])


# ---------------------------------------------------------------------------
# Store helpers — empty lists
# ---------------------------------------------------------------------------


def test_store_cycles_empty_list_returns_zero(db):
    """Storing an empty list commits nothing and returns 0."""
    pipeline = WhoopPipeline(db, client=MagicMock())
    assert pipeline._store_cycles([], FETCHED_AT) == 0
    assert db.query(WhoopCycle).count() == 0


def test_store_recovery_empty_list_returns_zero(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    assert pipeline._store_recovery([], FETCHED_AT) == 0


def test_store_sleep_empty_list_returns_zero(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    assert pipeline._store_sleep([], FETCHED_AT) == 0


def test_store_workouts_empty_list_returns_zero(db):
    pipeline = WhoopPipeline(db, client=MagicMock())
    assert pipeline._store_workouts([], FETCHED_AT) == 0


# ---------------------------------------------------------------------------
# Upsert — raw_json updated
# ---------------------------------------------------------------------------


def test_upsert_updates_raw_json(db):
    """Re-syncing a record must update raw_json, not preserve the stale blob."""
    pipeline = WhoopPipeline(db, client=MagicMock())
    pipeline._store_cycles([CYCLE_SCORED], FETCHED_AT)

    updated = {**CYCLE_SCORED, "score": {**CYCLE_SCORED["score"], "strain": 55.5}}
    pipeline._store_cycles([updated], FETCHED_AT)

    row = db.get(WhoopCycle, "1344375740")
    stored = json.loads(row.raw_json)
    assert stored["score"]["strain"] == 55.5


# ---------------------------------------------------------------------------
# Sync type: manual vs incremental
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_type_is_manual_with_explicit_dates(db):
    """run() with explicit start/end records sync_type='manual'."""
    mock_client = MagicMock()
    mock_client.get_cycles = AsyncMock(return_value=[])
    mock_client.get_recovery = AsyncMock(return_value=[])
    mock_client.get_sleep = AsyncMock(return_value=[])
    mock_client.get_workouts = AsyncMock(return_value=[])

    pipeline = WhoopPipeline(db, client=mock_client)
    log = await pipeline.run(
        start=datetime(2024, 3, 1, tzinfo=UTC),
        end=datetime(2024, 3, 5, tzinfo=UTC),
    )
    assert log.sync_type == "manual"


@pytest.mark.asyncio
async def test_sync_type_is_incremental_without_dates(db):
    """run() without explicit dates records sync_type='incremental'."""
    mock_client = MagicMock()
    mock_client.get_cycles = AsyncMock(return_value=[])
    mock_client.get_recovery = AsyncMock(return_value=[])
    mock_client.get_sleep = AsyncMock(return_value=[])
    mock_client.get_workouts = AsyncMock(return_value=[])

    pipeline = WhoopPipeline(db, client=mock_client)
    log = await pipeline.run()
    assert log.sync_type == "incremental"
