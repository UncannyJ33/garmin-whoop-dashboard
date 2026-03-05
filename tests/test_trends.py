"""Tests for src/analytics/trends.py.

Isolation strategy
------------------
All integration tests share a single module-scoped in-memory SQLite engine.
Each test class that writes data uses a unique, non-overlapping date window:

  TestGetMetricSeries   → recovery, 2029-02 (series) + 2029-07 (gap)
  TestDetectAnomalies   → recovery, 2029-05-01..28
  TestWeeklyRollup      → recovery, 2029-10-07..27
  TestMonthlyRollup     → recovery, 2029-11-01..2029-12-31

get_metric_series fetches a 27-day lookback window before start_date.
All anchors are spaced ≥ 35 days apart to prevent cross-contamination.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.trends import (
    AnomalyPoint,
    DailyPoint,
    PeriodRollup,
    _avg_nonull,
    _calendar_fill,
    _metric_source,
    _month_key,
    _std_nonull,
    _week_key,
    _z_score,
    detect_anomalies,
    get_metric_series,
    get_monthly_rollup,
    get_weekly_rollup,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily

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
    def seed(self, engine):
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
    """Uses recovery data in 2029-05: normal (70), high outlier (100), low outlier (30)."""

    # May 01-26 = 70, May 27 = 100 (high), May 28 = 30 (low)
    _END = date(2029, 5, 28)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as session:
            for i in range(26):
                d = date(2029, 5, 1) + timedelta(days=i)
                session.merge(_daily(d.isoformat(), 70.0))
            session.merge(_daily("2029-05-27", 100.0))
            session.merge(_daily("2029-05-28", 30.0))
            session.commit()

    def test_high_outlier_detected(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=27, end_date=date(2029, 5, 27))
        dates = [a.date for a in anomalies]
        assert "2029-05-27" in dates

    def test_low_outlier_detected(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=28, end_date=self._END)
        dates = [a.date for a in anomalies]
        assert "2029-05-28" in dates

    def test_high_direction(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=27, end_date=date(2029, 5, 27))
        a = next(x for x in anomalies if x.date == "2029-05-27")
        assert a.direction == "high"
        assert a.z_score > 0

    def test_low_direction(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=28, end_date=self._END)
        a = next(x for x in anomalies if x.date == "2029-05-28")
        assert a.direction == "low"
        assert a.z_score < 0

    def test_normal_days_not_flagged(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=28, end_date=self._END)
        flagged = {a.date for a in anomalies}
        # None of the 70-valued days (May 01-26) should be flagged
        for i in range(26):
            d = (date(2029, 5, 1) + timedelta(days=i)).isoformat()
            assert d not in flagged

    def test_rolling_mean_and_std_populated(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=27, end_date=date(2029, 5, 27))
        a = next(x for x in anomalies if x.date == "2029-05-27")
        assert a.rolling_mean is not None
        assert a.rolling_std is not None and a.rolling_std > 0

    def test_custom_high_threshold_suppresses_normal_outlier(self, engine):
        # threshold=10.0 → nothing flagged (max z ≈ 5)
        anomalies = detect_anomalies(
            engine, "recovery", days=27, end_date=date(2029, 5, 27), z_threshold=10.0
        )
        assert anomalies == []

    def test_returns_anomaly_point_instances(self, engine):
        anomalies = detect_anomalies(engine, "recovery", days=27, end_date=date(2029, 5, 27))
        assert all(isinstance(a, AnomalyPoint) for a in anomalies)


class TestWeeklyRollup:
    """Uses recovery data in 2029-10-08 through 2029-10-28 (3 full ISO weeks).

    Oct 08 2029 is the Monday that starts W41.  Three consecutive weeks:
      W41: Oct 08-14, values 70..76
      W42: Oct 15-21, values all 80
      W43: Oct 22-28, values all 90
    """

    # These are computed dynamically from _week_key to avoid hard-coding ISO numbers.
    _START = date(2029, 10, 8)   # Monday of W41
    _END = date(2029, 10, 28)    # Sunday of W43

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as session:
            for i in range(7):
                d = self._START + timedelta(days=i)
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
    def seed(self, engine):
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
        assert rollups[0].count == 30   # November
        assert rollups[1].count == 31   # December

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
