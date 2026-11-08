"""Whoop → unified schema transform functions.

All functions are pure (no DB access) and accept ORM model instances.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta

from src.database.models import WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout

logger = logging.getLogger(__name__)


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def _parse_offset(tz_offset: str | None) -> timedelta:
    """Parse a Whoop ``timezone_offset`` (``+HH:MM``, ``+HHMM`` or ``Z``) to a timedelta.

    Missing offsets fall back to UTC at DEBUG; unparseable ones fall back to
    UTC with a WARNING naming the value.
    """
    if not tz_offset:
        logger.debug("Whoop record has no timezone_offset; using UTC")
        return timedelta(0)
    if tz_offset == "Z":
        return timedelta(0)
    m = _OFFSET_RE.match(tz_offset)
    if m is None:
        logger.warning("Unparseable Whoop timezone_offset %r; using UTC", tz_offset)
        return timedelta(0)
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    return -delta if m.group(1) == "-" else delta


def local_datetime(ts_iso: str, tz_offset: str | None) -> datetime | None:
    """Convert a UTC ISO timestamp to a naive local datetime using a Whoop offset.

    Whoop reports ``timezone_offset`` per record, so DST needs no tz database.
    A sleep spanning a DST switch can be off by one hour at the wake end, which
    only matters for a wake within an hour of midnight.

    Args:
        ts_iso: UTC ISO 8601 string (``Z`` or ``+00:00``, optional fractional seconds).
        tz_offset: Whoop offset such as ``"-05:00"``, ``"+0900"`` or ``"Z"``.

    Returns:
        Naive local datetime, or None when the timestamp cannot be parsed.
    """
    try:
        parsed = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.warning("Could not parse Whoop timestamp %r", ts_iso)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed + _parse_offset(tz_offset)


def local_date(ts_iso: str, tz_offset: str | None) -> str | None:
    """Return the local calendar date (YYYY-MM-DD) of a UTC timestamp, or None."""
    dt = local_datetime(ts_iso, tz_offset)
    return dt.date().isoformat() if dt is not None else None


def cycle_wake_date(
    cycle: WhoopCycle,
    recovery: WhoopRecovery | None,
    sleep: WhoopSleep | None,
) -> str | None:
    """Return the local WAKE date (YYYY-MM-DD) a Whoop cycle belongs to.

    A Whoop cycle starts at sleep onset, so the cycle's own start date can be the
    previous evening. The daily key is the local date of the morning the user woke:

    1. If ``sleep`` (the sleep linked from the cycle's recovery) has an ``end_time``,
       use its local date (sleep offset, falling back to the cycle's offset).
    2. Otherwise use the cycle's local start datetime, plus one day when the local
       hour is >= 12 (onset after noon means the wake day is tomorrow; onset after
       midnight is the same day).

    Returns:
        ISO date string, or None when no timestamp can be parsed.
    """
    if sleep is not None and sleep.end_time:
        d = local_date(sleep.end_time, sleep.timezone_offset or cycle.timezone_offset)
        if d:
            return d
    if not cycle.start_time:
        return None
    dt = local_datetime(cycle.start_time, cycle.timezone_offset)
    if dt is None:
        return None
    if dt.hour >= 12:
        dt = dt + timedelta(days=1)
    return dt.date().isoformat()


def ms_to_minutes(ms: int | None) -> float | None:
    """Convert milliseconds to minutes.

    Args:
        ms: Duration in milliseconds, or None.

    Returns:
        Duration in minutes, or None.
    """
    if ms is None:
        return None
    return ms / 60_000.0


def kj_to_kcal(kj: float | None) -> float | None:
    """Convert kilojoules to kilocalories.

    Args:
        kj: Energy in kilojoules, or None.

    Returns:
        Energy in kilocalories, or None.
    """
    if kj is None:
        return None
    return kj * 0.239


def parse_zone_durations(
    json_str: str | None, workout_id: str | None = None
) -> dict[str, float | None]:
    """Parse Whoop zone_durations_json into per-zone minute values.

    The Whoop API returns a 6-element JSON array [zone0, zone1, zone2, zone3,
    zone4, zone5] where each element is milliseconds. Zone 0 is resting;
    zones 1–5 map to HR zones 1–5.

    Args:
        json_str: JSON array string from whoop_workouts.zone_durations_json, or None.
        workout_id: Optional workout id, used only in the corrupt-JSON warning.

    Returns:
        Dict with keys "zone_1" through "zone_5", each float minutes or None.
    """
    _empty: dict[str, float | None] = {
        "zone_1": None,
        "zone_2": None,
        "zone_3": None,
        "zone_4": None,
        "zone_5": None,
    }
    if json_str is None:
        return _empty
    try:
        zones = json.loads(json_str)
        return {
            "zone_1": ms_to_minutes(zones[1]) if len(zones) > 1 else None,
            "zone_2": ms_to_minutes(zones[2]) if len(zones) > 2 else None,
            "zone_3": ms_to_minutes(zones[3]) if len(zones) > 3 else None,
            "zone_4": ms_to_minutes(zones[4]) if len(zones) > 4 else None,
            "zone_5": ms_to_minutes(zones[5]) if len(zones) > 5 else None,
        }
    except (ValueError, TypeError, AttributeError):
        logger.warning("Corrupt zone_durations JSON for workout %s; zones left empty", workout_id)
        return _empty


def normalize_whoop_sport(sport_name: str | None, mapping: dict) -> str | None:
    """Map a Whoop sport name to the canonical unified schema name.

    Looks up the sport_type_mapping section in field_mappings.yaml to find the
    canonical name for the given Whoop sport. Falls back to the original value
    if no mapping is found.

    Args:
        sport_name: Whoop sport name (e.g. "weightlifting"), or None.
        mapping: Full parsed field_mappings.yaml dict.

    Returns:
        Canonical sport name (e.g. "strength_training"), or original value.
    """
    if sport_name is None:
        return None
    for canonical, sources in mapping.get("sport_type_mapping", {}).items():
        if isinstance(sources, dict) and sources.get("whoop") == sport_name:
            return canonical
    return sport_name


def map_whoop_daily(
    cycle: WhoopCycle,
    recovery: WhoopRecovery | None,
    sleep: WhoopSleep | None = None,
) -> dict:
    """Build the Whoop-sourced fields for a unified_daily row.

    Args:
        cycle: WhoopCycle ORM instance for the target date.
        recovery: WhoopRecovery linked to the cycle, or None if unscored.
        sleep: WhoopSleep linked to the cycle (for respiratory_rate), or None.

    Returns:
        Dict of unified_daily column names → values (Whoop fields only).
    """
    return {
        "whoop_recovery_score": recovery.recovery_score if recovery else None,
        "whoop_strain": cycle.strain,
        "whoop_hrv_rmssd": recovery.hrv_rmssd if recovery else None,
        "whoop_rhr": recovery.resting_heart_rate if recovery else None,
        "whoop_spo2": recovery.spo2_pct if recovery else None,
        "whoop_skin_temp": recovery.skin_temp_celsius if recovery else None,
        "whoop_respiratory_rate": sleep.respiratory_rate if sleep else None,
    }


def map_whoop_sleep(sleep: WhoopSleep) -> dict:
    """Build the Whoop-sourced fields for a unified_sleep row.

    Args:
        sleep: WhoopSleep ORM instance (nap=0) for the target date.

    Returns:
        Dict of unified_sleep column names → values (Whoop fields only).
    """
    return {
        "whoop_performance": sleep.sleep_performance,
        "whoop_consistency": sleep.sleep_consistency,
        "whoop_efficiency": sleep.sleep_efficiency,
        "total_sleep_minutes": ms_to_minutes(sleep.total_in_bed_ms),
        "deep_sleep_minutes": ms_to_minutes(sleep.total_sws_ms),
        "light_sleep_minutes": ms_to_minutes(sleep.total_light_ms),
        "rem_sleep_minutes": ms_to_minutes(sleep.total_rem_ms),
        "awake_minutes": ms_to_minutes(sleep.total_awake_ms),
    }


def map_whoop_workout(workout: WhoopWorkout, mapping: dict) -> dict:
    """Build a unified_workout dict from a Whoop-only workout row.

    Parses zone_durations_json into individual minute columns. Duration is
    computed from start_time and end_time (both ISO 8601 UTC strings).

    Args:
        workout: WhoopWorkout ORM instance.
        mapping: Full parsed field_mappings.yaml dict.

    Returns:
        Dict of unified_workouts column names → values.
    """
    sport = normalize_whoop_sport(workout.sport_name, mapping)
    zones = parse_zone_durations(workout.zone_durations_json, workout.id)

    duration_minutes: float | None = None
    if workout.start_time and workout.end_time:
        try:
            start = datetime.fromisoformat(workout.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(workout.end_time.replace("Z", "+00:00"))
            duration_minutes = (end - start).total_seconds() / 60.0
        except ValueError:
            logger.warning("Could not parse workout times for id=%s", workout.id)

    date_str = (
        local_date(workout.start_time, workout.timezone_offset) if workout.start_time else None
    )

    return {
        "id": f"w_{workout.id}",
        "date": date_str,
        "start_time": workout.start_time,
        "end_time": workout.end_time,
        "activity_type": sport,
        "duration_minutes": duration_minutes,
        "whoop_workout_id": workout.id,
        "whoop_strain": workout.strain,
        "whoop_avg_hr": workout.avg_heart_rate,
        "whoop_max_hr": workout.max_heart_rate,
        "whoop_calories_kj": workout.kilojoules,
        "garmin_activity_id": None,
        "garmin_distance_m": None,
        "garmin_avg_pace": None,
        "garmin_elevation_gain": None,
        "garmin_avg_cadence": None,
        "garmin_training_effect": None,
        "garmin_avg_ground_contact": None,
        "garmin_avg_vertical_osc": None,
        "garmin_avg_stride_length": None,
        "hr_zone1_minutes": zones["zone_1"],
        "hr_zone2_minutes": zones["zone_2"],
        "hr_zone3_minutes": zones["zone_3"],
        "hr_zone4_minutes": zones["zone_4"],
        "hr_zone5_minutes": zones["zone_5"],
        "matched": False,
        "match_confidence": None,
        "primary_source": "whoop",
    }
