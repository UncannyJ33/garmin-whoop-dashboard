"""Garmin → unified schema transform functions.

All functions are pure (no DB access) and accept ORM model instances.
"""

from src.database.models import GarminActivity, GarminDailySummary, GarminSleep


def seconds_to_minutes(secs: float | None) -> float | None:
    """Convert seconds to minutes.

    Args:
        secs: Duration in seconds, or None.

    Returns:
        Duration in minutes, or None.
    """
    if secs is None:
        return None
    return secs / 60.0


def mps_to_pace(speed_mps: float | None) -> float | None:
    """Convert metres-per-second to min/km running pace.

    Args:
        speed_mps: Speed in m/s, or None.

    Returns:
        Pace in min/km, or None if speed is None or zero.
    """
    if speed_mps is None or speed_mps == 0:
        return None
    return 1000.0 / (speed_mps * 60.0)


def normalize_garmin_sport(activity_type: str | None, mapping: dict) -> str | None:
    """Map a Garmin activity type to the canonical unified schema name.

    Looks up the sport_type_mapping section in field_mappings.yaml.
    Falls back to the original value if no mapping is found.

    Args:
        activity_type: Garmin activity type string (e.g. "indoor_cycling"), or None.
        mapping: Full parsed field_mappings.yaml dict.

    Returns:
        Canonical sport name (e.g. "spin"), or original value.
    """
    if activity_type is None:
        return None
    for canonical, sources in mapping.get("sport_type_mapping", {}).items():
        if isinstance(sources, dict) and sources.get("garmin") == activity_type:
            return canonical
    return activity_type


def map_garmin_daily(summary: GarminDailySummary) -> dict:
    """Build the Garmin-sourced fields for a unified_daily row.

    Note: garmin_vo2_max is not available in the daily summary and is left
    as None. The normalizer may populate it from a separate activity query.

    Args:
        summary: GarminDailySummary ORM instance for the target date.

    Returns:
        Dict of unified_daily column names → values (Garmin fields only).
    """
    return {
        "garmin_body_battery_high": summary.body_battery_high,
        "garmin_body_battery_low": summary.body_battery_low,
        "garmin_avg_stress": summary.avg_stress_level,
        "garmin_total_steps": summary.total_steps,
        "garmin_rhr": summary.resting_heart_rate,
        "garmin_vo2_max": None,  # not in daily summary; populated via activity query
    }


def map_garmin_sleep(sleep: GarminSleep) -> dict:
    """Build the Garmin-sourced fields for a unified_sleep row.

    Args:
        sleep: GarminSleep ORM instance for the target date.

    Returns:
        Dict of unified_sleep column names → values (Garmin fields only).
    """
    return {
        "garmin_sleep_score": sleep.sleep_score,
        "garmin_avg_stress_sleep": sleep.avg_stress_sleep,
        "garmin_avg_spo2_sleep": sleep.avg_spo2_sleep,
    }


def map_garmin_workout(activity: GarminActivity, mapping: dict) -> dict:
    """Build a unified_workout dict from a Garmin-only activity row.

    Duration is taken from garmin_activities.duration_seconds (moving time).
    avg_speed is converted to pace (min/km) for running display.

    Args:
        activity: GarminActivity ORM instance.
        mapping: Full parsed field_mappings.yaml dict.

    Returns:
        Dict of unified_workouts column names → values.
    """
    sport = normalize_garmin_sport(activity.activity_type, mapping)
    date_str = activity.start_time[:10] if activity.start_time else None

    return {
        "id": f"g_{activity.activity_id}",
        "date": date_str,
        "start_time": activity.start_time_gmt,  # UTC for cross-source consistency
        "end_time": None,  # not stored in garmin_activities
        "activity_type": sport,
        "duration_minutes": seconds_to_minutes(activity.duration_seconds),
        "whoop_workout_id": None,
        "whoop_strain": None,
        "whoop_avg_hr": None,
        "whoop_max_hr": None,
        "whoop_calories_kj": None,
        "garmin_activity_id": activity.activity_id,
        "garmin_distance_m": activity.distance_meters,
        "garmin_avg_pace": mps_to_pace(activity.avg_speed),
        "garmin_elevation_gain": activity.elevation_gain,
        "garmin_avg_cadence": activity.avg_running_cadence,
        "garmin_training_effect": activity.training_effect_aerobic,
        "garmin_avg_ground_contact": activity.avg_ground_contact_time,
        "garmin_avg_vertical_osc": activity.avg_vertical_oscillation,
        "garmin_avg_stride_length": activity.avg_stride_length,
        "hr_zone1_minutes": None,
        "hr_zone2_minutes": None,
        "hr_zone3_minutes": None,
        "hr_zone4_minutes": None,
        "hr_zone5_minutes": None,
        "matched": 0,
        "match_confidence": None,
        "primary_source": "garmin",
    }
