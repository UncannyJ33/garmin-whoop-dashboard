"""Tests for src/analytics/limiting_factors.py.

Isolation strategy
------------------
All tests share one module-scoped in-memory SQLite engine.
unified_daily uses ``date`` as its sole primary key, so each test class must
use non-overlapping date windows.  All anchors are spaced ≥ 30 days apart in
2041 (far from the 2040 training_load test dates).

  TestExplanationTemplates — pure function tests, no DB
  TestSleepLimiting        — anchor 2041-01-15  (sleep quality crashes)
  TestRecoveryLimiting     — anchor 2041-02-20  (recovery crashes)
  TestBodyBatteryLimiting  — anchor 2041-03-28  (body battery crashes)
  TestGoodDay              — anchor 2041-05-05  (all factors near baseline)
  TestTopN                 — anchor 2041-06-10  (two factors limiting, test top_n=1)
  TestNoData               — anchor 2041-07-20  (no data → empty list)
  TestInsufficientHistory  — anchor 2041-08-25  (only 2 prior days → no baseline)
  TestSeverityThresholds   — pure logic, no DB (tests _classify_severity)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.limiting_factors import (
    _avg,
    _build_explanation,
    _classify_severity,
    _fmt,
    get_limiting_factors,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, UnifiedSleep

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


def _daily(
    date_str: str,
    recovery: float = 75.0,
    hrv: float = 60.0,
    bb: int = 80,
    strain: float | None = None,
) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        whoop_hrv_rmssd=hrv,
        garmin_body_battery_high=bb,
        whoop_strain=strain,
        data_sources='["whoop","garmin"]',
        last_updated=NOW_ISO,
    )


def _sleep(date_str: str, performance: float = 75.0) -> UnifiedSleep:
    return UnifiedSleep(
        date=date_str,
        whoop_performance=performance,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


def _seed_window(session: Session, anchor: date, days: int = 15) -> None:
    """Seed ``days`` days of uniform baseline data ending at anchor.

    All metrics set to mid-range values so no factor is limiting by default.
    """
    for i in range(days):
        d = (anchor - timedelta(days=days - 1 - i)).isoformat()
        session.merge(_daily(d))
        session.merge(_sleep(d))


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------


class TestSeverityThresholds:
    def test_mild(self):
        assert _classify_severity(-8.0) == "mild"

    def test_mild_boundary(self):
        assert _classify_severity(-14.9) == "mild"

    def test_moderate(self):
        assert _classify_severity(-15.0) == "moderate"

    def test_moderate_high(self):
        assert _classify_severity(-29.9) == "moderate"

    def test_significant(self):
        assert _classify_severity(-30.0) == "significant"

    def test_significant_extreme(self):
        assert _classify_severity(-75.0) == "significant"


class TestAvgHelper:
    def test_returns_none_below_min_history(self):
        assert _avg([50.0, 60.0]) is None  # only 2 values, min is 3

    def test_returns_avg_at_min_history(self):
        result = _avg([50.0, 60.0, 70.0])
        assert result == 60.0

    def test_skips_none_values(self):
        result = _avg([50.0, None, 70.0, 60.0])
        assert result == 60.0

    def test_all_none_returns_none(self):
        assert _avg([None, None, None]) is None


class TestFmtHelper:
    def test_recovery_pct(self):
        assert _fmt("whoop_recovery", 52.4) == "52%"

    def test_sleep_pct(self):
        assert _fmt("sleep_quality", 74.0) == "74%"

    def test_hrv_ms(self):
        assert _fmt("hrv_trend", 38.2) == "38ms"

    def test_body_battery_num(self):
        assert _fmt("body_battery", 42.0) == "42"


class TestExplanationTemplates:
    def test_sleep_quality_significant(self):
        msg = _build_explanation("sleep_quality", 52.0, 74.0, -30.0, "significant")
        assert "dragging" in msg
        assert "52%" in msg
        assert "74%" in msg

    def test_sleep_quality_mild(self):
        msg = _build_explanation("sleep_quality", 68.0, 74.0, -8.0, "mild")
        assert "slightly affecting" in msg

    def test_hrv_below_baseline(self):
        msg = _build_explanation("hrv_trend", 38.0, 52.0, -26.0, "moderate")
        assert "low" in msg
        assert "38ms" in msg
        assert "below" in msg
        assert "52ms" in msg

    def test_hrv_above_baseline(self):
        msg = _build_explanation("hrv_trend", 70.0, 52.0, +35.0, "mild")
        assert "above" in msg

    def test_recovery_explanation(self):
        msg = _build_explanation("whoop_recovery", 30.0, 70.0, -57.0, "significant")
        assert "bounced back" in msg
        assert "30%" in msg
        assert "70%" in msg

    def test_body_battery_explanation(self):
        msg = _build_explanation("body_battery", 25.0, 65.0, -61.0, "significant")
        assert "Body Battery" in msg
        assert "25" in msg
        assert "65" in msg

    def test_training_load_with_acwr(self):
        msg = _build_explanation(
            "training_load",
            105.0,
            60.0,
            -35.0,
            "significant",
            acute_load=105.0,
            chronic_load=240.0,
        )
        assert "high" in msg
        assert "105.0" in msg
        assert "240.0" in msg

    def test_training_load_without_acwr(self):
        msg = _build_explanation("training_load", 105.0, 60.0, -35.0, "significant")
        assert "high" in msg
        assert "baseline" in msg


# ---------------------------------------------------------------------------
# Integration tests (DB-backed)
# ---------------------------------------------------------------------------


class TestSleepLimiting:
    """Sleep quality crashes on the anchor day — should surface as most limiting."""

    ANCHOR = date(2041, 1, 15)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # 15 days of uniform baseline data
            _seed_window(s, self.ANCHOR, days=15)
            # Override anchor sleep to be way below average (40 vs 75 baseline)
            s.merge(_sleep(self.ANCHOR.isoformat(), performance=40.0))
            s.commit()

    def test_sleep_returned_as_limiting(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        names = [f.factor_name for f in factors]
        assert "Sleep Quality" in names

    def test_current_value_matches_seed(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert sleep_f.current_value == pytest.approx(40.0, abs=0.5)

    def test_seven_day_avg_near_baseline(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert sleep_f.seven_day_avg == pytest.approx(75.0, abs=1.0)

    def test_deviation_is_negative(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert sleep_f.deviation_pct < -_get_mild_threshold()

    def test_severity_significant(self, engine):
        # 40 vs 75 → deviation ≈ -47% → significant
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert sleep_f.severity == "significant"

    def test_explanation_contains_values(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert "40%" in sleep_f.explanation or "40" in sleep_f.explanation
        assert "dragging" in sleep_f.explanation

    def test_display_strings_formatted(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        sleep_f = next(f for f in factors if f.factor_name == "Sleep Quality")
        assert sleep_f.current_value_display.endswith("%")
        assert sleep_f.seven_day_avg_display.endswith("%")


class TestRecoveryLimiting:
    """Recovery score crashes — should surface as limiting."""

    ANCHOR = date(2041, 2, 20)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            _seed_window(s, self.ANCHOR, days=15)
            # Override anchor daily: recovery crashes to 20 (vs 75 baseline)
            s.merge(_daily(self.ANCHOR.isoformat(), recovery=20.0))
            s.commit()

    def test_recovery_returned(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        names = [f.factor_name for f in factors]
        assert "Recovery Score" in names

    def test_explanation_template(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        rec = next(f for f in factors if f.factor_name == "Recovery Score")
        assert "bounced back" in rec.explanation
        assert "20%" in rec.explanation

    def test_severity_significant(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        rec = next(f for f in factors if f.factor_name == "Recovery Score")
        assert rec.severity == "significant"


class TestBodyBatteryLimiting:
    """Body Battery crashes — should surface as limiting."""

    ANCHOR = date(2041, 3, 28)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            _seed_window(s, self.ANCHOR, days=15)
            # Override anchor daily: body battery crashes to 15 (vs 80 baseline)
            s.merge(_daily(self.ANCHOR.isoformat(), bb=15))
            s.commit()

    def test_body_battery_returned(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        names = [f.factor_name for f in factors]
        assert "Body Battery" in names

    def test_explanation_template(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        bb = next(f for f in factors if f.factor_name == "Body Battery")
        assert "Body Battery" in bb.explanation
        assert "15" in bb.explanation

    def test_display_no_percent(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        bb = next(f for f in factors if f.factor_name == "Body Battery")
        assert "%" not in bb.current_value_display


class TestGoodDay:
    """All factors near their 7-day baselines → no limiting factors returned."""

    ANCHOR = date(2041, 5, 5)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Uniform baseline — today is same as all prior days
            _seed_window(s, self.ANCHOR, days=15)
            s.commit()

    def test_empty_on_good_day(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        assert factors == []


class TestTopN:
    """Both sleep and recovery are limiting — test that top_n=1 returns only 1."""

    ANCHOR = date(2041, 6, 10)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            _seed_window(s, self.ANCHOR, days=15)
            # Both recovery and sleep crash on anchor day
            s.merge(_daily(self.ANCHOR.isoformat(), recovery=20.0))
            s.merge(_sleep(self.ANCHOR.isoformat(), performance=30.0))
            s.commit()

    def test_default_returns_up_to_two(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR, top_n=2)
        assert len(factors) <= 2
        assert len(factors) >= 1

    def test_top_n_1_returns_one(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR, top_n=1)
        assert len(factors) == 1

    def test_sorted_most_limiting_first(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR, top_n=2)
        if len(factors) == 2:
            assert factors[0].deviation_pct <= factors[1].deviation_pct

    def test_most_limiting_has_significant_severity(self, engine):
        factors = get_limiting_factors(engine, None, self.ANCHOR, top_n=1)
        assert factors[0].severity in ("significant", "moderate")


class TestNoData:
    """No data at all → empty list (confidence == 0)."""

    ANCHOR = date(2041, 7, 20)

    def test_empty_when_no_data(self, engine):
        # No data seeded for this date range
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        assert factors == []


class TestInsufficientHistory:
    """Only 2 prior days of data — no 7-day baseline → factors skipped → empty."""

    ANCHOR = date(2041, 8, 25)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Only seed today + 2 prior days (below _MIN_HISTORY=3 for baseline)
            for i in range(3):
                d = (self.ANCHOR - timedelta(days=2 - i)).isoformat()
                s.merge(_daily(d, recovery=50.0))  # today crashes vs "baseline"
                s.merge(_sleep(d, performance=50.0))
            s.commit()

    def test_empty_with_insufficient_history(self, engine):
        # avg() requires ≥ 3 prior values; with only 2 prior days, all
        # factors are skipped and empty list is returned
        factors = get_limiting_factors(engine, None, self.ANCHOR)
        assert factors == []


# ---------------------------------------------------------------------------
# Helper to avoid magic numbers in tests
# ---------------------------------------------------------------------------


def _get_mild_threshold() -> float:
    from src.analytics.limiting_factors import _MILD_THRESHOLD

    return _MILD_THRESHOLD
