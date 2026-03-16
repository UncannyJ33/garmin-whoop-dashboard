import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from src.clients.whoop_client import WhoopClient
from src.database.models import (
    SyncLog,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
    WhoopWorkout,
)
from src.normalization.normalizer import Normalizer

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30

_M = TypeVar("_M")  # ORM model type variable for _upsert


# ---------------------------------------------------------------------------
# Transform functions (module-level for testability)
# ---------------------------------------------------------------------------


def transform_cycle(record: dict, fetched_at: str) -> dict:
    """Map a Whoop /v2/cycle response dict to whoop_cycles column values.

    Args:
        record: Raw cycle dict from the Whoop API.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for WhoopCycle construction.
    """
    score = record.get("score") or {}
    return {
        "id": str(record["id"]),
        "user_id": record["user_id"],
        "start_time": record["start"],
        "end_time": record.get("end"),
        "timezone_offset": record.get("timezone_offset"),
        "score_state": record.get("score_state"),
        "strain": score.get("strain"),
        "kilojoules": score.get("kilojoule"),
        "avg_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_recovery(record: dict, fetched_at: str) -> dict:
    """Map a Whoop /v2/recovery response dict to whoop_recovery column values.

    The Whoop recovery endpoint does not return an ``id`` field. A stable
    synthetic key is generated from ``cycle_id`` (one recovery per cycle).

    Args:
        record: Raw recovery dict from the Whoop API.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for WhoopRecovery construction.
    """
    score = record.get("score") or {}
    return {
        "id": str(record["cycle_id"]),  # stable synthetic PK
        "cycle_id": str(record["cycle_id"]),
        "sleep_id": record.get("sleep_id"),
        "score_state": record.get("score_state"),
        "recovery_score": score.get("recovery_score"),
        "resting_heart_rate": score.get("resting_heart_rate"),
        "hrv_rmssd": score.get("hrv_rmssd_milli"),
        "spo2_pct": score.get("spo2_percentage"),
        "skin_temp_celsius": score.get("skin_temp_celsius"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_sleep(record: dict, fetched_at: str) -> dict:
    """Map a Whoop /v2/activity/sleep response dict to whoop_sleep column values.

    Args:
        record: Raw sleep dict from the Whoop API.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for WhoopSleep construction.
    """
    score = record.get("score") or {}
    stages = score.get("stage_summary") or {}
    return {
        "id": str(record["id"]),
        "cycle_id": str(record["cycle_id"]) if record.get("cycle_id") else None,
        "start_time": record["start"],
        "end_time": record.get("end"),
        "timezone_offset": record.get("timezone_offset"),
        "nap": bool(record.get("nap") or False),
        "score_state": record.get("score_state"),
        "total_in_bed_ms": stages.get("total_in_bed_time_milli"),
        "total_awake_ms": stages.get("total_awake_time_milli"),
        "total_light_ms": stages.get("total_light_sleep_time_milli"),
        "total_sws_ms": stages.get("total_slow_wave_sleep_time_milli"),
        "total_rem_ms": stages.get("total_rem_sleep_time_milli"),
        "total_no_data_ms": stages.get("total_no_data_time_milli"),
        "sleep_performance": score.get("sleep_performance_percentage"),
        "sleep_consistency": score.get("sleep_consistency_percentage"),
        "sleep_efficiency": score.get("sleep_efficiency_percentage"),
        "respiratory_rate": score.get("respiratory_rate"),
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


def transform_workout(record: dict, fetched_at: str) -> dict:
    """Map a Whoop /v2/activity/workout response dict to whoop_workouts column values.

    Args:
        record: Raw workout dict from the Whoop API.
        fetched_at: ISO 8601 timestamp of when the data was fetched.

    Returns:
        Dict of column name → value ready for WhoopWorkout construction.
    """
    score = record.get("score") or {}
    zones = score.get("zone_duration") or {}
    zone_list = (
        [
            zones.get("zone_zero_milli"),
            zones.get("zone_one_milli"),
            zones.get("zone_two_milli"),
            zones.get("zone_three_milli"),
            zones.get("zone_four_milli"),
            zones.get("zone_five_milli"),
        ]
        if zones
        else None
    )

    return {
        "id": str(record["id"]),
        "cycle_id": str(record["cycle_id"]) if record.get("cycle_id") else None,
        "start_time": record["start"],
        "end_time": record.get("end"),
        "timezone_offset": record.get("timezone_offset"),
        "sport_id": record.get("sport_id"),
        "sport_name": record.get("sport_name"),
        "score_state": record.get("score_state"),
        "strain": score.get("strain"),
        "avg_heart_rate": score.get("average_heart_rate"),
        "max_heart_rate": score.get("max_heart_rate"),
        "kilojoules": score.get("kilojoule"),
        "distance_meter": score.get("distance_meter"),
        "altitude_gain_meter": score.get("altitude_gain_meter"),
        "altitude_change_meter": score.get("altitude_change_meter"),
        "zone_durations_json": json.dumps(zone_list) if zone_list is not None else None,
        "fetched_at": fetched_at,
        "raw_json": json.dumps(record),
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class WhoopPipeline:
    """Orchestrates fetching, transforming, and storing Whoop data.

    Usage::

        pipeline = WhoopPipeline(db)
        log = await pipeline.run()
        print(log.records_stored)
    """

    def __init__(
        self,
        db: Session,
        client: WhoopClient | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initialise the pipeline with a database session and optional API client.

        Args:
            db: Active SQLAlchemy session used for all reads and writes.
            client: Pre-built WhoopClient, useful for injection in tests.
                    Defaults to a new WhoopClient bound to *db*.
            user_id: App user UUID to tag all stored records.
        """
        self._db = db
        self._client = client or WhoopClient(db)
        self.user_id = user_id

    def _get_sync_window(self) -> tuple[datetime, datetime]:
        """Return (start, end) for the next sync window.

        Start is the ``sync_end`` of the last successful sync, or 30 days ago
        if no prior sync exists.
        """
        last = (
            self._db.query(SyncLog)
            .filter_by(source="whoop", status="success")
            .order_by(SyncLog.id.desc())
            .first()
        )
        now = datetime.now(tz=UTC)
        if last and last.metadata_json:
            try:
                meta = json.loads(last.metadata_json)
                start = datetime.fromisoformat(meta["sync_end"])
                return start, now
            except (KeyError, ValueError):
                pass
        return now - timedelta(days=DEFAULT_LOOKBACK_DAYS), now

    async def run(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> SyncLog:
        """Fetch and store Whoop data for the given window.

        Args:
            start: Sync window start. Defaults to end of last successful sync
                   (or 30 days ago if none exists).
            end: Sync window end. Defaults to now.

        Returns:
            The completed SyncLog entry.

        Raises:
            Re-raises any exception from the client after logging the error.
        """
        auto_start, auto_end = self._get_sync_window()
        sync_start = start or auto_start
        sync_end = end or auto_end
        now = datetime.now(tz=UTC)

        sync_type = "manual" if (start or end) else "incremental"
        log = SyncLog(
            source="whoop",
            sync_type=sync_type,
            started_at=now.isoformat(),
            status="running",
            user_id=self.user_id,
            metadata_json=json.dumps(
                {
                    "sync_start": sync_start.isoformat(),
                    "sync_end": sync_end.isoformat(),
                }
            ),
        )
        self._db.add(log)
        self._db.commit()
        logger.info(
            "Whoop sync started: %s → %s",
            sync_start.date(),
            sync_end.date(),
        )

        try:
            fetched_at = datetime.now(tz=UTC).isoformat()

            logger.info("Fetching cycles...")
            cycles = await self._client.get_cycles(sync_start, sync_end)
            logger.info("Fetching recovery...")
            recovery = await self._client.get_recovery(sync_start, sync_end)
            logger.info("Fetching sleep...")
            sleep = await self._client.get_sleep(sync_start, sync_end)
            logger.info("Fetching workouts...")
            workouts = await self._client.get_workouts(sync_start, sync_end)

            records_fetched = len(cycles) + len(recovery) + len(sleep) + len(workouts)
            logger.info(
                "Fetched: %d cycles, %d recovery, %d sleep, %d workouts",
                len(cycles),
                len(recovery),
                len(sleep),
                len(workouts),
            )

            stored = (
                self._store_cycles(cycles, fetched_at)
                + self._store_recovery(recovery, fetched_at)
                + self._store_sleep(sleep, fetched_at)
                + self._store_workouts(workouts, fetched_at)
            )

            log.records_fetched = records_fetched
            log.records_stored = stored
            log.status = "success"
            log.completed_at = datetime.now(tz=UTC).isoformat()
            self._db.commit()
            logger.info("Whoop sync complete — %d fetched, %d stored", records_fetched, stored)

            normalizer = Normalizer(self._db, user_id=self.user_id)
            norm_counts = normalizer.normalize_all(sync_start.date(), sync_end.date())
            logger.info("Normalization complete: %s", norm_counts)

        except Exception as exc:
            logger.error("Whoop sync failed: %s", exc)
            try:
                self._db.rollback()
                log.status = "error"
                log.error_message = str(exc)
                log.completed_at = datetime.now(tz=UTC).isoformat()
                self._db.merge(log)
                self._db.commit()
            except Exception as log_exc:
                logger.error("Failed to update sync_log after error: %s", log_exc)
            raise

        return log

    # ------------------------------------------------------------------
    # Private store helpers — each returns the number of rows upserted
    # ------------------------------------------------------------------

    def _upsert(self, model_cls: type[_M], data: dict[str, Any]) -> _M:
        """Insert or update a single row identified by ``data["id"]``.

        Args:
            model_cls: The SQLAlchemy ORM class to insert/update.
            data: Column-value mapping produced by a transform function.

        Returns:
            The inserted or updated ORM instance (not yet committed).
        """
        pk = data["id"]
        row = self._db.get(model_cls, pk)
        if row is None:
            row = model_cls(**data)
            self._db.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
        return row

    def _store_cycles(self, records: list[dict], fetched_at: str) -> int:
        """Transform and upsert cycle records. Returns number of records processed."""
        for r in records:
            data = transform_cycle(r, fetched_at)
            data["app_user_id"] = self.user_id
            self._upsert(WhoopCycle, data)
        self._db.commit()
        return len(records)

    def _store_recovery(self, records: list[dict], fetched_at: str) -> int:
        """Transform and upsert recovery records. Returns number of records processed."""
        for r in records:
            data = transform_recovery(r, fetched_at)
            data["user_id"] = self.user_id
            self._upsert(WhoopRecovery, data)
        self._db.commit()
        return len(records)

    def _store_sleep(self, records: list[dict], fetched_at: str) -> int:
        """Transform and upsert sleep records. Returns number of records processed."""
        for r in records:
            data = transform_sleep(r, fetched_at)
            data["user_id"] = self.user_id
            self._upsert(WhoopSleep, data)
        self._db.commit()
        return len(records)

    def _store_workouts(self, records: list[dict], fetched_at: str) -> int:
        """Transform and upsert workout records. Returns number of records processed."""
        for r in records:
            data = transform_workout(r, fetched_at)
            data["user_id"] = self.user_id
            self._upsert(WhoopWorkout, data)
        self._db.commit()
        return len(records)
