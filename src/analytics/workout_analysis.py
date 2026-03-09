"""Workout enrichment module.

Combines unified_workouts with garmin_activities (for fields not stored in the
unified schema) and unified_daily (for next-day recovery context) to produce
fully enriched workout records with computed performance insights.

Public API
----------
get_enriched_workout(engine, workout_id)  -> EnrichedWorkout | None
get_enriched_workouts(engine, start, end) -> list[EnrichedWorkout]
get_workout_type_summary(engine, start, end) -> dict[str, dict]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnrichedWorkout:
    """A workout record combining Whoop, Garmin, and computed insights.

    Source priority:
    - Physiological load (strain, HR, zones): Whoop primary, Garmin fallback
    - Performance metrics (distance, pace, dynamics): Garmin primary
    - Combined insights: computed from whichever sources are present

    Fields with unit suffixes (e.g. _ms, _cm, _pct) reflect the unit stored
    by the Garmin API and passed through unchanged.
    """

    # Identity
    id: str  # unified_workouts PK ("w_…" or "g_…")
    date: str  # YYYY-MM-DD (local date)
    start_time: str | None  # ISO 8601 UTC
    activity_type: str | None
    duration_minutes: float | None
    primary_source: str  # "whoop" | "garmin" | "both"
    matched: bool  # True if both devices tracked this session
    garmin_activity_id: str | None  # FK into garmin_activities; used for exercise sets

    # Physiological load — Whoop primary, Garmin fallback for HR
    strain: float | None
    avg_hr: int | None  # Whoop if available, else Garmin
    max_hr: int | None  # Whoop if available, else Garmin
    calories_kj: float | None
    hr_zone_minutes: dict[str, float | None]  # keys "zone1"–"zone5"

    # Performance metrics — Garmin primary
    distance_m: float | None
    avg_pace_min_per_km: float | None
    elevation_gain_m: float | None
    avg_cadence: float | None
    avg_stride_length: float | None
    training_effect_aerobic: float | None
    training_effect_anaerobic: float | None
    training_load: float | None
    vo2_max: float | None

    # Running dynamics — Garmin only
    avg_ground_contact_time_ms: float | None
    avg_vertical_oscillation_cm: float | None
    avg_vertical_ratio_pct: float | None

    # Combined insights — computed
    strain_per_minute: float | None  # strain / duration (intensity proxy)
    efficiency_score: float | None  # distance_m / strain (output per cost)
    next_day_recovery: float | None  # recovery score the morning after
    recovery_impact: float | None  # next_day_recovery − 7-day avg recovery


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _compute_strain_per_minute(
    strain: float | None, duration_minutes: float | None
) -> float | None:
    """Compute strain per minute; None if either input is missing or duration is 0."""
    if strain is None or duration_minutes is None or duration_minutes == 0.0:
        return None
    return strain / duration_minutes


def _compute_efficiency_score(distance_m: float | None, strain: float | None) -> float | None:
    """Compute distance per unit of strain; None if either input is missing or strain is 0."""
    if distance_m is None or strain is None or strain == 0.0:
        return None
    return distance_m / strain


def _compute_recovery_impact(
    next_day_recovery: float | None, seven_day_avg: float | None
) -> float | None:
    """Delta between next-day recovery and baseline 7-day average."""
    if next_day_recovery is None or seven_day_avg is None:
        return None
    return next_day_recovery - seven_day_avg


def _avg_nonull(values: list[float | None]) -> float | None:
    """Mean of non-None values, or None if there are none."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


# ---------------------------------------------------------------------------
# Row → EnrichedWorkout builder
# ---------------------------------------------------------------------------


