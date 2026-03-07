"""Tests for src/analytics/workout_analysis.py.

Covers:
- Pure helpers: strain_per_minute, efficiency_score, recovery_impact, avg_nonull
- Single-source workouts: Whoop-only, Garmin-only
- Matched dual-source workouts (Whoop HR preferred over Garmin)
- Computed insights with real recovery data
- get_workout_type_summary: grouping and averages
- Edge cases: missing fields, zero strain/duration, unknown activity type
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.workout_analysis import (
    EnrichedWorkout,
    _avg_nonull,
    _build_enriched,
    _compute_efficiency_score,
    _compute_recovery_impact,
    _compute_strain_per_minute,
    get_enriched_workout,
    get_enriched_workouts,
    get_workout_type_summary,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import (
    GarminActivity,
    UnifiedDaily,
    UnifiedWorkout,
)

IN_MEMORY = "sqlite:///:memory:"
NOW_ISO = datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    db = Session(engine)
    yield db
    db.rollback()
    db.close()


# ---------------------------------------------------------------------------
# DB insert helpers
# ---------------------------------------------------------------------------


def _workout(
    id: str,
    workout_date: str,
    activity_type: str = "running",
    duration_minutes: float = 45.0,
    primary_source: str = "both",
    matched: int = 1,
    whoop_strain: float | None = 14.0,
    whoop_avg_hr: int | None = 155,
    whoop_max_hr: int | None = 178,
    whoop_calories_kj: float | None = 1200.0,
    garmin_activity_id: str | None = None,
    garmin_distance_m: float | None = 8000.0,
    garmin_avg_pace: float | None = 5.0,
    garmin_elevation_gain: float | None = 80.0,
    garmin_avg_cadence: float | None = 170.0,
    garmin_avg_stride_length: float | None = 1.15,
    garmin_training_effect: float | None = 3.5,
    garmin_avg_ground_contact: float | None = 255.0,
    garmin_avg_vertical_osc: float | None = 9.2,
    hr_zone1_minutes: float | None = 5.0,
    hr_zone2_minutes: float | None = 10.0,
    hr_zone3_minutes: float | None = 15.0,
    hr_zone4_minutes: float | None = 12.0,
    hr_zone5_minutes: float | None = 3.0,
) -> UnifiedWorkout:
    return UnifiedWorkout(
        id=id,
        date=workout_date,
        start_time=f"{workout_date}T07:00:00+00:00",
        end_time=f"{workout_date}T07:45:00+00:00",
        activity_type=activity_type,
        duration_minutes=duration_minutes,
        primary_source=primary_source,
        matched=matched,
        whoop_strain=whoop_strain,
        whoop_avg_hr=whoop_avg_hr,
        whoop_max_hr=whoop_max_hr,
        whoop_calories_kj=whoop_calories_kj,
        garmin_activity_id=garmin_activity_id,
        garmin_distance_m=garmin_distance_m,
        garmin_avg_pace=garmin_avg_pace,
        garmin_elevation_gain=garmin_elevation_gain,
        garmin_avg_cadence=garmin_avg_cadence,
        garmin_avg_stride_length=garmin_avg_stride_length,
        garmin_training_effect=garmin_training_effect,
        garmin_avg_ground_contact=garmin_avg_ground_contact,
        garmin_avg_vertical_osc=garmin_avg_vertical_osc,
        hr_zone1_minutes=hr_zone1_minutes,
        hr_zone2_minutes=hr_zone2_minutes,
        hr_zone3_minutes=hr_zone3_minutes,
        hr_zone4_minutes=hr_zone4_minutes,
        hr_zone5_minutes=hr_zone5_minutes,
        last_updated=NOW_ISO,
    )


def _garmin_activity(activity_id: str, **kwargs) -> GarminActivity:
    defaults = dict(
        avg_heart_rate=150,
        max_heart_rate=180,
        training_effect_anaerobic=1.2,
        training_load=75.0,
        vo2_max=52.0,
        avg_vertical_ratio=8.5,
        fetched_at=NOW_ISO,
    )
    defaults.update(kwargs)
    return GarminActivity(activity_id=activity_id, **defaults)


def _daily(date_str: str, recovery: float | None = 72.0) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        data_sources='["whoop"]',
        last_updated=NOW_ISO,
    )


def _add_days(date_str: str, n: int) -> str:
    return (date.fromisoformat(date_str) + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Pure helper unit tests
# ---------------------------------------------------------------------------


class TestComputedMetrics:
    def test_strain_per_minute_normal(self):
        assert _compute_strain_per_minute(14.0, 60.0) == pytest.approx(14 / 60)

    def test_strain_per_minute_none_strain(self):
        assert _compute_strain_per_minute(None, 60.0) is None

    def test_strain_per_minute_none_duration(self):
        assert _compute_strain_per_minute(14.0, None) is None

    def test_strain_per_minute_zero_duration(self):
        assert _compute_strain_per_minute(14.0, 0.0) is None

    def test_efficiency_score_normal(self):
        assert _compute_efficiency_score(8000.0, 14.0) == pytest.approx(8000 / 14)

    def test_efficiency_score_none_distance(self):
        assert _compute_efficiency_score(None, 14.0) is None

    def test_efficiency_score_none_strain(self):
        assert _compute_efficiency_score(8000.0, None) is None

    def test_efficiency_score_zero_strain(self):
        assert _compute_efficiency_score(8000.0, 0.0) is None

    def test_recovery_impact_positive(self):
        # Next-day better than baseline
        assert _compute_recovery_impact(80.0, 70.0) == pytest.approx(10.0)

    def test_recovery_impact_negative(self):
        # Next-day worse than baseline
        assert _compute_recovery_impact(55.0, 70.0) == pytest.approx(-15.0)

    def test_recovery_impact_none_next_day(self):
        assert _compute_recovery_impact(None, 70.0) is None

    def test_recovery_impact_none_avg(self):
        assert _compute_recovery_impact(75.0, None) is None

    def test_avg_nonull_normal(self):
        assert _avg_nonull([10.0, 20.0, 30.0]) == pytest.approx(20.0)

    def test_avg_nonull_ignores_none(self):
        assert _avg_nonull([10.0, None, 30.0]) == pytest.approx(20.0)

    def test_avg_nonull_all_none(self):
        assert _avg_nonull([None, None]) is None

    def test_avg_nonull_empty(self):
        assert _avg_nonull([]) is None


# ---------------------------------------------------------------------------
# _build_enriched — pure builder from dicts
# ---------------------------------------------------------------------------


class TestBuildEnriched:
    BASE_DATE = "2026-02-10"

    def _base_row(self, **overrides) -> dict:
        row = {
            "id": "w_test1",
            "date": self.BASE_DATE,
            "start_time": f"{self.BASE_DATE}T07:00:00+00:00",
            "activity_type": "running",
            "duration_minutes": 45.0,
            "primary_source": "both",
            "matched": 1,
            "whoop_strain": 14.0,
            "whoop_avg_hr": 155,
            "whoop_max_hr": 178,
            "whoop_calories_kj": 1200.0,
            "hr_zone1_minutes": 5.0,
            "hr_zone2_minutes": 10.0,
            "hr_zone3_minutes": 15.0,
            "hr_zone4_minutes": 12.0,
            "hr_zone5_minutes": 3.0,
            "garmin_distance_m": 8000.0,
            "garmin_avg_pace": 5.0,
            "garmin_elevation_gain": 80.0,
            "garmin_avg_cadence": 170.0,
            "garmin_avg_stride_length": 1.15,
            "garmin_training_effect": 3.5,
            "garmin_avg_ground_contact": 255.0,
            "garmin_avg_vertical_osc": 9.2,
            "garmin_avg_hr": 152,
            "garmin_max_hr": 180,
            "garmin_training_effect_anaerobic": 1.2,
            "garmin_training_load": 75.0,
            "garmin_vo2_max": 52.0,
            "garmin_avg_vertical_ratio": 8.5,
        }
        row.update(overrides)
        return row

    def test_returns_enriched_workout(self):
        result = _build_enriched(self._base_row(), {})
        assert isinstance(result, EnrichedWorkout)

    def test_identity_fields(self):
        row = self._base_row()
        result = _build_enriched(row, {})
        assert result.id == "w_test1"
        assert result.date == self.BASE_DATE
        assert result.activity_type == "running"
        assert result.duration_minutes == 45.0
        assert result.matched is True

    def test_whoop_hr_preferred_over_garmin(self):
        # Whoop avg_hr=155, Garmin avg_hr=152 — should use Whoop
        result = _build_enriched(self._base_row(), {})
        assert result.avg_hr == 155
        assert result.max_hr == 178

    def test_garmin_hr_used_as_fallback(self):
        row = self._base_row(whoop_avg_hr=None, whoop_max_hr=None)
        result = _build_enriched(row, {})
        assert result.avg_hr == 152
        assert result.max_hr == 180

    def test_hr_none_when_both_missing(self):
        row = self._base_row(
            whoop_avg_hr=None, whoop_max_hr=None, garmin_avg_hr=None, garmin_max_hr=None
        )
        result = _build_enriched(row, {})
        assert result.avg_hr is None
        assert result.max_hr is None

    def test_hr_zone_minutes_dict_keys(self):
        result = _build_enriched(self._base_row(), {})
        assert set(result.hr_zone_minutes.keys()) == {"zone1", "zone2", "zone3", "zone4", "zone5"}
        assert result.hr_zone_minutes["zone3"] == 15.0

    def test_garmin_fields_populated(self):
        result = _build_enriched(self._base_row(), {})
        assert result.distance_m == 8000.0
        assert result.avg_pace_min_per_km == 5.0
        assert result.avg_cadence == 170.0
        assert result.training_effect_aerobic == 3.5
        assert result.training_effect_anaerobic == 1.2
        assert result.training_load == 75.0
        assert result.vo2_max == 52.0
        assert result.avg_ground_contact_time_ms == 255.0
        assert result.avg_vertical_oscillation_cm == 9.2
        assert result.avg_vertical_ratio_pct == 8.5

    def test_strain_per_minute_computed(self):
        result = _build_enriched(self._base_row(), {})
        assert result.strain_per_minute == pytest.approx(14.0 / 45.0)

    def test_efficiency_score_computed(self):
        result = _build_enriched(self._base_row(), {})
        assert result.efficiency_score == pytest.approx(8000.0 / 14.0)

    def test_next_day_recovery_from_lookup(self):
        next_day = _add_days(self.BASE_DATE, 1)
        result = _build_enriched(self._base_row(), {next_day: 78.0})
        assert result.next_day_recovery == 78.0

    def test_next_day_recovery_none_when_missing(self):
        result = _build_enriched(self._base_row(), {})
        assert result.next_day_recovery is None

    def test_recovery_impact_positive(self):
        # 7-day avg = 70, next day = 82 → impact = +12
        recovery = {_add_days(self.BASE_DATE, -(i)): 70.0 for i in range(7)}
        recovery[_add_days(self.BASE_DATE, 1)] = 82.0
        result = _build_enriched(self._base_row(), recovery)
        assert result.recovery_impact == pytest.approx(12.0, abs=0.1)

    def test_recovery_impact_negative(self):
        # 7-day avg = 75, next day = 55 → impact = -20
        recovery = {_add_days(self.BASE_DATE, -(i)): 75.0 for i in range(7)}
        recovery[_add_days(self.BASE_DATE, 1)] = 55.0
        result = _build_enriched(self._base_row(), recovery)
        assert result.recovery_impact == pytest.approx(-20.0, abs=0.1)

    def test_whoop_only_row_garmin_fields_none(self):
        row = self._base_row(
            primary_source="whoop",
            matched=0,
            garmin_distance_m=None,
            garmin_avg_pace=None,
            garmin_elevation_gain=None,
            garmin_avg_cadence=None,
            garmin_avg_stride_length=None,
            garmin_training_effect=None,
            garmin_avg_ground_contact=None,
            garmin_avg_vertical_osc=None,
            garmin_avg_hr=None,
            garmin_max_hr=None,
            garmin_training_effect_anaerobic=None,
            garmin_training_load=None,
            garmin_vo2_max=None,
            garmin_avg_vertical_ratio=None,
        )
        result = _build_enriched(row, {})
        assert result.primary_source == "whoop"
        assert result.matched is False
        assert result.distance_m is None
        assert result.training_load is None
        assert result.avg_ground_contact_time_ms is None
        # Whoop fields still present
        assert result.strain == 14.0
        assert result.avg_hr == 155

    def test_garmin_only_row_whoop_fields_none(self):
        row = self._base_row(
            primary_source="garmin",
            matched=0,
            whoop_strain=None,
            whoop_avg_hr=None,
            whoop_max_hr=None,
            whoop_calories_kj=None,
            hr_zone1_minutes=None,
            hr_zone2_minutes=None,
            hr_zone3_minutes=None,
            hr_zone4_minutes=None,
            hr_zone5_minutes=None,
        )
        result = _build_enriched(row, {})
        assert result.primary_source == "garmin"
        assert result.strain is None
        assert result.calories_kj is None
        # HR falls back to Garmin
        assert result.avg_hr == 152
        # Garmin performance fields present
        assert result.distance_m == 8000.0


# ---------------------------------------------------------------------------
# DB-backed integration tests
# ---------------------------------------------------------------------------


class TestGetEnrichedWorkout:
    WORKOUT_ID = "w_single1"
    WORKOUT_DATE = "2026-03-10"

    def setup_method(self, engine_not_needed=None):
        pass

    def test_returns_none_for_unknown_id(self, engine):
        result = get_enriched_workout(engine, "w_does_not_exist")
        assert result is None

    def test_returns_enriched_workout(self, engine):
        with Session(engine) as s:
            s.merge(_workout(self.WORKOUT_ID, self.WORKOUT_DATE, garmin_activity_id="g1"))
            s.merge(_garmin_activity("g1"))
            s.commit()
        result = get_enriched_workout(engine, self.WORKOUT_ID)
        assert isinstance(result, EnrichedWorkout)
        assert result.id == self.WORKOUT_ID

    def test_garmin_join_fields_populated(self, engine):
        with Session(engine) as s:
            s.merge(_workout(self.WORKOUT_ID, self.WORKOUT_DATE, garmin_activity_id="g1"))
            s.merge(_garmin_activity("g1", training_load=88.0, vo2_max=54.0))
            s.commit()
        result = get_enriched_workout(engine, self.WORKOUT_ID)
        assert result.training_load == 88.0
        assert result.vo2_max == 54.0

    def test_next_day_recovery_from_db(self, engine):
        next_day = _add_days(self.WORKOUT_DATE, 1)
        with Session(engine) as s:
            s.merge(_workout(self.WORKOUT_ID, self.WORKOUT_DATE, garmin_activity_id="g1"))
            s.merge(_garmin_activity("g1"))
            s.merge(_daily(next_day, recovery=81.0))
            s.commit()
        result = get_enriched_workout(engine, self.WORKOUT_ID)
        assert result.next_day_recovery == 81.0

    def test_recovery_impact_computed_from_db(self, engine):
        next_day = _add_days(self.WORKOUT_DATE, 1)
        with Session(engine) as s:
            # 7-day baseline: all 70
            for i in range(7):
                s.merge(_daily(_add_days(self.WORKOUT_DATE, -i), recovery=70.0))
            # Next-day recovery: 85
            s.merge(_daily(next_day, recovery=85.0))
            s.merge(_workout(self.WORKOUT_ID, self.WORKOUT_DATE, garmin_activity_id="g1"))
            s.merge(_garmin_activity("g1"))
            s.commit()
        result = get_enriched_workout(engine, self.WORKOUT_ID)
        assert result.next_day_recovery == 85.0
        # avg of [70]*7 = 70; 85 - 70 = 15
        assert result.recovery_impact == pytest.approx(15.0, abs=0.5)

    def test_whoop_only_no_garmin_join(self, engine):
        wid = "w_whoop_only"
        wdate = "2026-03-12"
        with Session(engine) as s:
            s.merge(
                _workout(
                    wid,
                    wdate,
                    primary_source="whoop",
                    matched=0,
                    garmin_activity_id=None,
                    garmin_distance_m=None,
                    garmin_avg_pace=None,
                    garmin_elevation_gain=None,
                    garmin_avg_cadence=None,
                    garmin_avg_stride_length=None,
                    garmin_training_effect=None,
                    garmin_avg_ground_contact=None,
                    garmin_avg_vertical_osc=None,
                )
            )
            s.commit()
        result = get_enriched_workout(engine, wid)
        assert result is not None
        assert result.training_load is None
        assert result.vo2_max is None
        assert result.strain == 14.0  # Whoop present
        assert result.avg_hr == 155  # Whoop HR used


class TestGetEnrichedWorkouts:
    START = date(2026, 4, 1)
    END = date(2026, 4, 7)

    def test_returns_list(self, engine):
        results = get_enriched_workouts(engine, self.START, self.END)
        assert isinstance(results, list)

    def test_empty_range_returns_empty(self, engine):
        far_future = date(2099, 1, 1)
        results = get_enriched_workouts(engine, far_future, far_future)
        assert results == []

    def test_returns_workouts_in_range(self, engine):
        d1 = "2026-04-02"
        d2 = "2026-04-05"
        with Session(engine) as s:
            s.merge(_workout("w_r1", d1))
            s.merge(_workout("w_r2", d2, activity_type="strength_training"))
            s.commit()
        results = get_enriched_workouts(engine, self.START, self.END)
        ids = [w.id for w in results]
        assert "w_r1" in ids
        assert "w_r2" in ids

    def test_sorted_by_start_time(self, engine):
        d1 = "2026-04-03"
        d2 = "2026-04-04"
        with Session(engine) as s:
            s.merge(_workout("w_sort1", d1))
            s.merge(_workout("w_sort2", d2))
            s.commit()
        results = get_enriched_workouts(engine, self.START, self.END)
        in_range = [w for w in results if w.id in ("w_sort1", "w_sort2")]
        assert in_range[0].date <= in_range[1].date

    def test_excludes_workouts_outside_range(self, engine):
        outside = "2026-03-25"
        with Session(engine) as s:
            s.merge(_workout("w_outside", outside))
            s.commit()
        results = get_enriched_workouts(engine, self.START, self.END)
        assert not any(w.id == "w_outside" for w in results)

    def test_recovery_context_batched(self, engine):
        """All workouts in the range share one recovery context fetch."""
        d1 = "2026-04-01"
        d2 = "2026-04-02"
        with Session(engine) as s:
            s.merge(_workout("w_batch1", d1))
            s.merge(_workout("w_batch2", d2))
            s.merge(_daily(_add_days(d1, 1), recovery=75.0))
            s.merge(_daily(_add_days(d2, 1), recovery=80.0))
            s.commit()
        results = get_enriched_workouts(engine, self.START, self.END)
        batch1 = next((w for w in results if w.id == "w_batch1"), None)
        batch2 = next((w for w in results if w.id == "w_batch2"), None)
        assert batch1 is not None and batch1.next_day_recovery == 75.0
        assert batch2 is not None and batch2.next_day_recovery == 80.0


class TestGetWorkoutTypeSummary:
    START = date(2026, 5, 1)
    END = date(2026, 5, 14)

    def _populate(self, session):
        """Insert 3 running and 2 strength workouts with known values."""
        runs = [
            ("w_run1", "2026-05-02", 50.0, 15.0, 9000.0),
            ("w_run2", "2026-05-05", 45.0, 13.0, 8000.0),
            ("w_run3", "2026-05-09", 55.0, 16.0, 10000.0),
        ]
        for wid, d, dur, strain, dist in runs:
            session.merge(
                _workout(
                    wid,
                    d,
                    activity_type="running",
                    duration_minutes=dur,
                    whoop_strain=strain,
                    garmin_distance_m=dist,
                )
            )

        strengths = [
            ("w_str1", "2026-05-03", 60.0, 12.0),
            ("w_str2", "2026-05-07", 65.0, 13.0),
        ]
        for wid, d, dur, strain in strengths:
            session.merge(
                _workout(
                    wid,
                    d,
                    activity_type="strength_training",
                    duration_minutes=dur,
                    whoop_strain=strain,
                    garmin_distance_m=None,
                    garmin_avg_pace=None,
                )
            )

        session.commit()

    def test_groups_by_activity_type(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        assert "running" in summary
        assert "strength_training" in summary

    def test_running_count(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        assert summary["running"]["count"] == 3

    def test_strength_count(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        assert summary["strength_training"]["count"] == 2

    def test_running_avg_strain(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        # (15 + 13 + 16) / 3 = 14.67
        assert summary["running"]["avg_strain"] == pytest.approx(44 / 3, abs=0.1)

    def test_running_avg_distance(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        # (9000 + 8000 + 10000) / 3 = 9000
        assert summary["running"]["avg_distance_m"] == pytest.approx(9000.0, abs=0.1)

    def test_strength_avg_distance_none(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        # No distance for strength training
        assert summary["strength_training"]["avg_distance_m"] is None

    def test_all_summary_keys_present(self, engine):
        with Session(engine) as s:
            self._populate(s)
        summary = get_workout_type_summary(engine, self.START, self.END)
        expected_keys = {
            "count",
            "avg_duration_minutes",
            "avg_strain",
            "avg_distance_m",
            "avg_pace_min_per_km",
            "avg_training_load",
            "avg_training_effect_aerobic",
            "avg_next_day_recovery",
            "avg_recovery_impact",
            "avg_strain_per_minute",
            "avg_efficiency_score",
        }
        for atype in ("running", "strength_training"):
            assert expected_keys.issubset(summary[atype].keys()), f"Missing keys in {atype} summary"

    def test_unknown_activity_type_key(self, engine):
        with Session(engine) as s:
            s.merge(_workout("w_none_type", "2026-05-10", activity_type=None))
            s.commit()
        summary = get_workout_type_summary(engine, self.START, self.END)
        assert "unknown" in summary

    def test_empty_range_returns_empty_dict(self, engine):
        far = date(2099, 6, 1)
        summary = get_workout_type_summary(engine, far, far)
        assert summary == {}
