"""Tests for the workout deduplication engine."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.normalization.deduplication import (
    MATCH_DURATION_THRESHOLD_PCT,
    MATCH_START_THRESHOLD_MIN,
    _compute_confidence,
    match_workouts,
)

# ---------------------------------------------------------------------------
# Helpers to build lightweight attribute objects without a real DB session.
# Deduplication only reads .id / .start_time / .end_time / .duration_seconds /
# .activity_id / .start_time_gmt — SimpleNamespace is sufficient.
# ---------------------------------------------------------------------------


def _whoop(
    id: str,
    start_utc: datetime,
    end_utc: datetime,
    sport_name: str = "running",
    strain: float = 10.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        start_time=start_utc.isoformat(),
        end_time=end_utc.isoformat(),
        sport_name=sport_name,
        strain=strain,
        avg_heart_rate=140,
        max_heart_rate=175,
        kilojoules=1200.0,
        zone_durations_json=None,
        cycle_id=None,
    )


def _garmin(
    activity_id: str,
    start_utc: datetime,
    duration_sec: float,
    activity_type: str = "running",
) -> SimpleNamespace:
    return SimpleNamespace(
        activity_id=activity_id,
        start_time_gmt=start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        duration_seconds=duration_sec,
        activity_type=activity_type,
        avg_heart_rate=143,
        max_heart_rate=178,
        avg_speed=2.5,
        distance_meters=4500.0,
        elevation_gain=20.0,
        avg_running_cadence=145.0,
        avg_stride_length=98.0,
        avg_ground_contact_time=265.0,
        avg_vertical_oscillation=7.9,
        avg_vertical_ratio=8.5,
        training_effect_aerobic=3.2,
        vo2_max=None,
        start_time="2026-03-04 07:18:03",
    )


BASE_TIME = datetime(2026, 3, 4, 13, 0, 0, tzinfo=UTC)
DURATION_SEC = 1800.0  # 30 minutes


# ---------------------------------------------------------------------------
# _compute_confidence
# ---------------------------------------------------------------------------


def test_confidence_perfect_match():
    assert _compute_confidence(0.0, 0.0) == pytest.approx(1.0)


def test_confidence_worst_match():
    # Both at their thresholds: score should be small positive (not zero)
    conf = _compute_confidence(MATCH_START_THRESHOLD_MIN, MATCH_DURATION_THRESHOLD_PCT)
    assert conf == pytest.approx(0.0)  # exactly at threshold → 0


def test_confidence_partial():
    # Half-way on time, zero duration diff
    conf = _compute_confidence(MATCH_START_THRESHOLD_MIN / 2, 0.0)
    assert 0.0 < conf < 1.0


# ---------------------------------------------------------------------------
# match_workouts — time window
# ---------------------------------------------------------------------------


def test_match_within_time_window():
    """4-minute gap → match."""
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g = _garmin("g1", BASE_TIME + timedelta(minutes=4), DURATION_SEC)
    results, unmatched = match_workouts([w], [g])
    assert len(results) == 1
    assert results[0].matched is True
    assert results[0].garmin_activity.activity_id == "g1"
    assert unmatched == []


def test_no_match_outside_time_window():
    """6-minute gap → no match."""
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g = _garmin("g1", BASE_TIME + timedelta(minutes=6), DURATION_SEC)
    results, unmatched = match_workouts([w], [g])
    assert results[0].matched is False
    assert results[0].garmin_activity is None
    assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# match_workouts — duration window
# ---------------------------------------------------------------------------


def test_match_within_duration_window():
    """15% duration diff → match (below 20% threshold)."""
    longer = DURATION_SEC * 1.15
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g = _garmin("g1", BASE_TIME, longer)
    results, _ = match_workouts([w], [g])
    assert results[0].matched is True


def test_no_match_outside_duration_window():
    """50% duration diff → no match (above 20% threshold)."""
    # Garmin 1.5× longer: diff/longer = 0.5/1.5 = 0.33 > 0.20
    garmin_dur = DURATION_SEC * 1.5
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g = _garmin("g1", BASE_TIME, garmin_dur)
    results, unmatched = match_workouts([w], [g])
    assert results[0].matched is False
    assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# match_workouts — exclusivity
# ---------------------------------------------------------------------------


def test_garmin_claimed_once():
    """One Garmin activity cannot be claimed by two Whoop workouts."""
    # Two identical Whoop workouts at the same time
    w1 = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    w2 = _whoop("w2", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g = _garmin("g1", BASE_TIME, DURATION_SEC)

    results, unmatched = match_workouts([w1, w2], [g])
    matched = [r for r in results if r.matched]
    unmatched_w = [r for r in results if not r.matched]

    assert len(matched) == 1
    assert len(unmatched_w) == 1
    assert unmatched == []  # Garmin was claimed, not leftover


# ---------------------------------------------------------------------------
# match_workouts — edge cases
# ---------------------------------------------------------------------------


def test_whoop_only_no_garmin():
    """No Garmin activities → all Whoop workouts unmatched."""
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    results, unmatched = match_workouts([w], [])
    assert results[0].matched is False
    assert unmatched == []


def test_garmin_only_no_whoop():
    """No Whoop workouts → all Garmin activities unmatched."""
    g = _garmin("g1", BASE_TIME, DURATION_SEC)
    results, unmatched = match_workouts([], [g])
    assert results == []
    assert len(unmatched) == 1
    assert unmatched[0].activity_id == "g1"


def test_multiple_garmin_best_match_wins():
    """When two Garmin candidates fit, the closer one is chosen."""
    w = _whoop("w1", BASE_TIME, BASE_TIME + timedelta(seconds=DURATION_SEC))
    g_close = _garmin("g_close", BASE_TIME + timedelta(minutes=1), DURATION_SEC)
    g_far = _garmin("g_far", BASE_TIME + timedelta(minutes=4), DURATION_SEC)

    results, unmatched = match_workouts([w], [g_close, g_far])
    assert results[0].matched is True
    assert results[0].garmin_activity.activity_id == "g_close"
    # g_far is unmatched
    assert len(unmatched) == 1
    assert unmatched[0].activity_id == "g_far"
