"""Garmin data ingestion pipeline.

Fetches activities, daily summaries, sleep, and HRV from the Garmin Connect
API and upserts them into the garmin_* tables.  Each data type is fetched
independently — a broken endpoint skips that type without stopping the sync.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from src.clients.garmin_client import GarminClient
from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminHRV,
    GarminSleep,
    SyncLog,
)

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30

_M = TypeVar("_M")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    """Cast to int, returning None for None inputs."""
    return int(value) if value is not None else None


def _ms_to_iso(ms: int | None) -> str | None:
    """Convert a Unix millisecond timestamp to an ISO 8601 UTC string.

    Args:
        ms: Milliseconds since the Unix epoch, or None.

    Returns:
        ISO 8601 string (e.g. ``"2024-03-05T22:30:00+00:00"``), or None.
    """
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _date_range(start: date, end: date) -> list[date]:
    """Return every calendar date from start to end inclusive.

    Args:
        start: First date in the range.
        end: Last date in the range (inclusive).

    Returns:
        Ordered list of date objects.
    """
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


# ---------------------------------------------------------------------------
# Transform functions (module-level for testability)
# ---------------------------------------------------------------------------


def transform_activity(record: dict, fetched_at: str) -> dict:
    """Map a Garmin activity list entry to garmin_activities column values.

    Running dynamics (ground contact time, stride length, etc.) are available
    directly in the list response — no detail endpoint call is needed.
    ``avg_ground_contact_balance`` is not returned by any known endpoint and
    is stored as NULL.

    Args:
        record: Activity dict from ``garmin.get_activities_by_date()``.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for GarminActivity construction.
    """
    activity_type = record.get("activityType") or {}
    return {
        "activity_id": str(record["activityId"]),
        "activity_type": activity_type.get("typeKey"),
        "activity_name": record.get("activityName"),
        "start_time": record.get("startTimeLocal"),
        "start_time_gmt": record.get("startTimeGMT"),
        "duration_seconds": record.get("duration"),
        "elapsed_seconds": record.get("elapsedDuration"),
        "distance_meters": record.get("distance"),
        "avg_heart_rate": _int(record.get("averageHR")),
        "max_heart_rate": _int(record.get("maxHR")),
        "avg_running_cadence": record.get("averageRunningCadenceInStepsPerMinute"),
        "max_running_cadence": record.get("maxRunningCadenceInStepsPerMinute"),
        "calories": record.get("calories"),
        "avg_speed": record.get("averageSpeed"),
        "max_speed": record.get("maxSpeed"),
        "elevation_gain": record.get("elevationGain"),
        "elevation_loss": record.get("elevationLoss"),
        "avg_stride_length": record.get("avgStrideLength"),
        "vo2_max": record.get("vO2MaxValue"),
        "training_effect_aerobic": record.get("aerobicTrainingEffect"),
        "training_effect_anaerobic": record.get("anaerobicTrainingEffect"),
        "training_load": record.get("activityTrainingLoad"),
        "avg_ground_contact_time": record.get("avgGroundContactTime"),
        "avg_vertical_oscillation": record.get("avgVerticalOscillation"),
        "avg_vertical_ratio": record.get("avgVerticalRatio"),
        "avg_ground_contact_balance": None,  # not available in any endpoint
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_daily_summary(date_str: str, record: dict, fetched_at: str) -> dict:
    """Map the merged Garmin daily summary dict to garmin_daily_summary columns.

    The record is the merged output of get_stats + get_heart_rates +
    get_body_battery + get_stress_data produced by GarminClient.get_daily_summary().

    Args:
        date_str: Calendar date string ``"YYYY-MM-DD"`` used as the primary key.
        record: Merged daily summary dict from ``GarminClient.get_daily_summary()``.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for GarminDailySummary construction.
    """
    return {
        "date": date_str,
        "total_steps": _int(record.get("totalSteps")),
        "total_distance_m": record.get("totalDistanceMeters"),
        "active_calories": record.get("activeKilocalories"),
        "total_calories": record.get("totalKilocalories"),
        "resting_heart_rate": _int(record.get("restingHeartRate")),
        "min_heart_rate": _int(record.get("minHeartRate")),
        "max_heart_rate": _int(record.get("maxHeartRate")),
        "avg_stress_level": _int(record.get("averageStressLevel")),
        "max_stress_level": _int(record.get("maxStressLevel")),
        "body_battery_high": _int(record.get("bodyBatteryHighestValue")),
        "body_battery_low": _int(record.get("bodyBatteryLowestValue")),
        "avg_spo2": record.get("averageSpo2"),
        "lowest_spo2": record.get("lowestSpo2"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_sleep(date_str: str, record: dict, fetched_at: str) -> dict:
    """Map a Garmin sleep response to garmin_sleep column values.

    The watch is rarely worn during sleep (Whoop is used instead), so most
    fields will be NULL in practice.  Sleep timestamps in the API response are
    Unix millisecond integers and are converted to ISO 8601 UTC strings for
    consistency with all other timestamp columns in the schema.

    Args:
        date_str: Calendar date string ``"YYYY-MM-DD"`` used as the primary key.
        record: Sleep dict from ``garmin.get_sleep_data()``.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for GarminSleep construction.
    """
    dto = record.get("dailySleepDTO") or {}
    return {
        "date": date_str,
        "start_time": _ms_to_iso(dto.get("sleepStartTimestampGMT")),
        "end_time": _ms_to_iso(dto.get("sleepEndTimestampGMT")),
        "total_sleep_seconds": dto.get("sleepTimeSeconds"),
        "deep_sleep_seconds": dto.get("deepSleepSeconds"),
        "light_sleep_seconds": dto.get("lightSleepSeconds"),
        "rem_sleep_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        # Fields below only present when watch is worn and scored
        "sleep_score": dto.get("sleepScore"),
        "avg_spo2_sleep": dto.get("averageSpO2Value"),
        "avg_respiration": dto.get("averageRespirationValue"),
        "lowest_respiration": dto.get("lowestRespirationValue"),
        "avg_stress_sleep": dto.get("averageStressLevel"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_hrv(date_str: str, record: dict, fetched_at: str) -> dict:
    """Map a Garmin HRV response to garmin_hrv column values.

    Args:
        date_str: Calendar date string ``"YYYY-MM-DD"`` used as the primary key.
        record: HRV dict from ``garmin.get_hrv_data()``.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for GarminHRV construction.
    """
    summary = record.get("hrvSummary") or {}
    baseline = summary.get("baseline") or {}
    return {
        "date": date_str,
        "weekly_avg_ms": summary.get("weeklyAvg"),
        "last_night_avg_ms": summary.get("lastNight"),
        "last_night_5min_high": summary.get("lastNight5MinHigh"),
        "baseline_low_ms": baseline.get("lowUpper"),
        "baseline_balanced_low": baseline.get("balancedLow"),
        "baseline_balanced_up": baseline.get("balancedUpper"),
        "status": summary.get("status"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class GarminPipeline:
    """Orchestrates fetching, transforming, and storing Garmin data.

    Each data type (activities, daily summary, sleep, HRV) is fetched and
    stored independently.  A None return from any GarminClient method means
    the endpoint is unavailable; the pipeline logs a warning and moves on.

    Usage::

        pipeline = GarminPipeline(db)
        log = pipeline.run()
        print(log.records_stored)
    """

    def __init__(self, db: Session, client: GarminClient | None = None) -> None:
        """Initialise the pipeline.

        Args:
            db: Active SQLAlchemy session used for all reads and writes.
            client: Pre-built GarminClient, useful for injection in tests.
                    Defaults to a new GarminClient.
        """
        self._db = db
        self._client = client or GarminClient()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        start: date | None = None,
        end: date | None = None,
    ) -> SyncLog:
        """Fetch and store Garmin data for the given window.

        Args:
            start: Sync window start date. Defaults to the end date of the
                   last successful garmin sync (or 30 days ago if none exists).
            end: Sync window end date. Defaults to today.

        Returns:
            The completed SyncLog entry.
        """
        auto_start, auto_end = self._get_sync_window()
        sync_start = start or auto_start
        sync_end = end or auto_end
        now = datetime.now(tz=UTC)

        sync_type = "manual" if (start or end) else "incremental"
        log = SyncLog(
            source="garmin",
            sync_type=sync_type,
            started_at=now.isoformat(),
            status="running",
            metadata_json=json.dumps(
                {
                    "sync_start": sync_start.isoformat(),
                    "sync_end": sync_end.isoformat(),
                }
            ),
        )
        self._db.add(log)
        self._db.commit()
        logger.info("Garmin sync started: %s → %s", sync_start, sync_end)

        try:
            fetched_at = datetime.now(tz=UTC).isoformat()
            records_fetched = 0
            records_stored = 0

            # Activities — single batch call for the whole window
            n_fetched, n_stored = self._sync_activities(sync_start, sync_end, fetched_at)
            records_fetched += n_fetched
            records_stored += n_stored

            # Daily data — iterate one day at a time
            for d in _date_range(sync_start, sync_end):
                n_fetched, n_stored = self._sync_daily(d, fetched_at)
                records_fetched += n_fetched
                records_stored += n_stored

            log.records_fetched = records_fetched
            log.records_stored = records_stored
            log.status = "success"
            log.completed_at = datetime.now(tz=UTC).isoformat()
            self._db.commit()
            logger.info(
                "Garmin sync complete — %d fetched, %d stored",
                records_fetched,
                records_stored,
            )

        except Exception as exc:
            log.status = "error"
            log.error_message = str(exc)
            log.completed_at = datetime.now(tz=UTC).isoformat()
            self._db.commit()
            logger.error("Garmin sync failed: %s", exc)
            raise

        return log

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def _get_sync_window(self) -> tuple[date, date]:
        """Return (start, end) dates for the next sync window.

        Start is the ``sync_end`` of the last successful Garmin sync, or
        30 days ago if no prior sync exists.  End is always today.
        """
        last = (
            self._db.query(SyncLog)
            .filter_by(source="garmin", status="success")
            .order_by(SyncLog.id.desc())
            .first()
        )
        today = datetime.now(tz=UTC).date()
        if last and last.metadata_json:
            try:
                meta = json.loads(last.metadata_json)
                start = date.fromisoformat(meta["sync_end"])
                return start, today
            except (KeyError, ValueError):
                pass
        return today - timedelta(days=DEFAULT_LOOKBACK_DAYS), today

    def _sync_activities(
        self, start: date, end: date, fetched_at: str
    ) -> tuple[int, int]:
        """Fetch and upsert all activities in the date range.

        Args:
            start: Range start date.
            end: Range end date.
            fetched_at: ISO 8601 fetch timestamp.

        Returns:
            Tuple of (records_fetched, records_stored).
        """
        logger.info("Fetching activities %s → %s", start, end)
        activities = self._client.get_activities(start, end)
        if not activities:
            logger.info("No activities returned for %s → %s", start, end)
            return 0, 0

        for record in activities:
            data = transform_activity(record, fetched_at)
            self._upsert(GarminActivity, "activity_id", data)
        self._db.commit()

        logger.info("Stored %d activities", len(activities))
        return len(activities), len(activities)

    def _sync_daily(self, d: date, fetched_at: str) -> tuple[int, int]:
        """Fetch and upsert daily summary, sleep, and HRV for a single date.

        Each sub-fetch is independent — a None return skips that data type
        without affecting the others.

        Args:
            d: The calendar date to fetch.
            fetched_at: ISO 8601 fetch timestamp.

        Returns:
            Tuple of (records_fetched, records_stored).
        """
        date_str = d.isoformat()
        fetched = 0
        stored = 0

        # Daily summary
        summary = self._client.get_daily_summary(d)
        if summary:
            data = transform_daily_summary(date_str, summary, fetched_at)
            self._upsert(GarminDailySummary, "date", data)
            self._db.commit()
            fetched += 1
            stored += 1
        else:
            logger.warning("Garmin daily summary unavailable for %s — skipping", date_str)

        # Sleep (expected to be empty most nights — Whoop is worn instead)
        sleep = self._client.get_sleep(d)
        if sleep is not None:
            data = transform_sleep(date_str, sleep, fetched_at)
            self._upsert(GarminSleep, "date", data)
            self._db.commit()
            fetched += 1
            stored += 1
        else:
            logger.debug("Garmin sleep unavailable for %s (expected — watch not worn)", date_str)

        # HRV (expected to be empty most nights)
        hrv = self._client.get_hrv(d)
        if hrv is not None:
            data = transform_hrv(date_str, hrv, fetched_at)
            self._upsert(GarminHRV, "date", data)
            self._db.commit()
            fetched += 1
            stored += 1
        else:
            logger.debug("Garmin HRV unavailable for %s (expected — watch not worn)", date_str)

        return fetched, stored

    # ------------------------------------------------------------------
    # Upsert helper
    # ------------------------------------------------------------------

    def _upsert(self, model_cls: type[_M], pk_field: str, data: dict[str, Any]) -> _M:
        """Insert or update a single row identified by its primary key.

        Args:
            model_cls: The SQLAlchemy ORM class to insert/update.
            pk_field: The name of the primary key column in *data*.
            data: Column-value mapping produced by a transform function.

        Returns:
            The inserted or updated ORM instance (not yet committed).
        """
        pk = data[pk_field]
        row = self._db.get(model_cls, pk)
        if row is None:
            row = model_cls(**data)
            self._db.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
        return row
