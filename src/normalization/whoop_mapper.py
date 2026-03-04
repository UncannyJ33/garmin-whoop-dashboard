"""Whoop → unified schema transform functions.

All functions are pure (no DB access) and accept ORM model instances.
"""

import json
import logging
from datetime import datetime

from src.database.models import WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout

logger = logging.getLogger(__name__)


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


def parse_zone_durations(json_str: str | None) -> dict[str, float | None]:
    """Parse Whoop zone_durations_json into per-zone minute values.

    The Whoop API returns a 6-element JSON array [zone0, zone1, zone2, zone3,
    zone4, zone5] where each element is milliseconds. Zone 0 is resting;
    zones 1–5 map to HR zones 1–5.

    Args:
        json_str: JSON array string from whoop_workouts.zone_durations_json, or None.

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
    zones = parse_zone_durations(workout.zone_durations_json)

    duration_minutes: float | None = None
    if workout.start_time and workout.end_time:
        try:
            start = datetime.fromisoformat(workout.start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(workout.end_time.replace("Z", "+00:00"))
            duration_minutes = (end - start).total_seconds() / 60.0
        except ValueError:
            logger.warning("Could not parse workout times for id=%s", workout.id)

    date_str = workout.start_time[:10] if workout.start_time else None

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
        "matched": 0,
        "match_confidence": None,
        "primary_source": "whoop",
    }
