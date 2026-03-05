"""Tests for src/analytics/sleep_analysis.py.

Isolation strategy
------------------
Every integration test commits data to the module-level in-memory engine.
To prevent interference, each test class that inserts data uses a UNIQUE
fixed anchor date chosen so that the full data window (main range + the
6-day rolling history prefix) never overlaps with any other test's window.

The critical windows:
  - get_sleep_insights:      anchor 2026-06-* / 2026-07-*  (GetSleepInsights)
  - strain correlations:     anchors 2027-01-20 / -02-20 / -03-20 / -04-20 / -05-20 / -06-10
  - consistency tests:       anchors 2028-01 through 2028-10, spaced ≥ 45 days apart
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.sleep_analysis import (
    DEFAULT_TARGET_SLEEP_MINUTES,
    SleepInsight,
    _avg_nonull,
    _build_insight,
    _linear_slope,
    _pearson_r,
    _std_nonull,
    _time_str_to_fractional_hours,
    get_sleep_consistency,
    get_sleep_insights,
    get_strain_sleep_correlation,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import (
    UnifiedDaily,
    UnifiedSleep,
    WhoopSleep,
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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _usleep(
    date_str: str,
    total_min: float | None = 430.0,
    deep_min: float | None = 90.0,
    light_min: float | None = 180.0,
    rem_min: float | None = 100.0,
    awake_min: float | None = 20.0,
    performance: float | None = 80.0,
    efficiency: float | None = 88.0,
) -> UnifiedSleep:
    return UnifiedSleep(
        date=date_str,
        total_sleep_minutes=total_min,
        deep_sleep_minutes=deep_min,
        light_sleep_minutes=light_min,
        rem_sleep_minutes=rem_min,
        awake_minutes=awake_min,
        whoop_performance=performance,
        whoop_efficiency=efficiency,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


def _udaily(date_str: str, strain: float | None = None,
            recovery: float | None = None, body_battery: int | None = None) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_strain=strain,
        whoop_recovery_score=recovery,
        garmin_body_battery_high=body_battery,
        data_sources='["whoop"]',
        last_updated=NOW_ISO,
    )


def _whoop_sleep(row_id: str, start_iso: str, end_iso: str) -> WhoopSleep:
    return WhoopSleep(
        id=row_id,
        cycle_id=None,
        start_time=start_iso,
        end_time=end_iso,
        nap=0,
        score_state="SCORED",
        fetched_at=NOW_ISO,
    )


def _add_days(date_str: str, n: int) -> str:
    return (date.fromisoformat(date_str) + timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Pure unit tests — no DB access
# ---------------------------------------------------------------------------


class TestPearsonR:
    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        assert _pearson_r(xs, xs) == pytest.approx(1.0, abs=1e-9)

    def test_perfect_negative(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        assert _pearson_r(xs, [-x for x in xs]) == pytest.approx(-1.0, abs=1e-9)

    def test_zero_variance_returns_none(self):
        xs = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0]
        assert _pearson_r(xs, [5.0] * 7) is None  # constant y → zero variance

    def test_returns_none_below_min_sample(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]   # 6 < min of 7
        assert _pearson_r(xs, xs) is None

    def test_returns_result_at_min_sample(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]   # exactly 7
        assert _pearson_r(xs, xs) is not None

    def test_staircase_near_perfect(self):
        # y = x + tiny alternating noise; r should be well above 0.98
        xs = [float(i) for i in range(1, 11)]
        ys = [x + (0.5 if i % 2 == 0 else -0.5) for i, x in enumerate(xs)]
        r = _pearson_r(xs, ys)
        assert r is not None
        assert r > 0.98

    def test_output_in_range(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        ys = [7.0, 1.0, 6.0, 2.0, 5.0, 3.0, 4.0]
        r = _pearson_r(xs, ys)
        assert r is not None
        assert -1.0 <= r <= 1.0


class TestLinearSlope:
    def test_positive(self):
        assert _linear_slope([1.0, 3.0, 5.0, 7.0, 9.0]) == pytest.approx(2.0, abs=1e-9)

    def test_negative(self):
        assert _linear_slope([10.0, 8.0, 6.0, 4.0, 2.0]) == pytest.approx(-2.0, abs=1e-9)

    def test_zero(self):
        assert _linear_slope([5.0] * 7) == pytest.approx(0.0, abs=1e-9)

    def test_none_single(self):
        assert _linear_slope([42.0]) is None

    def test_none_empty(self):
        assert _linear_slope([]) is None


class TestTimeToFractionalHours:
    def test_10_30_pm(self):
        assert _time_str_to_fractional_hours("2026-03-04T22:30:00+00:00") == pytest.approx(22.5)

    def test_1_30_am(self):
        assert _time_str_to_fractional_hours("2026-03-05T01:30:00+00:00") == pytest.approx(1.5)

    def test_midnight(self):
        assert _time_str_to_fractional_hours("2026-03-05T00:00:00+00:00") == pytest.approx(0.0)

    def test_none_input(self):
        assert _time_str_to_fractional_hours(None) is None

    def test_bad_string(self):
        assert _time_str_to_fractional_hours("not-a-date") is None

    def test_no_timezone(self):
        assert _time_str_to_fractional_hours("2026-03-04T23:00:00") == pytest.approx(23.0)


class TestAvgStdNonull:
    def test_avg_normal(self):
        assert _avg_nonull([10.0, 20.0, 30.0]) == pytest.approx(20.0)

    def test_avg_skips_none(self):
        assert _avg_nonull([10.0, None, 30.0]) == pytest.approx(20.0)

    def test_avg_all_none(self):
        assert _avg_nonull([None, None]) is None

    def test_std_known(self):
        # Population std of [2, 4, 6] = sqrt(8/3)
        assert _std_nonull([2.0, 4.0, 6.0]) == pytest.approx(math.sqrt(8 / 3), abs=1e-6)

    def test_std_none_single(self):
        assert _std_nonull([5.0]) is None

    def test_std_none_empty(self):
        assert _std_nonull([]) is None


# ---------------------------------------------------------------------------
# _build_insight — pure builder
# ---------------------------------------------------------------------------


class TestBuildInsight:
    DATE = "2026-02-10"

    def _sleep_row(self, **ov) -> dict:
        base = {
            "date": self.DATE, "total_sleep_minutes": 430.0, "deep_sleep_minutes": 90.0,
            "light_sleep_minutes": 180.0, "rem_sleep_minutes": 100.0, "awake_minutes": 20.0,
            "whoop_performance": 80.0, "whoop_efficiency": 88.0,
        }
        return {**base, **ov}

    def _daily(self, strain=10.0, recovery=70.0, bb=65) -> dict[str, dict]:
        prev = _add_days(self.DATE, -1)
        return {
            prev: {"whoop_strain": strain, "whoop_recovery_score": None, "garmin_body_battery_high": None},
            self.DATE: {"whoop_strain": None, "whoop_recovery_score": recovery, "garmin_body_battery_high": bb},
        }

    def test_returns_sleep_insight(self):
        assert isinstance(_build_insight(self._sleep_row(), self._daily(), {}, {}, 480.0), SleepInsight)

    def test_sleep_fields(self):
        r = _build_insight(self._sleep_row(), self._daily(), {}, {}, 480.0)
        assert r.total_sleep_minutes == 430.0
        assert r.sleep_performance == 80.0
        assert r.sleep_efficiency == 88.0

    def test_prev_strain(self):
        assert _build_insight(self._sleep_row(), self._daily(strain=15.0), {}, {}, 480.0).previous_day_strain == 15.0

    def test_next_day_recovery(self):
        assert _build_insight(self._sleep_row(), self._daily(recovery=82.0), {}, {}, 480.0).next_day_recovery_score == 82.0

    def test_next_day_body_battery(self):
        assert _build_insight(self._sleep_row(), self._daily(bb=75), {}, {}, 480.0).next_day_body_battery == 75

    def test_body_battery_none(self):
        assert _build_insight(self._sleep_row(), self._daily(bb=None), {}, {}, 480.0).next_day_body_battery is None

    def test_training_load(self):
        prev = _add_days(self.DATE, -1)
        r = _build_insight(self._sleep_row(), self._daily(), {prev: 88.0}, {}, 480.0)
        assert r.previous_day_training_load == 88.0

    def test_debt_deficit(self):
        hist = {_add_days(self.DATE, -i): {"total_sleep_minutes": 420.0} for i in range(7)}
        r = _build_insight(self._sleep_row(total_sleep_minutes=420.0), self._daily(), {}, hist, 480.0)
        assert r.sleep_debt_estimate == pytest.approx(-60.0, abs=0.1)

    def test_debt_surplus(self):
        hist = {_add_days(self.DATE, -i): {"total_sleep_minutes": 540.0} for i in range(7)}
        r = _build_insight(self._sleep_row(total_sleep_minutes=540.0), self._daily(), {}, hist, 480.0)
        assert r.sleep_debt_estimate == pytest.approx(60.0, abs=0.1)

    def test_debt_none_no_history(self):
        assert _build_insight(self._sleep_row(), self._daily(), {}, {}, 480.0).sleep_debt_estimate is None

    def test_custom_target(self):
        hist = {_add_days(self.DATE, -i): {"total_sleep_minutes": 420.0} for i in range(7)}
        r = _build_insight(self._sleep_row(total_sleep_minutes=420.0), self._daily(), {}, hist, 420.0)
        assert r.sleep_debt_estimate == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# get_sleep_insights — DB integration
# 2026-06-* and 2026-07-* (separate to avoid contamination)
# ---------------------------------------------------------------------------


class TestGetSleepInsights:
    START = date(2026, 6, 1)
    END = date(2026, 6, 7)

    def _populate(self, session, strains, sleeps):
        for i in range(6, 0, -1):
            d = _add_days(self.START.isoformat(), -i)
            session.merge(_usleep(d, total_min=420.0))
        for i, (strain, sleep) in enumerate(zip(strains, sleeps)):
            sd = _add_days(self.START.isoformat(), i)
            prev = _add_days(sd, -1)
            session.merge(_usleep(sd, total_min=sleep, deep_min=sleep * 0.2))
            session.merge(_udaily(prev, strain=strain, recovery=70.0, body_battery=60))
            session.merge(_udaily(sd, strain=5.0, recovery=70.0, body_battery=60))
        session.commit()

    def test_returns_list(self, engine):
        assert isinstance(get_sleep_insights(engine, self.START, self.END), list)

    def test_correct_count(self, engine):
        with Session(engine) as s:
            self._populate(s, [10.0] * 7, [430.0] * 7)
        assert len(get_sleep_insights(engine, self.START, self.END)) == 7

    def test_dates_match_range(self, engine):
        with Session(engine) as s:
            self._populate(s, [10.0] * 7, [430.0] * 7)
        results = get_sleep_insights(engine, self.START, self.END)
        assert results[0].date == self.START.isoformat()
        assert results[-1].date == self.END.isoformat()

    def test_strain_wired_from_prev_day(self, engine):
        strains = [5.0, 10.0, 15.0, 8.0, 12.0, 6.0, 18.0]
        with Session(engine) as s:
            self._populate(s, strains, [430.0] * 7)
        results = get_sleep_insights(engine, self.START, self.END)
        for insight, expected in zip(results, strains):
            assert insight.previous_day_strain == pytest.approx(expected, abs=0.01)

    def test_sleep_debt_computed(self, engine):
        # 6 history nights + 7 test nights all at 420 → avg 420; target 480 → debt -60
        with Session(engine) as s:
            self._populate(s, [10.0] * 7, [420.0] * 7)
        results = get_sleep_insights(engine, self.START, self.END)
        for r in results:
            assert r.sleep_debt_estimate == pytest.approx(-60.0, abs=1.0)

    def test_custom_target(self, engine):
        with Session(engine) as s:
            self._populate(s, [10.0] * 7, [420.0] * 7)
        r480 = get_sleep_insights(engine, self.START, self.END, 480.0)
        r420 = get_sleep_insights(engine, self.START, self.END, 420.0)
        assert r480[-1].sleep_debt_estimate == pytest.approx(-60.0, abs=1.0)
        assert r420[-1].sleep_debt_estimate == pytest.approx(0.0, abs=1.0)

    def test_empty_range(self, engine):
        assert get_sleep_insights(engine, date(2099, 1, 1), date(2099, 1, 1)) == []

    def test_omits_dates_without_sleep(self, engine):
        """Uses 2026-07-* to avoid contamination from 2026-06-* tests."""
        start, end = date(2026, 7, 1), date(2026, 7, 7)
        with Session(engine) as s:
            for d in ["2026-07-01", "2026-07-03", "2026-07-06"]:
                s.merge(_usleep(d))
                s.merge(_udaily(d, recovery=70.0))
            s.commit()
        dates = {r.date for r in get_sleep_insights(engine, start, end)}
        assert "2026-07-01" in dates
        assert "2026-07-02" not in dates
        assert "2026-07-03" in dates


# ---------------------------------------------------------------------------
# get_strain_sleep_correlation — unique anchors in 2027
#
# Data design (for perfect correlations):
#   strain[i] = 10 + i  (stored at date start+i-1, as previous_day_strain for sleep start+i)
#   total_sleep[i] = 400 + 2*i  (stored at date start+i)
#   deep_sleep[i]  = 80 + i
#   recovery[i]    = 50 - 0.5*i (stored at date start+i as next_day_recovery)
#
# Key: insert strain and recovery as SEPARATE fields on each date to avoid
# one merge overwriting the other.
# ---------------------------------------------------------------------------


class TestStrainSleepCorrelation:

    def _insert(self, session, n_days: int, anchor: date):
        """Insert correlated sleep/daily data ending at anchor.

        Each unified_daily row is inserted once with BOTH strain and recovery
        values to avoid a later merge overwriting an earlier one.
        """
        start = anchor - timedelta(days=n_days - 1)

        # 6-day history prefix (for rolling debt window, won't affect correlations)
        for j in range(1, 7):
            d = (start - timedelta(days=j)).isoformat()
            session.merge(_usleep(d, total_min=420.0))

        # Build per-date strain and recovery maps
        # sleep_date = start+i → prev = start+i-1 → strain at prev = 10+i
        # recovery at start+i = 50 - 0.5*i
        daily: dict[str, dict] = {}

        # strain for start-1 (prev of first sleep day)
        prev0 = (start - timedelta(days=1)).isoformat()
        daily[prev0] = {"whoop_strain": 10.0, "whoop_recovery_score": None}

        for i in range(n_days):
            d = (start + timedelta(days=i)).isoformat()
            # strain at d is used by sleep insight at start+i+1 (as previous_day_strain)
            # i.e., strain_at_d = 10 + (i+1) = 11 + i
            # recovery at d is used by sleep insight at start+i (same date)
            recovery = 50.0 - i * 0.5
            strain = 11.0 + i   # = 10 + (i+1)
            daily[d] = {"whoop_strain": strain, "whoop_recovery_score": recovery}
            session.merge(_usleep(d, total_min=400.0 + i * 2, deep_min=80.0 + i))

        for d_str, vals in daily.items():
            session.merge(UnifiedDaily(
                date=d_str,
                whoop_strain=vals["whoop_strain"],
                whoop_recovery_score=vals["whoop_recovery_score"],
                data_sources='["whoop"]',
                last_updated=NOW_ISO,
            ))

        session.commit()

    def test_perfect_positive_total_sleep(self, engine):
        anchor = date(2027, 1, 20)
        with Session(engine) as s:
            self._insert(s, 15, anchor)
        r = get_strain_sleep_correlation(engine, days=15, end_date=anchor)
        assert r["strain_vs_total_sleep"]["r"] == pytest.approx(1.0, abs=0.01)

    def test_perfect_positive_deep_sleep(self, engine):
        anchor = date(2027, 2, 20)
        with Session(engine) as s:
            self._insert(s, 15, anchor)
        r = get_strain_sleep_correlation(engine, days=15, end_date=anchor)
        assert r["strain_vs_deep_sleep"]["r"] == pytest.approx(1.0, abs=0.01)

    def test_perfect_negative_recovery(self, engine):
        anchor = date(2027, 3, 20)
        with Session(engine) as s:
            self._insert(s, 15, anchor)
        r = get_strain_sleep_correlation(engine, days=15, end_date=anchor)
        assert r["strain_vs_next_day_recovery"]["r"] == pytest.approx(-1.0, abs=0.01)

    def test_required_keys(self, engine):
        anchor = date(2027, 4, 20)
        with Session(engine) as s:
            self._insert(s, 10, anchor)
        result = get_strain_sleep_correlation(engine, days=10, end_date=anchor)
        for key in ("strain_vs_total_sleep", "strain_vs_deep_sleep", "strain_vs_next_day_recovery"):
            assert {"r", "n", "sufficient_data"}.issubset(result[key].keys())

    def test_days_analyzed(self, engine):
        anchor = date(2027, 5, 20)
        with Session(engine) as s:
            self._insert(s, 10, anchor)
        assert get_strain_sleep_correlation(engine, days=10, end_date=anchor)["days_analyzed"] == 10

    def test_insufficient_data(self, engine):
        anchor = date(2027, 6, 10)
        with Session(engine) as s:
            for i in range(3):
                d = (anchor - timedelta(days=2 - i)).isoformat()
                session_obj = s
                session_obj.merge(_usleep(d, total_min=420.0))
                session_obj.merge(UnifiedDaily(
                    date=_add_days(d, -1),
                    whoop_strain=10.0 + i,
                    data_sources='["whoop"]',
                    last_updated=NOW_ISO,
                ))
            s.commit()
        sub = get_strain_sleep_correlation(engine, days=3, end_date=anchor)["strain_vs_total_sleep"]
        assert sub["r"] is None
        assert sub["sufficient_data"] is False
        assert "message" in sub


# ---------------------------------------------------------------------------
# get_sleep_consistency — unique anchors in 2028
#
# Window arithmetic (to avoid inter-test contamination):
#   _insert_schedule(n, anchor) occupies whoop_sleep at [anchor-n+1, anchor]
#   get_sleep_consistency(days=n, end_date=anchor) also fetches unified_sleep
#   history from [anchor-n-5, anchor-n] for the debt trend.
#
# Chosen anchors leave ≥ 45 days between each test's occupied window.
# ---------------------------------------------------------------------------


class TestGetSleepConsistency:

    def _insert_schedule(self, session, n_days: int, anchor: date,
                         bed_hour: int = 23, wake_hour: int = 7,
                         sleep_min: float = 480.0, prefix: str = "wsc"):
        for i in range(n_days):
            wake = anchor - timedelta(days=n_days - 1 - i)
            prev = wake - timedelta(days=1)
            session.merge(_whoop_sleep(
                f"{prefix}_{i}",
                f"{prev.isoformat()}T{bed_hour:02d}:00:00+00:00",
                f"{wake.isoformat()}T{wake_hour:02d}:00:00+00:00",
            ))
            session.merge(_usleep(wake.isoformat(), total_min=sleep_min))
        session.commit()

    # -- insufficient data --------------------------------------------------

    def test_insufficient_below_7(self, engine):
        anchor = date(2028, 1, 3)
        with Session(engine) as s:
            self._insert_schedule(s, 3, anchor, prefix="ins3")
        result = get_sleep_consistency(engine, days=3, end_date=anchor)
        assert result["insufficient_data"] is True
        assert "message" in result

    # -- consistent 11 PM bedtime, 7 AM wake (anchor 2028-02-10) -----------

    def test_required_keys(self, engine):
        anchor = date(2028, 2, 10)
        with Session(engine) as s:
            self._insert_schedule(s, 10, anchor, prefix="cpcons")
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        assert result["insufficient_data"] is False
        required = {
            "avg_bedtime_hour", "bedtime_std_hours", "avg_wake_hour",
            "wake_time_std_hours", "avg_total_sleep_minutes",
            "sleep_debt_trend", "sleep_debt_trend_slope_min_per_day", "sample_size",
        }
        assert required.issubset(result.keys())

    def test_avg_bedtime_11pm(self, engine):
        anchor = date(2028, 2, 10)
        with Session(engine) as s:
            self._insert_schedule(s, 10, anchor, bed_hour=23, prefix="cpcons")
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        assert result["avg_bedtime_hour"] == pytest.approx(23.0, abs=0.05)

    def test_bedtime_std_zero(self, engine):
        anchor = date(2028, 2, 10)
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        assert result["bedtime_std_hours"] == pytest.approx(0.0, abs=0.01)

    def test_avg_wake_7am(self, engine):
        anchor = date(2028, 2, 10)
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        assert result["avg_wake_hour"] == pytest.approx(7.0, abs=0.05)

    def test_sample_size(self, engine):
        anchor = date(2028, 2, 10)
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        assert result["sample_size"] == 10

    # -- midnight-crossing bedtime (anchor 2028-04-10) ----------------------

    def test_midnight_crossing_average(self, engine):
        """11:30 PM / 12:30 AM alternating → avg = midnight = 0.0 hours."""
        anchor = date(2028, 4, 10)
        with Session(engine) as s:
            for i in range(10):
                wake = anchor - timedelta(days=9 - i)
                prev = wake - timedelta(days=1)
                if i % 2 == 0:
                    bed_iso = f"{prev.isoformat()}T23:30:00+00:00"   # 23.5 h
                else:
                    bed_iso = f"{wake.isoformat()}T00:30:00+00:00"   # 0.5 h → +24 = 24.5
                s.merge(_whoop_sleep(f"wsmid_{i}", bed_iso,
                                     f"{wake.isoformat()}T07:00:00+00:00"))
                s.merge(_usleep(wake.isoformat(), total_min=450.0))
            s.commit()
        result = get_sleep_consistency(engine, days=10, end_date=anchor)
        # avg(23.5, 24.5, 23.5, 24.5, ...) = 24.0 → normalised to 0.0
        assert result["avg_bedtime_hour"] == pytest.approx(0.0, abs=0.1)

    # -- sleep debt trends (well-separated anchors) -------------------------

    def test_stable_trend(self, engine):
        """Constant 8 h → debt = 0 every night → slope ≈ 0 → stable."""
        anchor = date(2028, 6, 14)
        with Session(engine) as s:
            self._insert_schedule(s, 14, anchor, sleep_min=480.0, prefix="stbl")
        result = get_sleep_consistency(engine, days=14, end_date=anchor)
        assert result["sleep_debt_trend"] == "stable"
        assert result["sleep_debt_trend_slope_min_per_day"] == pytest.approx(0.0, abs=1.5)

    def test_worsening_trend(self, engine):
        """Sleep decreasing 10 min/night → rolling avg falls → slope < 0 → worsening."""
        anchor = date(2028, 8, 14)
        with Session(engine) as s:
            for i in range(14):
                wake = anchor - timedelta(days=13 - i)
                prev = wake - timedelta(days=1)
                s.merge(_whoop_sleep(
                    f"wrse_{i}",
                    f"{prev.isoformat()}T23:00:00+00:00",
                    f"{wake.isoformat()}T07:00:00+00:00",
                ))
                s.merge(_usleep(wake.isoformat(), total_min=max(480.0 - i * 10.0, 200.0)))
            s.commit()
        result = get_sleep_consistency(engine, days=14, end_date=anchor)
        assert result["sleep_debt_trend"] == "worsening"
        assert result["sleep_debt_trend_slope_min_per_day"] < 0

    def test_improving_trend(self, engine):
        """Sleep increasing 10 min/night → rolling avg rises → slope > 0 → improving."""
        anchor = date(2028, 10, 14)
        with Session(engine) as s:
            for i in range(14):
                wake = anchor - timedelta(days=13 - i)
                prev = wake - timedelta(days=1)
                s.merge(_whoop_sleep(
                    f"impv_{i}",
                    f"{prev.isoformat()}T23:30:00+00:00",
                    f"{wake.isoformat()}T07:00:00+00:00",
                ))
                s.merge(_usleep(wake.isoformat(), total_min=360.0 + i * 10.0))
            s.commit()
        result = get_sleep_consistency(engine, days=14, end_date=anchor)
        assert result["sleep_debt_trend"] == "improving"
        assert result["sleep_debt_trend_slope_min_per_day"] > 0