def _build_enriched(
    row: dict,
    recovery_by_date: dict[str, float | None],
) -> EnrichedWorkout:
    """Convert a raw query row + recovery lookup to an EnrichedWorkout.

    Args:
        row: Dict with all columns from the unified_workouts + garmin join.
        recovery_by_date: Dict mapping ISO date string → whoop_recovery_score.
    """
    workout_date = row["date"]  # YYYY-MM-DD string

    # HR: prefer Whoop, fall back to Garmin
    avg_hr_raw = row["whoop_avg_hr"] if row["whoop_avg_hr"] is not None else row["garmin_avg_hr"]
    max_hr_raw = row["whoop_max_hr"] if row["whoop_max_hr"] is not None else row["garmin_max_hr"]
    avg_hr = int(avg_hr_raw) if avg_hr_raw is not None else None
    max_hr = int(max_hr_raw) if max_hr_raw is not None else None

    hr_zone_minutes: dict[str, float | None] = {
        "zone1": row["hr_zone1_minutes"],
        "zone2": row["hr_zone2_minutes"],
        "zone3": row["hr_zone3_minutes"],
        "zone4": row["hr_zone4_minutes"],
        "zone5": row["hr_zone5_minutes"],
    }

    strain = row["whoop_strain"]
    duration = row["duration_minutes"]
    distance = row["garmin_distance_m"]

    # Recovery context
    next_day_date = _add_days(workout_date, 1)
    next_day_recovery = recovery_by_date.get(next_day_date)

    # 7-day rolling average ending at (and including) the workout date
    seven_day_scores = [recovery_by_date.get(_add_days(workout_date, -i)) for i in range(7)]
    seven_day_avg = _avg_nonull(seven_day_scores)

    strain_per_min = _compute_strain_per_minute(strain, duration)
    efficiency = _compute_efficiency_score(distance, strain)
    recovery_impact = _compute_recovery_impact(next_day_recovery, seven_day_avg)

    return EnrichedWorkout(
        id=row["id"],
        date=workout_date,
        start_time=row["start_time"],
        activity_type=row["activity_type"],
        duration_minutes=duration,
        primary_source=row["primary_source"],
        matched=bool(row["matched"]),
        garmin_activity_id=row["garmin_activity_id"],
        # Physiological load
        strain=strain,
        avg_hr=avg_hr,
        max_hr=max_hr,
        calories_kj=row["whoop_calories_kj"],
        hr_zone_minutes=hr_zone_minutes,
        # Performance metrics
        distance_m=distance,
        avg_pace_min_per_km=row["garmin_avg_pace"],
        elevation_gain_m=row["garmin_elevation_gain"],
        avg_cadence=row["garmin_avg_cadence"],
        avg_stride_length=row["garmin_avg_stride_length"],
        training_effect_aerobic=row["garmin_training_effect"],
        training_effect_anaerobic=row["garmin_training_effect_anaerobic"],
        training_load=row["garmin_training_load"],
        vo2_max=row["garmin_vo2_max"],
        # Running dynamics
        avg_ground_contact_time_ms=row["garmin_avg_ground_contact"],
        avg_vertical_oscillation_cm=row["garmin_avg_vertical_osc"],
        avg_vertical_ratio_pct=row["garmin_avg_vertical_ratio"],
        # Computed insights
        strain_per_minute=strain_per_min,
        efficiency_score=efficiency,
        next_day_recovery=next_day_recovery,
        recovery_impact=recovery_impact,
    )


def _add_days(date_str: str, days: int) -> str:
    """Add `days` to a YYYY-MM-DD string, return YYYY-MM-DD."""
    d = date.fromisoformat(date_str)
    return (d + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

_WORKOUT_COLS = """
    uw.id,
    uw.date,
    uw.start_time,
    uw.activity_type,
    uw.duration_minutes,
    uw.primary_source,
    uw.matched,
    uw.whoop_strain,
    uw.whoop_avg_hr,
    uw.whoop_max_hr,
    uw.whoop_calories_kj,
    uw.hr_zone1_minutes,
    uw.hr_zone2_minutes,
    uw.hr_zone3_minutes,
    uw.hr_zone4_minutes,
    uw.hr_zone5_minutes,
    uw.garmin_activity_id,
    uw.garmin_distance_m,
    uw.garmin_avg_pace,
    uw.garmin_elevation_gain,
    uw.garmin_avg_cadence,
    uw.garmin_avg_stride_length,
    uw.garmin_training_effect,
    uw.garmin_avg_ground_contact,
    uw.garmin_avg_vertical_osc,
    ga.avg_heart_rate     AS garmin_avg_hr,
    ga.max_heart_rate     AS garmin_max_hr,
    ga.training_effect_anaerobic AS garmin_training_effect_anaerobic,
    ga.training_load      AS garmin_training_load,
    ga.vo2_max            AS garmin_vo2_max,
    ga.avg_vertical_ratio AS garmin_avg_vertical_ratio
"""

_WORKOUT_JOIN = """
    FROM unified_workouts uw
    LEFT JOIN garmin_activities ga ON uw.garmin_activity_id = ga.activity_id
"""


def _fetch_recovery_context(
    engine: Engine,
    min_date: str,
    max_date: str,
) -> dict[str, float | None]:
    """Fetch whoop_recovery_score keyed by date for the given range."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT date, whoop_recovery_score
                FROM unified_daily
                WHERE date >= :start AND date <= :end
                """
                ),
                {"start": min_date, "end": max_date},
            )
            .mappings()
            .all()
        )
    return {r["date"]: r["whoop_recovery_score"] for r in rows}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_enriched_workout(
    engine: Engine,
    workout_id: str,
) -> EnrichedWorkout | None:
    """Fetch and enrich a single workout by its unified_workouts ID.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        workout_id: Primary key from unified_workouts (e.g. "w_abc123").

    Returns:
        EnrichedWorkout, or None if the ID does not exist.
    """
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(f"SELECT {_WORKOUT_COLS} {_WORKOUT_JOIN} WHERE uw.id = :id"),  # noqa: S608
                {"id": workout_id},
            )
            .mappings()
            .fetchone()
        )

    if row is None:
        return None

    row_dict = dict(row)
    workout_date = row_dict["date"]

    # Fetch recovery window: 7 days prior for the rolling avg + next day
    context_start = _add_days(workout_date, -6)
    context_end = _add_days(workout_date, 1)
    recovery_by_date = _fetch_recovery_context(engine, context_start, context_end)

    return _build_enriched(row_dict, recovery_by_date)


