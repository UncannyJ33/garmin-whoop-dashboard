"""Workout deduplication: match Whoop workouts to Garmin activities.

Uses a time-window + duration-window strategy:
  - UTC start time difference ≤ 5 minutes
  - Duration difference ≤ 20% of the longer activity

Each Garmin activity can only be claimed by one Whoop workout.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from src.database.models import GarminActivity, WhoopWorkout

MATCH_START_THRESHOLD_MIN: float = 5.0
MATCH_DURATION_THRESHOLD_PCT: float = 0.20


@dataclass
class MatchResult:
    """Outcome of attempting to match one Whoop workout to a Garmin activity."""

    whoop_workout: WhoopWorkout
    garmin_activity: GarminActivity | None
    matched: bool
    confidence: float  # 0–1; 0 if unmatched


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp string to a timezone-aware datetime.

    Handles both "Z" suffix and "+00:00" offset formats.

    Args:
        s: ISO 8601 string, or None.

    Returns:
        Aware datetime, or None if input is None or unparseable.
    """
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # Garmin start_time_gmt is stored without timezone marker — treat as UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _compute_confidence(start_diff_min: float, dur_diff_pct: float) -> float:
    """Compute a 0–1 match confidence score.

    Both components are normalised against their thresholds and averaged.
    A perfect match (0 diff on both) yields 1.0; hitting both thresholds
    exactly yields a small positive value.

    Args:
        start_diff_min: Absolute start time difference in minutes.
        dur_diff_pct: Absolute duration difference as a fraction of the longer activity.

    Returns:
        Confidence score in [0, 1].
    """
    time_score = 1.0 - (start_diff_min / MATCH_START_THRESHOLD_MIN)
    dur_score = 1.0 - (dur_diff_pct / MATCH_DURATION_THRESHOLD_PCT)
    return max(0.0, (time_score + dur_score) / 2.0)


def match_workouts(
    whoop_workouts: list[WhoopWorkout],
    garmin_activities: list[GarminActivity],
) -> tuple[list[MatchResult], list[GarminActivity]]:
    """Match each Whoop workout to at most one Garmin activity.

    For each Whoop workout the best candidate Garmin activity is found within
    the time and duration thresholds. Each Garmin activity can be claimed by at
    most one Whoop workout (greedy, best-confidence-first within each Whoop row).

    Args:
        whoop_workouts: Whoop strain workouts for the date range (driving excluded).
        garmin_activities: Garmin activities for the same date range.

    Returns:
        Tuple of:
          - results: One MatchResult per Whoop workout (garmin_activity=None if unmatched).
          - unmatched_garmin: Garmin activities not claimed by any Whoop workout.
    """
    claimed: set[str] = set()
    results: list[MatchResult] = []

    for whoop in whoop_workouts:
        w_start = _parse_dt(whoop.start_time)
        w_end = _parse_dt(whoop.end_time)
        w_dur_sec = (w_end - w_start).total_seconds() if (w_start and w_end) else None

        best_garmin: GarminActivity | None = None
        best_confidence: float = -1.0

        for garmin in garmin_activities:
            if garmin.activity_id in claimed:
                continue

            g_start = _parse_dt(garmin.start_time_gmt)
            if g_start is None or w_start is None:
                continue

            start_diff_min = abs((w_start - g_start).total_seconds()) / 60.0
            if start_diff_min > MATCH_START_THRESHOLD_MIN:
                continue

            g_dur_sec = garmin.duration_seconds
            if w_dur_sec is None or g_dur_sec is None or g_dur_sec == 0:
                continue

            longer = max(w_dur_sec, g_dur_sec)
            dur_diff_pct = abs(w_dur_sec - g_dur_sec) / longer
            if dur_diff_pct > MATCH_DURATION_THRESHOLD_PCT:
                continue

            confidence = _compute_confidence(start_diff_min, dur_diff_pct)
            if confidence > best_confidence:
                best_confidence = confidence
                best_garmin = garmin

        if best_garmin is not None:
            claimed.add(best_garmin.activity_id)
            results.append(
                MatchResult(
                    whoop_workout=whoop,
                    garmin_activity=best_garmin,
                    matched=True,
                    confidence=best_confidence,
                )
            )
        else:
            results.append(
                MatchResult(
                    whoop_workout=whoop,
                    garmin_activity=None,
                    matched=False,
                    confidence=0.0,
                )
            )

    unmatched_garmin = [g for g in garmin_activities if g.activity_id not in claimed]
    return results, unmatched_garmin
