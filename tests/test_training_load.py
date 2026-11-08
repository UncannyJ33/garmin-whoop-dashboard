"""Tests for src/analytics/training_load.py.

Isolation strategy
------------------
All tests share one module-scoped in-memory SQLite engine.
Each test class uses a unique, non-overlapping anchor date far in the future
so that no class's data contaminates another's 28-day or 33-day lookback window.

  TestClassifyZone        — pure function, no DB
  TestTrendDirection      — pure function, no DB
  TestSweetSpot           — anchor 2040-01-28 (uniform 10 strain for 28 days)
  TestDetraining          — anchor 2040-03-01 (low recent, high prior)
  TestDanger              — anchor 2040-04-05 (high recent, low prior)
  TestZeroChronic         — anchor 2040-05-10 (no workouts → ACWR None)
  TestPartialHistory      — anchor 2040-06-15 (only 14 days of history)
  TestTrendComputed       — anchor 2040-07-20 (ACWR rising over 7 days)
  TestWeeklyLoads         — anchor 2040-08-25 (4 distinct ISO weeks)
  TestLoadHistory         — anchor 2040-10-01 (series over 7 days)
  TestMultipleWorkouts    — anchor 2040-11-10 (>1 workout per day summed)

All anchors are spaced ≥ 35 days apart to prevent cross-contamination.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.training_load import (
    _acwr_at,
    _classify_zone,
    _fill_zeros,
    _trend_direction,
    _weekly_loads,
    get_training_load_history,
    get_training_load_ratio,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedWorkout

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


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------


def _workout(date_str: str, strain: float, uid: str = "user1") -> UnifiedWorkout:
    return UnifiedWorkout(
        id=f"w_{date_str}_{strain}_{uid}",
        date=date_str,
        start_time=f"{date_str}T08:00:00",
        whoop_strain=strain,
        primary_source="whoop",
        last_updated=NOW_ISO,
        user_id=uid,
    )


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------


class TestClassifyZone:
    def test_detraining(self):
        zone, desc = _classify_zone(0.3)
        assert zone == "detraining"
        assert "significantly less" in desc

    def test_detraining_boundary(self):
        zone, _ = _classify_zone(0.59)
        assert zone == "detraining"

    def test_recovery_low(self):
        zone, _ = _classify_zone(0.6)
        assert zone == "recovery"

    def test_recovery_high(self):
        zone, _ = _classify_zone(0.79)
        assert zone == "recovery"

    def test_sweet_spot_low(self):
        zone, _ = _classify_zone(0.8)
        assert zone == "sweet_spot"

    def test_sweet_spot_mid(self):
        zone, desc = _classify_zone(1.0)
        assert zone == "sweet_spot"
        assert "sustainable" in desc

    def test_sweet_spot_high(self):
        zone, _ = _classify_zone(1.29)
        assert zone == "sweet_spot"

    def test_overreaching_low(self):
        zone, _ = _classify_zone(1.3)
        assert zone == "overreaching"

    def test_overreaching_high(self):
        zone, _ = _classify_zone(1.49)
        assert zone == "overreaching"

    def test_danger(self):
        zone, desc = _classify_zone(1.5)
        assert zone == "danger"
        assert "injury" in desc

    def test_danger_high(self):
        zone, _ = _classify_zone(2.5)
        assert zone == "danger"


class TestTrendDirection:
    def test_stable_flat(self):
        assert _trend_direction([1.0, 1.0, 1.0, 1.0, 1.0]) == "stable"

    def test_increasing(self):
        # 7 values linearly increasing from 0.8 to 1.4
        vals = [0.8 + 0.1 * i for i in range(7)]
        assert _trend_direction(vals) == "increasing"

    def test_decreasing(self):
        vals = [1.4 - 0.1 * i for i in range(7)]
        assert _trend_direction(vals) == "decreasing"

    def test_stable_near_flat(self):
        # Very small slope — should be stable
        vals = [1.0 + 0.00001 * i for i in range(7)]
        assert _trend_direction(vals) == "stable"

    def test_none_values_ignored(self):
        # All None → stable
        assert _trend_direction([None, None, None]) == "stable"

    def test_single_non_none(self):
        assert _trend_direction([None, 1.0, None]) == "stable"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestSweetSpot:
    """Uniform 10 strain per day for 28 days → ACWR ≈ 1.0, sweet_spot."""

    ANCHOR = date(2040, 1, 28)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # Seed 34 days so the full 33-day trend lookback is all 10 strain
            for i in range(34):
                d = (cls.ANCHOR - timedelta(days=33 - i)).isoformat()
                s.merge(_workout(d, 10.0))
            s.commit()

    def test_acwr_near_one(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert result.acwr is not None
        assert math.isclose(result.acwr, 1.0, abs_tol=0.01)

    def test_zone_sweet_spot(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert result.zone == "sweet_spot"

    def test_loads(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert math.isclose(result.acute_load, 70.0, abs_tol=0.1)  # 7 × 10
        assert math.isclose(result.chronic_load, 280.0, abs_tol=0.1)  # 28 × 10

    def test_no_confidence_note(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert result.confidence_note is None

    def test_trend_stable(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert result.trend == "stable"

    def test_weekly_loads_four_weeks(self, engine):
        result = get_training_load_ratio(engine, "user1", self.ANCHOR)
        assert len(result.weekly_loads) == 4
        for wl in result.weekly_loads:
            assert wl.total_strain > 0
            assert wl.workout_count > 0


class TestDetraining:
    """Low acute load (2/day) vs high chronic (10/day) → ACWR ≈ 0.2, detraining."""

    ANCHOR = date(2040, 3, 1)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # Last 7 days: strain 2
            for i in range(7):
                d = (cls.ANCHOR - timedelta(days=6 - i)).isoformat()
                s.merge(_workout(d, 2.0, "user_detr"))
            # Prior 21 days: strain 10
            for i in range(21):
                d = (cls.ANCHOR - timedelta(days=27 - i)).isoformat()
                s.merge(_workout(d, 10.0, "user_detr"))
            s.commit()

    def test_zone_detraining(self, engine):
        result = get_training_load_ratio(engine, "user_detr", self.ANCHOR)
        assert result.zone == "detraining"

    def test_acwr_value(self, engine):
        result = get_training_load_ratio(engine, "user_detr", self.ANCHOR)
        # acute_avg = 14/7 = 2.0; chronic_avg = (14+210)/28 = 224/28 = 8.0
        # ACWR = 2/8 = 0.25
        assert result.acwr is not None
        assert math.isclose(result.acwr, 0.25, abs_tol=0.01)


class TestDanger:
    """High acute (20/day) vs low chronic (5/day prior 21 days) → danger zone."""

    ANCHOR = date(2040, 4, 5)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            for i in range(7):
                d = (cls.ANCHOR - timedelta(days=6 - i)).isoformat()
                s.merge(_workout(d, 20.0, "user_dngr"))
            for i in range(21):
                d = (cls.ANCHOR - timedelta(days=27 - i)).isoformat()
                s.merge(_workout(d, 5.0, "user_dngr"))
            s.commit()

    def test_zone_danger(self, engine):
        result = get_training_load_ratio(engine, "user_dngr", self.ANCHOR)
        assert result.zone == "danger"

    def test_acwr_above_1_5(self, engine):
        result = get_training_load_ratio(engine, "user_dngr", self.ANCHOR)
        # acute_avg = 140/7 = 20; chronic_avg = (140+105)/28 = 245/28 ≈ 8.75
        # ACWR = 20/8.75 ≈ 2.29
        assert result.acwr is not None
        assert result.acwr > 1.5


class TestZeroChronic:
    """No workouts at all → chronic_avg = 0 → ACWR = None."""

    ANCHOR = date(2040, 5, 10)

    def test_acwr_none(self, engine):
        # No data seeded for "user_zero"
        result = get_training_load_ratio(engine, "user_zero", self.ANCHOR)
        assert result.acwr is None
        assert result.zone is None
        assert result.zone_description is None
        assert result.confidence_note is not None
        assert "not available" in result.confidence_note

    def test_loads_zero(self, engine):
        result = get_training_load_ratio(engine, "user_zero", self.ANCHOR)
        assert result.acute_load == 0.0
        assert result.chronic_load == 0.0

    def test_trend_stable_with_no_data(self, engine):
        result = get_training_load_ratio(engine, "user_zero", self.ANCHOR)
        assert result.trend == "stable"


class TestPartialHistory:
    """Only 14 days of data → ACWR computable but confidence note set."""

    ANCHOR = date(2040, 6, 15)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            for i in range(14):
                d = (cls.ANCHOR - timedelta(days=13 - i)).isoformat()
                s.merge(_workout(d, 10.0, "user_part"))
            s.commit()

    def test_acwr_computable(self, engine):
        result = get_training_load_ratio(engine, "user_part", self.ANCHOR)
        # acute_sum = 70 (7×10); chronic_sum = 140 (14×10, rest are 0)
        # acute_avg = 70/7 = 10; chronic_avg = 140/28 = 5.0
        # ACWR = 10/5 = 2.0 → danger
        assert result.acwr is not None
        assert math.isclose(result.acwr, 2.0, abs_tol=0.01)

    def test_confidence_note_set(self, engine):
        result = get_training_load_ratio(engine, "user_part", self.ANCHOR)
        assert result.confidence_note is not None
        assert "14 days" in result.confidence_note


class TestTrendComputed:
    """ACWR increasing over last 7 days → trend = 'increasing'."""

    ANCHOR = date(2040, 7, 20)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # Build a scenario where ACWR rises over the last 7 days:
            # Prior 21 days: constant 5 strain (chronic baseline)
            # Last 7 days: ramp from 5 up to 20 strain
            for i in range(21):
                d = (cls.ANCHOR - timedelta(days=27 - i)).isoformat()
                s.merge(_workout(d, 5.0, "user_trnd"))
            ramp = [5, 7, 9, 12, 15, 18, 20]
            for i, strain in enumerate(ramp):
                d = (cls.ANCHOR - timedelta(days=6 - i)).isoformat()
                s.merge(_workout(d, float(strain), "user_trnd"))
            s.commit()

    def test_trend_increasing(self, engine):
        result = get_training_load_ratio(engine, "user_trnd", self.ANCHOR)
        assert result.trend == "increasing"


class TestWeeklyLoads:
    """4 ISO weeks with known totals appear in weekly_loads."""

    ANCHOR = date(2040, 8, 25)  # Monday

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # Seed 28 days: 4 complete weeks ending on ANCHOR (Sunday 8/25 is day 28)
            # Week 1 (oldest): 7 workouts × 5 strain = 35
            # Week 2: 7 × 8 = 56
            # Week 3: 7 × 10 = 70
            # Week 4 (newest): 7 × 12 = 84
            strains_by_week = [5.0, 8.0, 10.0, 12.0]
            for week_idx, strain in enumerate(strains_by_week):
                for day in range(7):
                    # ANCHOR is the last day (day 27 from start)
                    offset = 27 - (week_idx * 7) - day
                    d = (cls.ANCHOR - timedelta(days=offset)).isoformat()
                    s.merge(_workout(d, strain, "user_wkly"))
            s.commit()

    def test_four_weeks_returned(self, engine):
        result = get_training_load_ratio(engine, "user_wkly", self.ANCHOR)
        assert len(result.weekly_loads) == 4

    def test_weekly_loads_ascending(self, engine):
        result = get_training_load_ratio(engine, "user_wkly", self.ANCHOR)
        dates = [wl.week_start_date for wl in result.weekly_loads]
        assert dates == sorted(dates)

    def test_newest_week_highest_strain(self, engine):
        result = get_training_load_ratio(engine, "user_wkly", self.ANCHOR)
        newest = result.weekly_loads[-1]
        oldest = result.weekly_loads[0]
        assert newest.total_strain > oldest.total_strain

    def test_workout_count_per_week(self, engine):
        result = get_training_load_ratio(engine, "user_wkly", self.ANCHOR)
        # Each week has at least 1 workout (exact count depends on ISO week boundaries)
        for wl in result.weekly_loads:
            assert wl.workout_count >= 1


class TestLoadHistory:
    """get_training_load_history returns one entry per day in [start, end]."""

    ANCHOR = date(2040, 10, 1)
    START = date(2040, 9, 25)  # 7-day history window

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # Seed 34 days so every day in [START, ANCHOR] has a full 28-day window
            for i in range(34):
                d = (cls.ANCHOR - timedelta(days=33 - i)).isoformat()
                s.merge(_workout(d, 10.0, "user_hist"))
            s.commit()

    def test_returns_one_per_day(self, engine):
        result = get_training_load_history(engine, "user_hist", self.START, self.ANCHOR)
        assert len(result) == (self.ANCHOR - self.START).days + 1

    def test_dates_ascending(self, engine):
        result = get_training_load_history(engine, "user_hist", self.START, self.ANCHOR)
        dates = [r["date"] for r in result]
        assert dates == sorted(dates)

    def test_all_sweet_spot(self, engine):
        result = get_training_load_history(engine, "user_hist", self.START, self.ANCHOR)
        for row in result:
            assert row["zone"] == "sweet_spot", (
                f"Expected sweet_spot on {row['date']}, got {row['zone']}"
            )

    def test_acwr_near_one(self, engine):
        result = get_training_load_history(engine, "user_hist", self.START, self.ANCHOR)
        for row in result:
            assert row["acwr"] is not None
            assert math.isclose(row["acwr"], 1.0, abs_tol=0.01)

    def test_no_data_user_returns_none_acwr(self, engine):
        result = get_training_load_history(engine, "user_nodata", self.START, self.ANCHOR)
        assert len(result) == (self.ANCHOR - self.START).days + 1
        for row in result:
            assert row["acwr"] is None


class TestMultipleWorkoutsPerDay:
    """Multiple workouts on the same day — strain should be summed."""

    ANCHOR = date(2040, 11, 10)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as s:
            # 28 days of single 5-strain workouts as baseline
            for i in range(28):
                d = (cls.ANCHOR - timedelta(days=27 - i)).isoformat()
                s.merge(_workout(d, 5.0, "user_multi"))
            # On ANCHOR day: add a second workout (total for that day = 10)
            s.merge(
                UnifiedWorkout(
                    id=f"w_{cls.ANCHOR.isoformat()}_5.0_user_multi_b",
                    date=cls.ANCHOR.isoformat(),
                    start_time=f"{cls.ANCHOR.isoformat()}T10:00:00",
                    whoop_strain=5.0,
                    primary_source="whoop",
                    last_updated=NOW_ISO,
                    user_id="user_multi",
                )
            )
            s.commit()

    def test_strain_summed(self, engine):
        result = get_training_load_ratio(engine, "user_multi", self.ANCHOR)
        # ANCHOR day has 10 strain; prior 6 days have 5 each = 40 total acute
        # acute_avg = (10 + 6*5) / 7 = 40/7 ≈ 5.71
        # chronic_avg = (10 + 27*5) / 28 = (10+135)/28 = 145/28 ≈ 5.18
        # ACWR ≈ 5.71/5.18 ≈ 1.10 → sweet_spot
        assert result.acwr is not None
        assert math.isclose(result.acute_load, 40.0, abs_tol=0.1)
        assert result.zone == "sweet_spot"


# ---------------------------------------------------------------------------
# Unit tests for private helpers
# ---------------------------------------------------------------------------


class TestFillZeros:
    def test_fills_missing_days_with_zero(self):
        raw = {"2040-01-03": 10.0}
        result = _fill_zeros(raw, date(2040, 1, 1), date(2040, 1, 5))
        assert result[0] == ("2040-01-01", 0.0)
        assert result[2] == ("2040-01-03", 10.0)
        assert result[4] == ("2040-01-05", 0.0)
        assert len(result) == 5

    def test_single_day(self):
        raw = {"2040-01-01": 7.5}
        result = _fill_zeros(raw, date(2040, 1, 1), date(2040, 1, 1))
        assert result == [("2040-01-01", 7.5)]


class TestAcwrAt:
    def test_uniform_strain_gives_one(self):
        # 28 days of 10 strain each
        start = date(2040, 1, 1)
        daily = _fill_zeros(
            {(start + timedelta(days=i)).isoformat(): 10.0 for i in range(28)},
            start,
            start + timedelta(days=27),
        )
        acwr = _acwr_at(daily, 27)
        assert acwr is not None
        assert math.isclose(acwr, 1.0, abs_tol=0.001)

    def test_zero_chronic_returns_none(self):
        start = date(2040, 2, 1)
        daily = _fill_zeros({}, start, start + timedelta(days=6))
        acwr = _acwr_at(daily, 6)
        assert acwr is None


class TestWeeklyLoadsHelper:
    def test_returns_up_to_four_weeks(self):
        # Build 28 days of data
        start = date(2040, 3, 4)  # Monday
        daily = _fill_zeros(
            {(start + timedelta(days=i)).isoformat(): float(i + 1) for i in range(28)},
            start,
            start + timedelta(days=27),
        )
        loads = _weekly_loads(daily, 0, 27)
        assert len(loads) == 4

    def test_week_start_dates_are_mondays(self):
        start = date(2040, 3, 4)  # Monday
        daily = _fill_zeros(
            {(start + timedelta(days=i)).isoformat(): 10.0 for i in range(28)},
            start,
            start + timedelta(days=27),
        )
        loads = _weekly_loads(daily, 0, 27)
        for wl in loads:
            d = date.fromisoformat(wl.week_start_date)
            assert d.weekday() == 0, f"{wl.week_start_date} is not a Monday"
