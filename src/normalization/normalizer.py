"""Normalization engine: populates unified_daily, unified_sleep, unified_workouts.

Reads field mapping decisions from config/field_mappings.yaml and orchestrates
calls to the Whoop and Garmin mapper functions and the deduplication engine.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

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
    local_date,
    map_whoop_daily,
    map_whoop_sleep,
    map_whoop_workout,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAPPINGS_PATH = Path(__file__).parent.parent.parent / "config" / "field_mappings.yaml"


def _date_range(start: date, end: date) -> list[date]:
    """Return every calendar date from start to end inclusive."""
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def upsert_row[M](db: Session, model_cls: type[M], pk_field: str, data: dict[str, Any]) -> M:
    """Insert or update a single row identified by ``data[pk_field]`` (not committed).

    Args:
        db: Active session.
        model_cls: SQLAlchemy ORM class.
        pk_field: Name of the primary key in data.
        data: Column-value mapping to persist.

    Returns:
        The inserted or updated ORM instance.
    """
    row = db.get(model_cls, data[pk_field])
    if row is None:
        row = model_cls(**data)
        db.add(row)
    else:
        for k, v in data.items():
            setattr(row, k, v)
    return row


@dataclass
class PrefetchCache:
    """Batch-prefetched source rows for a date range, keyed for O(1) lookup."""

    cycles_by_date: dict[str, WhoopCycle]
    recoveries_by_cycle: dict[str, WhoopRecovery]
    sleep_by_id: dict[str, WhoopSleep]
    sleep_by_end_date: dict[str, WhoopSleep]
    garmin_daily_by_date: dict[str, GarminDailySummary]
    garmin_sleep_by_date: dict[str, GarminSleep]
    vo2_by_date: dict[str, float]


class Normalizer:
    """Reads source tables and writes to unified_daily, unified_sleep, unified_workouts.

    Usage::

        with Session(engine) as db:
            n = Normalizer(db)
            counts = n.normalize_all(date(2026, 2, 1), date(2026, 3, 4))
            print(counts)
    """

    def __init__(
        self,
        db: Session,
        mappings_path: Path | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initialise the Normalizer.

        Args:
            db: Active SQLAlchemy session for all reads and writes.
            mappings_path: Path to field_mappings.yaml. Defaults to
                config/field_mappings.yaml relative to the project root.
            user_id: App user UUID to tag all unified rows and scope source queries.
        """
        self._db = db
        self.user_id = user_id
        path = mappings_path or _DEFAULT_MAPPINGS_PATH
        self._mappings: dict[str, Any] = yaml.safe_load(path.read_text())

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
        return self._normalize_daily_from_cache(
            target_date, self._prefetch_range(target_date, target_date)
        )

    def normalize_sleep(self, target_date: date) -> int:
        """Upsert one unified_sleep row for the given wake-up date.

        Only non-nap Whoop sleep events are included (nap=0). Garmin sleep is
        supplementary (typically absent since the watch is not worn during sleep).

        Args:
            target_date: The wake-up calendar date (DATE(end_time) for Whoop).

        Returns:
            1 if a row was written, 0 if no data found.
        """
        return self._normalize_sleep_from_cache(
            target_date, self._prefetch_range(target_date, target_date)
        )

    def normalize_workouts(self, start: date, end: date) -> int:
        """Deduplicate and upsert unified_workout rows for the date range.

        Loads Whoop strain workouts (excluding driving) and Garmin activities,
        runs the matching algorithm, and upserts one row per workout.

        Query bounds are UTC and unwidened; row dates are local. A local-``end``
        evening workout (UTC ``end + 1``) is normalized by the next window:
        incremental windows end at the UTC date, which is already the next local
        day after about 19:00 US local, and backfill chunks are contiguous. Its
        matched Garmin activity sits at the same instant, so the pair is always
        normalized together.

        Args:
            start: Range start date (inclusive).
            end: Range end date (inclusive).

        Returns:
            Total number of rows written.
        """
        start_str = start.isoformat()
        end_str = end.isoformat()

        wk_start_ts = start_str + "T00:00:00"
        wk_end_ts = end_str + "T23:59:59"
        whoop_workouts_query = self._db.query(WhoopWorkout).filter(
            WhoopWorkout.start_time >= wk_start_ts,
            WhoopWorkout.start_time <= wk_end_ts,
            WhoopWorkout.strain.isnot(None),
            WhoopWorkout.sport_name != "driving",
        )
        if self.user_id is not None:
            whoop_workouts_query = whoop_workouts_query.filter(WhoopWorkout.user_id == self.user_id)
        whoop_workouts = whoop_workouts_query.all()

        ga_start_ts = start_str + " 00:00:00"
        ga_end_ts = end_str + " 23:59:59"
        garmin_activities_query = self._db.query(GarminActivity).filter(
            GarminActivity.start_time_gmt >= ga_start_ts,
            GarminActivity.start_time_gmt <= ga_end_ts,
        )
        if self.user_id is not None:
            garmin_activities_query = garmin_activities_query.filter(
                GarminActivity.user_id == self.user_id
            )
        garmin_activities = garmin_activities_query.all()

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

                data["matched"] = True
                data["match_confidence"] = result.confidence
                data["primary_source"] = "both"

            data["last_updated"] = now
            data["user_id"] = self.user_id
            self._upsert(UnifiedWorkout, "id", data)
            rows_written += 1

            if result.matched and result.garmin_activity is not None:
                # Garmin may have been normalized alone before this Whoop workout
                # arrived; drop its Garmin-only row so the activity isn't counted twice.
                stale = self._db.get(UnifiedWorkout, f"g_{result.garmin_activity.activity_id}")
                if stale is not None:
                    self._db.delete(stale)

        for garmin in unmatched_garmin:
            data = map_garmin_workout(garmin, self._mappings)
            data["last_updated"] = now
            data["user_id"] = self.user_id
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

    def normalize_all(
        self, start: date, end: date, *, refresh_anomalies: bool = True
    ) -> dict[str, int]:
        """Run all three normalizers over the date range.

        Uses batch-prefetch for daily and sleep to avoid N+1 query patterns.
        Falls back to per-day queries only when batch prefetch is unavailable.

        Args:
            start: Range start date (inclusive).
            end: Range end date (inclusive).
            refresh_anomalies: Recompute the anomaly cache for the range (default).
                The backfill passes False per chunk and refreshes once at the end;
                analytics-cache invalidation stays unconditional.

        Returns:
            Dict with keys "daily", "sleep", "workouts" and row counts.
        """
        counts = {"daily": 0, "sleep": 0, "workouts": 0}

        dates = _date_range(start, end)
        if not dates:
            return counts

        # ── Batch-prefetch all source data for the range ────────────────
        prefetch = self._prefetch_range(start, end)

        for d in dates:
            counts["daily"] += self._normalize_daily_from_cache(d, prefetch)
            counts["sleep"] += self._normalize_sleep_from_cache(d, prefetch)
        counts["workouts"] = self.normalize_workouts(start, end)
        logger.info("normalize_all %s→%s: %s", start, end, counts)

        # Invalidate analytics cache and refresh anomaly store for this user
        if self.user_id is not None:
            try:
                from src.analytics.cache import analytics_cache

                analytics_cache.invalidate_user(self.user_id)
            except Exception:  # noqa: BLE001
                logger.warning("normalize_all: analytics cache invalidation failed", exc_info=True)
            if refresh_anomalies:
                try:
                    from src.analytics.anomaly_store import (
                        refresh_anomalies as _refresh_anomalies,
                    )

                    _refresh_anomalies(self._db.get_bind(), self.user_id, start, end)
                except Exception:  # noqa: BLE001
                    logger.warning("normalize_all: anomaly refresh failed", exc_info=True)

        return counts

    # ------------------------------------------------------------------
    # Batch prefetch — reduces ~210 queries to ~7 for a 30-day range
    # ------------------------------------------------------------------

    def _prefetch_range(self, start: date, end: date) -> PrefetchCache:
        """Fetch all source data for the date range in bulk queries.

        Returns a dict of lookup tables keyed by date string.
        """
        start_str = start.isoformat()
        end_str = end.isoformat()
        # Timestamp bounds: use bare date strings so string comparison works
        # with BOTH "2024-03-05T13:00:00" (Whoop) and "2024-03-05 13:00:00" (Garmin)
        # since "2024-03-05" <= "2024-03-05 ..." and "2024-03-05 ..." < "2024-03-06"
        start_ts = start_str
        end_ts = (end + timedelta(days=1)).isoformat()
        # Whoop timestamps are UTC but keys are local dates, so a local date can sit
        # on the neighbouring UTC date: widen Whoop cycle/sleep bounds by a day each side.
        wk_start_ts = (start - timedelta(days=1)).isoformat()
        wk_end_ts = (end + timedelta(days=2)).isoformat()

        uid = self.user_id

        # 1. Whoop cycles in range
        q = self._db.query(WhoopCycle).filter(
            WhoopCycle.start_time >= wk_start_ts,
            WhoopCycle.start_time < wk_end_ts,
        )
        if uid is not None:
            q = q.filter(WhoopCycle.app_user_id == uid)
        cycles = q.all()
        cycles_by_date: dict[str, WhoopCycle] = {}
        for c in cycles:
            d = local_date(c.start_time, c.timezone_offset) if c.start_time else None
            if d:
                cycles_by_date[d] = c

        # 2. Whoop recoveries for those cycles
        cycle_ids = [c.id for c in cycles]
        recoveries_by_cycle: dict[str, WhoopRecovery] = {}
        if cycle_ids:
            q = self._db.query(WhoopRecovery).filter(WhoopRecovery.cycle_id.in_(cycle_ids))
            if uid is not None:
                q = q.filter(WhoopRecovery.user_id == uid)
            for r in q.all():
                recoveries_by_cycle[r.cycle_id] = r

        # 3. Whoop sleep records keyed by sleep_id (for daily) and by end_date (for sleep norm)
        sleep_ids = [r.sleep_id for r in recoveries_by_cycle.values() if r.sleep_id]
        sleep_by_id: dict[str, WhoopSleep] = {}
        sleep_by_end_date: dict[str, WhoopSleep] = {}
        if sleep_ids:
            for s in self._db.query(WhoopSleep).filter(WhoopSleep.id.in_(sleep_ids)).all():
                sleep_by_id[s.id] = s
        # Also fetch non-nap sleep for sleep normalization
        q = self._db.query(WhoopSleep).filter(
            WhoopSleep.end_time >= wk_start_ts,
            WhoopSleep.end_time < wk_end_ts,
            WhoopSleep.nap.is_(False),
        )
        if uid is not None:
            q = q.filter(WhoopSleep.user_id == uid)
        for s in q.all():
            end_date = local_date(s.end_time, s.timezone_offset) if s.end_time else None
            if end_date:
                sleep_by_end_date[end_date] = s
            sleep_by_id[s.id] = s

        # 4. Garmin daily summaries
        q = self._db.query(GarminDailySummary).filter(
            GarminDailySummary.date >= start_str,
            GarminDailySummary.date <= end_str,
        )
        if uid is not None:
            q = q.filter(GarminDailySummary.user_id == uid)
        garmin_daily_by_date = {g.date: g for g in q.all()}

        # 5. Garmin sleep
        q = self._db.query(GarminSleep).filter(
            GarminSleep.date >= start_str,
            GarminSleep.date <= end_str,
        )
        if uid is not None:
            q = q.filter(GarminSleep.user_id == uid)
        garmin_sleep_by_date = {g.date: g for g in q.all()}

        # 6. VO2 max per date from garmin activities, keyed by LOCAL date.
        # Garmin timestamps use space separator ("2026-03-25 14:30:00"); start_time is
        # startTimeLocal, so its first 10 chars are the local date used for grouping.
        date_expr = func.substr(GarminActivity.start_time, 1, 10)
        # Range filter uses full timestamp comparison (index-friendly);
        # SUBSTR is only used for GROUP BY (not in WHERE).
        q = self._db.query(
            date_expr.label("d"),
            func.max(GarminActivity.vo2_max).label("v"),
        ).filter(
            GarminActivity.start_time >= start_ts,
            GarminActivity.start_time < end_ts,
            GarminActivity.vo2_max.isnot(None),
        )
        if uid is not None:
            q = q.filter(GarminActivity.user_id == uid)
        vo2_by_date = {row.d: row.v for row in q.group_by(date_expr).all()}

        return PrefetchCache(
            cycles_by_date=cycles_by_date,
            recoveries_by_cycle=recoveries_by_cycle,
            sleep_by_id=sleep_by_id,
            sleep_by_end_date=sleep_by_end_date,
            garmin_daily_by_date=garmin_daily_by_date,
            garmin_sleep_by_date=garmin_sleep_by_date,
            vo2_by_date=vo2_by_date,
        )

    def _normalize_daily_from_cache(self, target_date: date, cache: PrefetchCache) -> int:
        """Upsert one unified_daily row using prefetched data."""
        date_str = target_date.isoformat()

        cycle = cache.cycles_by_date.get(date_str)
        recovery: WhoopRecovery | None = None
        sleep: WhoopSleep | None = None
        if cycle:
            recovery = cache.recoveries_by_cycle.get(cycle.id)
            if recovery and recovery.sleep_id:
                sleep = cache.sleep_by_id.get(recovery.sleep_id)

        garmin_summary = cache.garmin_daily_by_date.get(date_str)

        if cycle is None and garmin_summary is None:
            return 0

        data = self._build_daily_row(
            date_str, cycle, recovery, sleep, garmin_summary, cache.vo2_by_date.get(date_str)
        )
        self._upsert(UnifiedDaily, "date", data)
        self._db.commit()
        return 1

    def _normalize_sleep_from_cache(self, target_date: date, cache: PrefetchCache) -> int:
        """Upsert one unified_sleep row using prefetched data."""
        date_str = target_date.isoformat()

        whoop_sleep = cache.sleep_by_end_date.get(date_str)
        garmin_sleep = cache.garmin_sleep_by_date.get(date_str)

        if whoop_sleep is None and garmin_sleep is None:
            return 0

        data = self._build_sleep_row(date_str, whoop_sleep, garmin_sleep)
        self._upsert(UnifiedSleep, "date", data)
        self._db.commit()
        return 1

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_daily_row(
        self,
        date_str: str,
        cycle: WhoopCycle | None,
        recovery: WhoopRecovery | None,
        sleep: WhoopSleep | None,
        garmin_summary: GarminDailySummary | None,
        garmin_vo2_max: float | None,
    ) -> dict[str, Any]:
        """Merge Whoop and Garmin daily sources into one unified_daily row dict.

        Whoop wins; Garmin only fills columns Whoop left unset.  The caller
        guarantees at least one of ``cycle`` / ``garmin_summary`` is present.
        """
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
            data["garmin_vo2_max"] = garmin_vo2_max
            sources.append("garmin")

        data["data_sources"] = json.dumps(sources)
        data["readiness_score"] = None  # reserved
        data["last_updated"] = datetime.now(tz=UTC).isoformat()
        data["user_id"] = self.user_id
        return data

    def _build_sleep_row(
        self,
        date_str: str,
        whoop_sleep: WhoopSleep | None,
        garmin_sleep: GarminSleep | None,
    ) -> dict[str, Any]:
        """Merge Whoop and Garmin sleep into one unified_sleep row dict.

        The caller guarantees at least one source is present.
        """
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
        data["user_id"] = self.user_id
        return data

    def _upsert[M](self, model_cls: type[M], pk_field: str, data: dict[str, Any]) -> M:
        """Insert or update a single row identified by its primary key."""
        return upsert_row(self._db, model_cls, pk_field, data)
