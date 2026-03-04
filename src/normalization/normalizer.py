"""Normalization engine: populates unified_daily, unified_sleep, unified_workouts.

Reads field mapping decisions from config/field_mappings.yaml and orchestrates
calls to the Whoop and Garmin mapper functions and the deduplication engine.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.models import (
    GarminActivity,
    GarminDailySummary,
    GarminSleep,
    UnifiedDaily,
    UnifiedSleep,
    UnifiedWorkout,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
    WhoopWorkout,
)
from src.normalization.deduplication import match_workouts
from src.normalization.garmin_mapper import (
    map_garmin_daily,
    map_garmin_sleep,
    map_garmin_workout,
    seconds_to_minutes,
)
from src.normalization.whoop_mapper import (
    map_whoop_daily,
    map_whoop_sleep,
    map_whoop_workout,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAPPINGS_PATH = Path(__file__).parent.parent.parent / "config" / "field_mappings.yaml"

_M = TypeVar("_M")


def _date_range(start: date, end: date) -> list[date]:
    """Return every calendar date from start to end inclusive."""
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


class Normalizer:
    """Reads source tables and writes to unified_daily, unified_sleep, unified_workouts.

    Usage::

        with Session(engine) as db:
            n = Normalizer(db)
            counts = n.normalize_all(date(2026, 2, 1), date(2026, 3, 4))
            print(counts)
    """

    def __init__(self, db: Session, mappings_path: Path | None = None) -> None:
        """Initialise the Normalizer.

        Args:
            db: Active SQLAlchemy session for all reads and writes.
            mappings_path: Path to field_mappings.yaml. Defaults to
                config/field_mappings.yaml relative to the project root.
        """
        self._db = db
        path = mappings_path or _DEFAULT_MAPPINGS_PATH
        self._mappings: dict = yaml.safe_load(path.read_text())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize_daily(self, target_date: date) -> int:
        """Upsert one unified_daily row for the given date.

        Args:
            target_date: The calendar date to normalise.

        Returns:
            1 if a row was written, 0 if neither source had data.
        """
        date_str = target_date.isoformat()

        # --- Whoop data ---
        cycle = (
            self._db.query(WhoopCycle)
            .filter(func.substr(WhoopCycle.start_time, 1, 10) == date_str)
            .first()
        )
        recovery: WhoopRecovery | None = None
        sleep: WhoopSleep | None = None
        if cycle:
            recovery = (
                self._db.query(WhoopRecovery).filter(WhoopRecovery.cycle_id == cycle.id).first()
            )
            if recovery and recovery.sleep_id:
                sleep = self._db.get(WhoopSleep, recovery.sleep_id)

        # --- Garmin data ---
        garmin_summary: GarminDailySummary | None = self._db.get(GarminDailySummary, date_str)

        if cycle is None and garmin_summary is None:
            return 0

        # --- Build unified row ---
        data: dict[str, Any] = {"date": date_str}

        sources: list[str] = []

        if cycle is not None:
            data.update(map_whoop_daily(cycle, recovery, sleep))
            sources.append("whoop")

        if garmin_summary is not None:
            garmin_fields = map_garmin_daily(garmin_summary)
            # Garmin-only columns; never overwrite Whoop-populated fields
            for k, v in garmin_fields.items():
                if k not in data or data[k] is None:
                    data[k] = v
            # garmin_vo2_max: take max VO2 from activities on this date
            data["garmin_vo2_max"] = self._daily_vo2_max(date_str)
            sources.append("garmin")

        data["data_sources"] = json.dumps(sources)
        data["readiness_score"] = None  # reserved
        data["last_updated"] = datetime.now(tz=UTC).isoformat()

        self._upsert(UnifiedDaily, "date", data)
        self._db.commit()
        return 1

    def normalize_sleep(self, target_date: date) -> int:
        """Upsert one unified_sleep row for the given wake-up date.

        Only non-nap Whoop sleep events are included (nap=0). Garmin sleep is
        supplementary (typically absent since the watch is not worn during sleep).

        Args:
            target_date: The wake-up calendar date (DATE(end_time) for Whoop).

        Returns:
            1 if a row was written, 0 if no data found.
        """
        date_str = target_date.isoformat()

        whoop_sleep: WhoopSleep | None = (
            self._db.query(WhoopSleep)
            .filter(
                func.substr(WhoopSleep.end_time, 1, 10) == date_str,
                WhoopSleep.nap == 0,
            )
            .first()
        )

        garmin_sleep: GarminSleep | None = self._db.get(GarminSleep, date_str)

        if whoop_sleep is None and garmin_sleep is None:
            return 0

        data: dict[str, Any] = {"date": date_str}

        if whoop_sleep is not None and garmin_sleep is not None:
            primary_source = "both"
        elif whoop_sleep is not None:
            primary_source = "whoop"
        else:
            primary_source = "garmin"

        if whoop_sleep is not None:
            data.update(map_whoop_sleep(whoop_sleep))

        if garmin_sleep is not None:
            garmin_fields = map_garmin_sleep(garmin_sleep)
            for k, v in garmin_fields.items():
                if k not in data or data[k] is None:
                    data[k] = v

        data["primary_source"] = primary_source
        data["last_updated"] = datetime.now(tz=UTC).isoformat()

        self._upsert(UnifiedSleep, "date", data)
        self._db.commit()
        return 1

    def normalize_workouts(self, start: date, end: date) -> int:
        """Deduplicate and upsert unified_workout rows for the date range.

        Loads Whoop strain workouts (excluding driving) and Garmin activities,
        runs the matching algorithm, and upserts one row per workout.

        Args:
            start: Range start date (inclusive).
            end: Range end date (inclusive).

        Returns:
            Total number of rows written.
        """
        start_str = start.isoformat()
        end_str = end.isoformat()

        whoop_workouts = (
            self._db.query(WhoopWorkout)
            .filter(
                func.substr(WhoopWorkout.start_time, 1, 10) >= start_str,
                func.substr(WhoopWorkout.start_time, 1, 10) <= end_str,
                WhoopWorkout.strain.isnot(None),
                WhoopWorkout.sport_name != "driving",
            )
            .all()
        )

        garmin_activities = (
            self._db.query(GarminActivity)
            .filter(
                func.substr(GarminActivity.start_time_gmt, 1, 10) >= start_str,
                func.substr(GarminActivity.start_time_gmt, 1, 10) <= end_str,
            )
            .all()
        )

        results, unmatched_garmin = match_workouts(whoop_workouts, garmin_activities)

        now = datetime.now(tz=UTC).isoformat()
        rows_written = 0

        for result in results:
            whoop = result.whoop_workout
            data = map_whoop_workout(whoop, self._mappings)

            if result.matched and result.garmin_activity is not None:
                garmin = result.garmin_activity
                garmin_data = map_garmin_workout(garmin, self._mappings)

                # Overlay Garmin-specific fields onto the Whoop base row
                data["garmin_activity_id"] = garmin_data["garmin_activity_id"]
                data["garmin_distance_m"] = garmin_data["garmin_distance_m"]
                data["garmin_avg_pace"] = garmin_data["garmin_avg_pace"]
                data["garmin_elevation_gain"] = garmin_data["garmin_elevation_gain"]
                data["garmin_avg_cadence"] = garmin_data["garmin_avg_cadence"]
                data["garmin_training_effect"] = garmin_data["garmin_training_effect"]
                data["garmin_avg_ground_contact"] = garmin_data["garmin_avg_ground_contact"]
                data["garmin_avg_vertical_osc"] = garmin_data["garmin_avg_vertical_osc"]
                data["garmin_avg_stride_length"] = garmin_data["garmin_avg_stride_length"]

                # Garmin is primary for duration (directly stored, not derived)
                garmin_dur = seconds_to_minutes(garmin.duration_seconds)
                if garmin_dur is not None:
                    data["duration_minutes"] = garmin_dur

                data["matched"] = 1
                data["match_confidence"] = result.confidence
                data["primary_source"] = "both"

            data["last_updated"] = now
            self._upsert(UnifiedWorkout, "id", data)
            rows_written += 1

        for garmin in unmatched_garmin:
            data = map_garmin_workout(garmin, self._mappings)
            data["last_updated"] = now
            self._upsert(UnifiedWorkout, "id", data)
            rows_written += 1

        self._db.commit()
        logger.info(
            "normalize_workouts %s→%s: %d whoop, %d garmin-only, %d total rows",
            start_str,
            end_str,
            len(results),
            len(unmatched_garmin),
            rows_written,
        )
        return rows_written

    def normalize_all(self, start: date, end: date) -> dict[str, int]:
        """Run all three normalizers over the date range.

        Args:
            start: Range start date (inclusive).
            end: Range end date (inclusive).

        Returns:
            Dict with keys "daily", "sleep", "workouts" and row counts.
        """
        counts = {"daily": 0, "sleep": 0, "workouts": 0}
        for d in _date_range(start, end):
            counts["daily"] += self.normalize_daily(d)
            counts["sleep"] += self.normalize_sleep(d)
        counts["workouts"] = self.normalize_workouts(start, end)
        logger.info("normalize_all %s→%s: %s", start, end, counts)
        return counts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _daily_vo2_max(self, date_str: str) -> float | None:
        """Return the max VO2 max from Garmin activities on the given date."""
        rows = (
            self._db.query(GarminActivity.vo2_max)
            .filter(
                func.substr(GarminActivity.start_time_gmt, 1, 10) == date_str,
                GarminActivity.vo2_max.isnot(None),
            )
            .all()
        )
        values = [r[0] for r in rows if r[0] is not None]
        return max(values) if values else None

    def _upsert(self, model_cls: type[_M], pk_field: str, data: dict[str, Any]) -> _M:
        """Insert or update a single row identified by its primary key.

        Args:
            model_cls: SQLAlchemy ORM class.
            pk_field: Name of the primary key in data.
            data: Column-value mapping to persist.

        Returns:
            The inserted or updated ORM instance.
        """
        pk = data[pk_field]
        row = self._db.get(model_cls, pk)
        if row is None:
            row = model_cls(**data)
            self._db.add(row)
        else:
            for k, v in data.items():
                setattr(row, k, v)
        return row