def get_enriched_workouts(
    engine: Engine,
    start_date: date,
    end_date: date,
) -> list[EnrichedWorkout]:
    """Fetch and enrich all workouts in a date range.

    Uses two batched queries (workouts + recovery) rather than N per-workout
    queries, so it's efficient for chart-sized date ranges.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        start_date: First date to include (inclusive).
        end_date: Last date to include (inclusive).

    Returns:
        List of EnrichedWorkout sorted by start_time ascending.
    """
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    f"""
                SELECT {_WORKOUT_COLS}
                {_WORKOUT_JOIN}
                WHERE uw.date >= :start AND uw.date <= :end
                ORDER BY uw.start_time
                """  # noqa: S608
                ),
                {"start": start_date.isoformat(), "end": end_date.isoformat()},
            )
            .mappings()
            .all()
        )

    if not rows:
        logger.debug("get_enriched_workouts: no workouts for %s → %s", start_date, end_date)
        return []

    # Recovery context: 6 days before earliest workout → 1 day after latest
    context_start = _add_days(start_date.isoformat(), -6)
    context_end = _add_days(end_date.isoformat(), 1)
    recovery_by_date = _fetch_recovery_context(engine, context_start, context_end)

    result = [_build_enriched(dict(r), recovery_by_date) for r in rows]
    logger.debug(
        "get_enriched_workouts: %d workouts enriched for %s → %s",
        len(result),
        start_date,
        end_date,
    )
    return result


def get_workout_type_summary(
    engine: Engine,
    start_date: date,
    end_date: date,
) -> dict[str, dict[str, Any]]:
    """Aggregate enriched workouts by activity type.

    Args:
        engine: SQLAlchemy engine for the fitness database.
        start_date: First date to include (inclusive).
        end_date: Last date to include (inclusive).

    Returns:
        Dict keyed by activity_type (str, or ``"unknown"`` if None).
        Each value is a dict with:
            ``count``, ``avg_duration_minutes``, ``avg_strain``,
            ``avg_distance_m``, ``avg_pace_min_per_km``, ``avg_training_load``,
            ``avg_training_effect_aerobic``, ``avg_next_day_recovery``,
            ``avg_recovery_impact``, ``avg_strain_per_minute``,
            ``avg_efficiency_score``.
        All ``avg_*`` values are float or None if no valid data for that metric.
    """
    workouts = get_enriched_workouts(engine, start_date, end_date)

    # Group by activity_type
    groups: dict[str, list[EnrichedWorkout]] = {}
    for w in workouts:
        key = w.activity_type or "unknown"
        groups.setdefault(key, []).append(w)

    summary: dict[str, dict[str, Any]] = {}
    for activity_type, group in groups.items():
        summary[activity_type] = {
            "count": len(group),
            "avg_duration_minutes": _avg_nonull([w.duration_minutes for w in group]),
            "avg_strain": _avg_nonull([w.strain for w in group]),
            "avg_distance_m": _avg_nonull([w.distance_m for w in group]),
            "avg_pace_min_per_km": _avg_nonull([w.avg_pace_min_per_km for w in group]),
            "avg_training_load": _avg_nonull([w.training_load for w in group]),
            "avg_training_effect_aerobic": _avg_nonull([w.training_effect_aerobic for w in group]),
            "avg_next_day_recovery": _avg_nonull([w.next_day_recovery for w in group]),
            "avg_recovery_impact": _avg_nonull([w.recovery_impact for w in group]),
            "avg_strain_per_minute": _avg_nonull([w.strain_per_minute for w in group]),
            "avg_efficiency_score": _avg_nonull([w.efficiency_score for w in group]),
        }

    return summary
