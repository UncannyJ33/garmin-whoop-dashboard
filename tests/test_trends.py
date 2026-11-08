"""Tests for src/analytics/trends.py.

Isolation strategy
------------------
All integration tests share a single module-scoped in-memory SQLite engine.
Each test class that writes data uses a unique, non-overlapping date window:

  TestGetMetricSeries      → recovery, 2029-02 (series) + 2029-07 (gap)
  TestWeeklyRollup         → recovery, 2029-10-07..27
  TestMonthlyRollup        → recovery, 2029-11-01..2029-12-31
  TestGetMetricTrend       → recovery_score + training_load, 2031-01
  TestGetWeeklySummary     → unified_daily/sleep/workouts, 2031-06

TestDetectAnomalies, TestCalculateTrendDirection — pure functions, no DB.

get_metric_series fetches a 27-day lookback window before start_date.
All anchors are spaced ≥ 35 days apart to prevent cross-contamination.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.trends import (
    MetricTrend,
    PeriodRollup,
    _avg_nonull,
    _calendar_fill,
    _metric_source,
    _month_key,
    _std_nonull,
    _week_key,
    _z_score,
    calculate_trend_direction,
    detect_anomalies,
    get_batch_metric_trends,
    get_metric_series,
    get_metric_trend,
    get_monthly_rollup,
    get_weekly_rollup,
    get_weekly_summary,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, UnifiedSleep, UnifiedWorkout

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
# DB helpers
# ---------------------------------------------------------------------------


def _daily(date_str: str, recovery: float | None) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        data_sources='["whoop"]',
        last_updated=NOW_ISO,
    )


# ---------------------------------------------------------------------------
# Pure unit tests — no DB
# ---------------------------------------------------------------------------


class TestAvgNonull:
    def test_normal(self):
        assert _avg_nonull([10.0, 20.0, 30.0]) == pytest.approx(20.0)

    def test_skips_none(self):
        assert _avg_nonull([None, 10.0, None, 30.0]) == pytest.approx(20.0)

    def test_all_none_returns_none(self):
        assert _avg_nonull([None, None]) is None

    def test_empty_returns_none(self):
        assert _avg_nonull([]) is None

    def test_single_value(self):
        assert _avg_nonull([42.0]) == pytest.approx(42.0)


class TestStdNonull:
    def test_known_value(self):
        # sample std of [1, 2, 3] = 1.0 exactly
        assert _std_nonull([1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_all_same_returns_zero(self):
        assert _std_nonull([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_single_value_returns_none(self):
        assert _std_nonull([7.0]) is None

    def test_empty_returns_none(self):
        assert _std_nonull([]) is None

    def test_skips_none_values(self):
        assert _std_nonull([None, 2.0, 4.0, None]) == pytest.approx(math.sqrt(2.0))


class TestZScore:
    def _window(self, n: int = 10, value: float = 5.0) -> list[float | None]:
        return [value] * n

    def test_none_value_returns_none(self):
        assert _z_score(None, self._window()) is None

    def test_insufficient_sample_returns_none(self):
        # 6 non-None values < MIN_ANOMALY_SAMPLE (7)
        assert _z_score(50.0, [70.0] * 6) is None

    def test_exactly_min_sample_not_none(self):
        # 7 non-None values = MIN_ANOMALY_SAMPLE → z_score returned
        assert _z_score(70.0, [70.0] * 7) is not None

    def test_zero_std_returns_zero(self):
        # All identical values → std = 0 → z_score = 0.0
        assert _z_score(70.0, [70.0] * 10) == pytest.approx(0.0)

    def test_positive_z(self):
        # Value above mean → positive z
        window = [0.0] * 9 + [100.0]
        z = _z_score(100.0, window)
        assert z is not None and z > 0

    def test_negative_z(self):
        # Value below mean → negative z
        window = [100.0] * 9 + [0.0]
        z = _z_score(0.0, window)
        assert z is not None and z < 0


class TestWeekKey:
    def test_monday(self):
        d = date(2025, 1, 6)  # known Monday
        label, start = _week_key(d)
        assert start == "2025-01-06"
        assert label.startswith("2025-W")

    def test_wednesday(self):
        d = date(2025, 1, 8)  # Wednesday
        _, start = _week_key(d)
        assert start == "2025-01-06"  # same Monday

    def test_sunday(self):
        d = date(2025, 1, 12)  # Sunday
        _, start = _week_key(d)
        assert start == "2025-01-06"  # still same Monday


class TestMonthKey:
    def test_mid_month(self):
        label, start = _month_key(date(2025, 3, 15))
        assert label == "2025-03"
        assert start == "2025-03-01"

    def test_last_day(self):
        label, start = _month_key(date(2025, 12, 31))
        assert label == "2025-12"
        assert start == "2025-12-01"


class TestCalendarFill:
    def test_no_gaps(self):
        raw = [("2025-01-01", 10.0), ("2025-01-02", 20.0), ("2025-01-03", 30.0)]
        result = _calendar_fill(raw, date(2025, 1, 1), date(2025, 1, 3))
        assert result == [("2025-01-01", 10.0), ("2025-01-02", 20.0), ("2025-01-03", 30.0)]

    def test_gap_filled_with_none(self):
        raw = [("2025-01-01", 10.0), ("2025-01-03", 30.0)]
        result = _calendar_fill(raw, date(2025, 1, 1), date(2025, 1, 3))
        assert result == [("2025-01-01", 10.0), ("2025-01-02", None), ("2025-01-03", 30.0)]

    def test_empty_raw_all_none(self):
        result = _calendar_fill([], date(2025, 1, 1), date(2025, 1, 3))
        assert result == [
            ("2025-01-01", None),
            ("2025-01-02", None),
            ("2025-01-03", None),
        ]


class TestMetricSource:
    def test_valid_metric(self):
        table, col = _metric_source("recovery")
        assert table == "unified_daily"
        assert col == "whoop_recovery_score"

    def test_invalid_metric_raises(self):
        with pytest.raises(ValueError, match="Unknown metric"):
            _metric_source("not_a_real_metric")


# ---------------------------------------------------------------------------
# Integration tests — DB access
# ---------------------------------------------------------------------------


class TestGetMetricSeries:
    """Uses recovery data in 2029-02 (28 days) and 2029-07 (gap days)."""

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            # 28 days of recovery, values 50..77
            for i in range(28):
                d = date(2029, 2, 1) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 50.0 + i))
            # Gap test: only Jul 01, 03, 05 (skip 02, 04)
            for day in (1, 3, 5):
                session.merge(_daily(date(2029, 7, day).isoformat(), 80.0))
            session.commit()

    def _series(self, engine, start, end):
        return get_metric_series(engine, "recovery", start, end)

    def test_returns_one_point_per_calendar_day(self, engine):
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 28))
        assert len(pts) == 28

    def test_dates_span_range(self, engine):
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 28))
        assert pts[0].date == "2029-02-01"
        assert pts[-1].date == "2029-02-28"

    def test_value_matches_inserted_data(self, engine):
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 28))
        assert pts[0].value == pytest.approx(50.0)
        assert pts[6].value == pytest.approx(56.0)

    def test_rolling_7d_correct_on_day_7(self, engine):
        # Feb 01-07 are indices 0-6; rolling_7d on day 7 = avg(50..56) = 53.0
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 7))
        assert pts[6].rolling_7d == pytest.approx(53.0)

    def test_rolling_7d_partial_on_day_1(self, engine):
        # On Feb 01 the 7-day window has at most 1 non-None value (no prior history)
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 1))
        assert pts[0].rolling_7d == pytest.approx(50.0)

    def test_rolling_28d_equals_value_on_first_day_with_no_history(self, engine):
        # Feb 01 is the first data day; rolling_28d = only available value
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 1))
        assert pts[0].rolling_28d == pytest.approx(50.0)

    def test_z_score_none_when_insufficient_history(self, engine):
        # Feb 01 has only 1 non-None value in the 28-day window → z_score is None
        pts = self._series(engine, date(2029, 2, 1), date(2029, 2, 1))
        assert pts[0].z_score is None

    def test_z_score_not_none_with_sufficient_history(self, engine):
        # Feb 07 has 7 non-None values in the window → z_score returned
        pts = self._series(engine, date(2029, 2, 7), date(2029, 2, 7))
        assert pts[0].z_score is not None

    def test_calendar_gap_appears_as_none_value(self, engine):
        # Jul 02 and Jul 04 have no data; they must appear in output with value=None
        pts = self._series(engine, date(2029, 7, 1), date(2029, 7, 5))
        assert len(pts) == 5
        dates = {p.date: p for p in pts}
        assert dates["2029-07-02"].value is None
        assert dates["2029-07-04"].value is None
        assert dates["2029-07-01"].value == pytest.approx(80.0)
        assert dates["2029-07-03"].value == pytest.approx(80.0)
        assert dates["2029-07-05"].value == pytest.approx(80.0)

    def test_rolling_average_skips_none_gaps(self, engine):
        # On Jul 05, the 7-day window contains Jul 01, 03, 05 (all 80) + gaps
        pts = self._series(engine, date(2029, 7, 5), date(2029, 7, 5))
        # rolling_7d = avg of non-None values in window = 80.0
        assert pts[0].rolling_7d == pytest.approx(80.0)

    def test_empty_range_returns_empty(self, engine):
        pts = self._series(engine, date(2029, 9, 1), date(2029, 9, 7))
        # No data in Sep 2029 → all values None; points still returned for each day
        # (7 calendar days, all None)
        assert len(pts) == 7
        assert all(p.value is None for p in pts)

    def test_invalid_metric_raises_value_error(self, engine):
        with pytest.raises(ValueError):
            get_metric_series(engine, "nonexistent", date(2029, 2, 1), date(2029, 2, 7))


class TestDetectAnomalies:
    """Pure function: detect_anomalies(values, dates, window=7, threshold=2.0).

    Test data: 10 days alternating 65/75 (mean≈70, std≈5.2), then a high
    outlier (100) and a low outlier (30).  The 7-day preceding window for
    the outlier days has real variance, so the detection fires.
    """

    # 10 normal days alternating 65/75, then 100, then 30
    _DATES = [(date(2035, 1, 1) + timedelta(days=i)).isoformat() for i in range(12)]
    _NORMAL = [65.0 if i % 2 == 0 else 75.0 for i in range(10)]
    _VALUES: list[float | None] = _NORMAL + [100.0, 30.0]

    def test_high_outlier_detected(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        assert self._DATES[10] in {a["date"] for a in anomalies}

    def test_low_outlier_detected(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        assert self._DATES[11] in {a["date"] for a in anomalies}

    def test_high_direction(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        a = next(x for x in anomalies if x["date"] == self._DATES[10])
        assert a["direction"] == "high"
        assert a["severity"] > 0

    def test_low_direction(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        a = next(x for x in anomalies if x["date"] == self._DATES[11])
        assert a["direction"] == "low"
        assert a["severity"] < 0

    def test_normal_days_not_flagged(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        flagged = {a["date"] for a in anomalies}
        # First 10 normal days (indices 0-9) should not be flagged.
        # The first 7 lack the required prior window; 7-9 have low severity.
        for d in self._DATES[:10]:
            assert d not in flagged

    def test_insufficient_window_skips_early_positions(self):
        # With window=7, positions 0-6 cannot be flagged (fewer than 7 prior values)
        anomalies = detect_anomalies(self._VALUES, self._DATES, window=7)
        flagged = {a["date"] for a in anomalies}
        for d in self._DATES[:7]:
            assert d not in flagged

    def test_custom_threshold_suppresses_outlier(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES, threshold=10.0)
        assert anomalies == []

    def test_returns_list_of_dicts(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        assert all(isinstance(a, dict) for a in anomalies)

    def test_dict_has_required_keys(self):
        anomalies = detect_anomalies(self._VALUES, self._DATES)
        for a in anomalies:
            assert set(a.keys()) == {"date", "value", "direction", "severity"}

    def test_all_none_returns_empty(self):
        nones: list[float | None] = [None] * 12
        assert detect_anomalies(nones, self._DATES) == []

    def test_zero_std_not_flagged(self):
        # All same values → std=0 → nothing flagged
        same: list[float | None] = [70.0] * 12
        assert detect_anomalies(same, self._DATES) == []

    def test_window_parameter_respected(self):
        # window=3: need only 3 prior values, so position 3 onward is eligible
        anomalies = detect_anomalies(self._VALUES, self._DATES, window=3)
        flagged = {a["date"] for a in anomalies}
        # Positions 0-2 must still be skipped (fewer than 3 prior values)
        for d in self._DATES[:3]:
            assert d not in flagged


class TestWeeklyRollup:
    """Uses recovery data in 2029-10-08 through 2029-10-28 (3 full ISO weeks).

    Oct 08 2029 is the Monday that starts W41.  Three consecutive weeks:
      W41: Oct 08-14, values 70..76
      W42: Oct 15-21, values all 80
      W43: Oct 22-28, values all 90
    """

    # These are computed dynamically from _week_key to avoid hard-coding ISO numbers.
    _START = date(2029, 10, 8)  # Monday of W41
    _END = date(2029, 10, 28)  # Sunday of W43

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            for i in range(7):
                d = cls._START + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 70.0 + i))
            for i in range(7):
                d = date(2029, 10, 15) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 80.0))
            for i in range(7):
                d = date(2029, 10, 22) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 90.0))
            session.commit()

    def _rollup(self, engine):
        return get_weekly_rollup(engine, "recovery", self._START, self._END)

    def test_returns_three_weeks(self, engine):
        assert len(self._rollup(engine)) == 3

    def test_period_labels_sorted(self, engine):
        labels = [r.period for r in self._rollup(engine)]
        assert labels == sorted(labels)

    def test_period_start_is_monday(self, engine):
        for r in self._rollup(engine):
            d = date.fromisoformat(r.period_start)
            assert d.weekday() == 0  # 0 = Monday

    def test_count_per_week(self, engine):
        for r in self._rollup(engine):
            assert r.count == 7

    def test_week1_avg(self, engine):
        w1 = self._rollup(engine)[0]
        # W41: Oct 08-14, values 70,71,...,76 → avg = 73.0
        assert w1.avg == pytest.approx(sum(range(70, 77)) / 7)

    def test_week1_min_max(self, engine):
        w1 = self._rollup(engine)[0]
        assert w1.min == pytest.approx(70.0)
        assert w1.max == pytest.approx(76.0)

    def test_uniform_week_std_zero(self, engine):
        # W42 (all 80) and W43 (all 90) → std = 0.0
        rollups = self._rollup(engine)
        assert rollups[1].std == pytest.approx(0.0)
        assert rollups[2].std == pytest.approx(0.0)

    def test_returns_period_rollup_instances(self, engine):
        assert all(isinstance(r, PeriodRollup) for r in self._rollup(engine))


class TestMonthlyRollup:
    """Uses recovery data for 2029-11 (all=60) and 2029-12 (all=70)."""

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            # November: 30 days at 60
            for i in range(30):
                d = date(2029, 11, 1) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 60.0))
            # December: 31 days at 70
            for i in range(31):
                d = date(2029, 12, 1) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 70.0))
            session.commit()

    def _rollup(self, engine):
        return get_monthly_rollup(engine, "recovery", date(2029, 11, 1), date(2029, 12, 31))

    def test_returns_two_months(self, engine):
        assert len(self._rollup(engine)) == 2

    def test_period_labels(self, engine):
        labels = [r.period for r in self._rollup(engine)]
        assert labels == ["2029-11", "2029-12"]

    def test_period_start_first_of_month(self, engine):
        rollups = self._rollup(engine)
        assert rollups[0].period_start == "2029-11-01"
        assert rollups[1].period_start == "2029-12-01"

    def test_count_matches_days_in_month(self, engine):
        rollups = self._rollup(engine)
        assert rollups[0].count == 30  # November
        assert rollups[1].count == 31  # December

    def test_avg_correct(self, engine):
        rollups = self._rollup(engine)
        assert rollups[0].avg == pytest.approx(60.0)
        assert rollups[1].avg == pytest.approx(70.0)

    def test_min_max_correct(self, engine):
        rollups = self._rollup(engine)
        for r in rollups:
            assert r.min == r.avg  # uniform data
            assert r.max == r.avg

    def test_uniform_std_zero(self, engine):
        for r in self._rollup(engine):
            assert r.std == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# New: pure function tests — no DB
# ---------------------------------------------------------------------------


class TestCalculateTrendDirection:
    """calculate_trend_direction(rolling_avg, window=7) -> str."""

    def test_strictly_increasing_is_improving(self):
        # Values rising 1 unit/day from 50; mean≈53, slope=1, relative≈0.019 > 0.002
        avgs = [50.0 + i for i in range(7)]
        assert calculate_trend_direction(avgs) == "improving"

    def test_strictly_decreasing_is_declining(self):
        avgs = [80.0 - i for i in range(7)]
        assert calculate_trend_direction(avgs) == "declining"

    def test_flat_is_stable(self):
        avgs = [70.0] * 7
        assert calculate_trend_direction(avgs) == "stable"

    def test_tiny_slope_is_stable(self):
        # Slope of 0.001/day, mean 70 → relative ≈ 0.000014 < threshold
        avgs = [70.0 + i * 0.001 for i in range(7)]
        assert calculate_trend_direction(avgs) == "stable"

    def test_single_value_is_stable(self):
        assert calculate_trend_direction([70.0]) == "stable"

    def test_all_none_is_stable(self):
        avgs: list[float | None] = [None] * 7
        assert calculate_trend_direction(avgs) == "stable"

    def test_uses_last_window_values(self):
        # Prepend declining values; last 7 are sharply increasing → improving
        prefix = [100.0 - i for i in range(10)]
        suffix = [50.0 + i * 2 for i in range(7)]  # slope=2, mean≈56, rel≈0.036
        assert calculate_trend_direction(prefix + suffix) == "improving"

    def test_none_values_skipped(self):
        # Mix Nones into a clearly increasing series
        avgs: list[float | None] = [None, 50.0, None, 56.0, None, 62.0, 68.0]
        assert calculate_trend_direction(avgs) == "improving"


# ---------------------------------------------------------------------------
# New: integration tests — DB access
# ---------------------------------------------------------------------------


def _make_daily(date_str: str, **kwargs) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        data_sources='["whoop"]',
        last_updated=datetime.now(UTC).isoformat(),
        **kwargs,
    )


def _make_sleep(date_str: str, **kwargs) -> UnifiedSleep:
    return UnifiedSleep(
        date=date_str,
        primary_source="whoop",
        last_updated=datetime.now(UTC).isoformat(),
        **kwargs,
    )


def _make_workout(id_: str, date_str: str, **kwargs) -> UnifiedWorkout:
    return UnifiedWorkout(
        id=id_,
        date=date_str,
        start_time=f"{date_str}T08:00:00",
        last_updated=datetime.now(UTC).isoformat(),
        **kwargs,
    )


class TestGetMetricTrend:
    """get_metric_trend(engine, metric_name, start_date, end_date) -> MetricTrend.

    Uses dates in 2031-01 for standard metrics, 2031-03 for training_load.
    Lookback window goes back 29 days; all anchors are far from existing data.
    """

    # 40 days of recovery data in 2031-01-01..2031-02-09
    _START = date(2031, 1, 10)  # start of requested range (10 days in)
    _END = date(2031, 1, 31)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            # 40 days ascending 50..89 — trend should be "improving"
            for i in range(40):
                d = date(2031, 1, 1) + timedelta(days=i)
                session.merge(_make_daily(d.isoformat(), whoop_recovery_score=50.0 + i))
            # training_load: seed 14 workouts across 2031-03 (7 days × 2 workouts)
            for day in range(7):
                d = date(2031, 3, 1) + timedelta(days=day)
                for j in range(2):
                    session.merge(
                        _make_workout(
                            f"tl_{day}_{j}",
                            d.isoformat(),
                            whoop_strain=5.0 + j,
                            duration_minutes=45.0,
                        )
                    )
            session.commit()

    def test_returns_metric_trend_instance(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert isinstance(result, MetricTrend)

    def test_metric_name_stored(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert result.metric_name == "recovery_score"

    def test_dates_span_requested_range(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert result.dates[0] == self._START.isoformat()
        assert result.dates[-1] == self._END.isoformat()
        assert len(result.dates) == (self._END - self._START).days + 1

    def test_values_aligned_with_dates(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert len(result.values) == len(result.dates)

    def test_rolling_lists_aligned(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        n = len(result.dates)
        assert len(result.rolling_avg_7d) == n
        assert len(result.rolling_avg_30d) == n
        assert len(result.rolling_std_7d) == n

    def test_rolling_7d_non_none_after_enough_data(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        # All days in range have data; rolling_7d should be non-None everywhere
        assert all(v is not None for v in result.rolling_avg_7d)

    def test_rolling_7d_correct_value(self, engine):
        # Jan 10 (index 9 of full series 50..89) → value=59
        # 7-day window includes Jan 04..10 (values 53,54,55,56,57,58,59) → avg=56.0
        result = get_metric_trend(engine, "recovery_score", self._START, self._START)
        assert result.rolling_avg_7d[0] == pytest.approx(56.0)

    def test_trend_direction_improving(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert result.trend_direction == "improving"

    def test_anomalies_is_list(self, engine):
        result = get_metric_trend(engine, "recovery_score", self._START, self._END)
        assert isinstance(result.anomalies, list)

    def test_invalid_metric_raises(self, engine):
        with pytest.raises(ValueError, match="Unknown metric"):
            get_metric_trend(engine, "not_a_metric", self._START, self._END)

    def test_strain_metric_alias(self, engine):
        # "strain" should work the same as "daily_strain"
        result = get_metric_trend(engine, "strain", self._START, self._END)
        assert isinstance(result, MetricTrend)

    def test_training_load_sums_per_day(self, engine):
        # Each day in 2031-03 has 2 workouts with strain 5 and 6 → sum=11
        start = date(2031, 3, 1)
        end = date(2031, 3, 7)
        result = get_metric_trend(engine, "training_load", start, end)
        assert result.values[0] == pytest.approx(11.0)
        assert all(v == pytest.approx(11.0) for v in result.values if v is not None)

    def test_missing_days_appear_as_none(self, engine):
        # 2031-04 has no data seeded → all values None
        start = date(2031, 4, 1)
        end = date(2031, 4, 7)
        result = get_metric_trend(engine, "recovery_score", start, end)
        assert all(v is None for v in result.values)


class TestGetWeeklySummary:
    """get_weekly_summary(engine, end_date) -> dict.

    Uses dates in 2031-06. Current week: Jun 08-14. Prev week: Jun 01-07.
    """

    _END = date(2031, 6, 14)
    _CURR_START = date(2031, 6, 8)
    _PREV_START = date(2031, 6, 1)
    _PREV_END = date(2031, 6, 7)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            # Previous week: recovery=70, hrv=50, rhr=55, strain=10
            for i in range(7):
                d = cls._PREV_START + timedelta(days=i)
                session.merge(
                    _make_daily(
                        d.isoformat(),
                        whoop_recovery_score=70.0,
                        whoop_hrv_rmssd=50.0,
                        whoop_rhr=55.0,
                        whoop_strain=10.0,
                    )
                )
                session.merge(
                    _make_sleep(
                        d.isoformat(),
                        total_sleep_minutes=420.0,  # 7 h
                        deep_sleep_minutes=90.0,
                    )
                )
                session.merge(_make_workout(f"ws_prev_{i}", d.isoformat(), duration_minutes=60.0))
            # Current week: recovery=80, strain=12; more workouts
            for i in range(7):
                d = cls._CURR_START + timedelta(days=i)
                session.merge(
                    _make_daily(
                        d.isoformat(),
                        whoop_recovery_score=80.0,
                        whoop_hrv_rmssd=55.0,
                        whoop_rhr=53.0,
                        whoop_strain=12.0,
                    )
                )
                session.merge(
                    _make_sleep(
                        d.isoformat(),
                        total_sleep_minutes=480.0,  # 8 h
                        deep_sleep_minutes=100.0,
                    )
                )
                # 2 workouts per day this week
                for j in range(2):
                    session.merge(
                        _make_workout(
                            f"ws_curr_{i}_{j}",
                            d.isoformat(),
                            duration_minutes=45.0,
                        )
                    )
            session.commit()

    def _summary(self, engine):
        return get_weekly_summary(engine, self._END)

    def test_returns_dict(self, engine):
        assert isinstance(self._summary(engine), dict)

    def test_required_keys_present(self, engine):
        s = self._summary(engine)
        required = {
            "period_start",
            "period_end",
            "avg_recovery",
            "avg_hrv",
            "avg_rhr",
            "total_strain",
            "workout_count",
            "total_training_minutes",
            "avg_sleep_duration",
            "avg_deep_sleep",
            "notable_anomalies",
            "comparison",
        }
        assert required.issubset(s.keys())

    def test_period_dates_correct(self, engine):
        s = self._summary(engine)
        assert s["period_start"] == self._CURR_START.isoformat()
        assert s["period_end"] == self._END.isoformat()

    def test_avg_recovery_current_week(self, engine):
        assert self._summary(engine)["avg_recovery"] == pytest.approx(80.0)

    def test_total_strain_current_week(self, engine):
        # 7 days × 12 strain/day = 84
        assert self._summary(engine)["total_strain"] == pytest.approx(84.0)

    def test_workout_count_current_week(self, engine):
        # 7 days × 2 workouts = 14
        assert self._summary(engine)["workout_count"] == 14

    def test_total_training_minutes_current_week(self, engine):
        # 14 workouts × 45 min = 630
        assert self._summary(engine)["total_training_minutes"] == pytest.approx(630.0)

    def test_avg_sleep_duration_current_week(self, engine):
        assert self._summary(engine)["avg_sleep_duration"] == pytest.approx(480.0)

    def test_avg_deep_sleep_current_week(self, engine):
        assert self._summary(engine)["avg_deep_sleep"] == pytest.approx(100.0)

    def test_comparison_recovery_pct_change(self, engine):
        # 80 vs 70 → +14.3 %
        pct = self._summary(engine)["comparison"]["avg_recovery"]
        assert pct == pytest.approx(14.3, abs=0.1)

    def test_comparison_sleep_pct_change(self, engine):
        # 480 vs 420 → +14.3 %
        pct = self._summary(engine)["comparison"]["avg_sleep_duration"]
        assert pct == pytest.approx(14.3, abs=0.1)

    def test_comparison_workout_count_pct_change(self, engine):
        # 14 vs 7 → +100 %
        pct = self._summary(engine)["comparison"]["workout_count"]
        assert pct == pytest.approx(100.0)

    def test_notable_anomalies_is_list(self, engine):
        assert isinstance(self._summary(engine)["notable_anomalies"], list)

    def test_comparison_none_when_prev_zero(self, engine):
        # Use a period with no previous-week data → comparison values are None
        s = get_weekly_summary(engine, date(2031, 8, 7))
        assert s["comparison"]["avg_recovery"] is None


class TestTrendAnomalyLookback:
    """Anomalies are detected over the 29-day lookback, then trimmed to the range."""

    _LAST = date(2034, 3, 30)
    _JITTER = (60.0, 62.0, 58.0)

    @pytest.fixture(scope="class", autouse=True)
    @classmethod
    def seed(cls, engine):
        with Session(engine) as session:
            for i in range(30):
                d = cls._LAST - timedelta(days=29 - i)
                value = 20.0 if d == cls._LAST else cls._JITTER[i % 3]
                session.merge(_make_daily(d.isoformat(), whoop_recovery_score=value))
            session.commit()

    def test_trend_anomalies_use_lookback(self, engine):
        start = self._LAST - timedelta(days=2)
        trend = get_metric_trend(engine, "recovery_score", start, self._LAST)
        assert self._LAST.isoformat() in {a["date"] for a in trend.anomalies}

    def test_trend_anomalies_within_range(self, engine):
        start = self._LAST - timedelta(days=2)
        single = get_metric_trend(engine, "recovery_score", start, self._LAST)
        batch = get_batch_metric_trends(engine, ["recovery_score"], start, self._LAST)
        for trend in (single, batch["recovery_score"]):
            assert trend.anomalies
            assert all(a["date"] >= start.isoformat() for a in trend.anomalies)
