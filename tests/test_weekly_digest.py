"""Tests for src/analytics/weekly_digest.py.

Isolation strategy
------------------
All tests share one module-scoped in-memory SQLite engine.
Each test class uses non-overlapping anchor windows in 2043.

Pure-function test classes (no DB):
  TestPrevVal          — _prev_val helper
  TestSleepDebtStatus  — _sleep_debt_status helper
  TestReadinessCandidate — template text for big decline / gain / stable
  TestTrainingCandidate  — overreaching, volume-up, volume-down, stable
  TestSleepCandidate     — improved, declined (with debt), stable
  TestRecoveryCandidate  — decline, gain, no-change
  TestSelectTakeaways    — deduplication, max_n, ordering

DB-backed test classes:
  TestNoData              — anchor 2043-01-15  (empty DB → fallback takeaway)
  TestRecoveryDecline     — anchor 2043-03-10  (curr recovery << prev → sluggish)
  TestOverreachingWarning — anchor 2043-05-01  (ACWR in overreaching zone)
  TestMetricsSnapshot     — anchor 2043-06-20  (snapshot has expected keys)
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.analytics.weekly_digest import (
    WeeklyDigest,
    _Candidate,
    _prev_val,
    _readiness_candidate,
    _recovery_candidate,
    _select_takeaways,
    _sleep_candidate,
    _sleep_debt_status,
    _training_candidate,
    get_weekly_digest,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, UnifiedWorkout

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


def _daily(date_str: str, recovery: float = 75.0) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        data_sources='["whoop"]',
        last_updated=NOW_ISO,
    )


def _workout(date_str: str, strain: float, uid: int = 0) -> UnifiedWorkout:
    return UnifiedWorkout(
        id=f"w_{date_str}_{strain}_{uid}",
        date=date_str,
        start_time=f"{date_str}T08:00:00",
        whoop_strain=strain,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestPrevVal:
    def test_positive_delta(self):
        # curr=100, delta=+25% → prev=80
        assert _prev_val(100.0, 25.0) == pytest.approx(80.0, abs=0.1)

    def test_negative_delta(self):
        # curr=75, delta=-25% → prev=100
        assert _prev_val(75.0, -25.0) == pytest.approx(100.0, abs=0.1)

    def test_zero_delta(self):
        assert _prev_val(70.0, 0.0) == pytest.approx(70.0, abs=0.1)

    def test_none_curr(self):
        assert _prev_val(None, 10.0) is None

    def test_none_delta(self):
        assert _prev_val(80.0, None) is None


class TestSleepDebtStatus:
    def test_accumulating_below_6_5(self):
        assert _sleep_debt_status(6.0) == "accumulating"

    def test_manageable_range(self):
        assert _sleep_debt_status(7.0) == "manageable"

    def test_good_shape_above_7_5(self):
        assert _sleep_debt_status(8.0) == "in good shape"

    def test_boundary_6_5_is_manageable(self):
        assert _sleep_debt_status(6.5) == "manageable"

    def test_boundary_7_5_is_good_shape(self):
        assert _sleep_debt_status(7.5) == "in good shape"


class TestReadinessCandidate:
    def test_big_decline_contains_dropped(self):
        c = _readiness_candidate(55.0, -25.0)
        assert c is not None
        assert "dropped" in c.text.lower()

    def test_big_decline_contains_value(self):
        c = _readiness_candidate(55.0, -25.0)
        assert "55%" in c.text

    def test_big_decline_includes_limiting_factor(self):
        c = _readiness_candidate(55.0, -25.0, limiting_factor="Sleep Quality")
        assert "Sleep Quality" in c.text

    def test_big_decline_score_above_70(self):
        c = _readiness_candidate(55.0, -25.0)
        assert c.score >= 70.0

    def test_big_improvement_contains_up(self):
        c = _readiness_candidate(82.0, +18.0)
        assert c is not None
        assert "up from" in c.text.lower()

    def test_big_improvement_score_above_60(self):
        c = _readiness_candidate(82.0, +18.0)
        assert c.score >= 60.0

    def test_stable_contains_steady(self):
        c = _readiness_candidate(75.0, 4.0)
        assert c is not None
        assert "steady" in c.text.lower()

    def test_stable_score_below_30(self):
        c = _readiness_candidate(75.0, 4.0)
        assert c.score < 30.0

    def test_none_readiness_returns_none(self):
        assert _readiness_candidate(None, 10.0) is None

    def test_none_delta_falls_through_to_stable(self):
        # None delta → no big change detected → stable template
        c = _readiness_candidate(70.0, None)
        assert c is not None
        assert "steady" in c.text.lower()


class TestTrainingCandidate:
    def _acwr(self, acwr_val: float | None, zone: str | None) -> MagicMock:
        m = MagicMock()
        m.acwr = acwr_val
        m.zone = zone
        return m

    def test_overreaching_zone_score_100(self):
        c = _training_candidate(5, 300.0, 4, self._acwr(1.4, "overreaching"))
        assert c is not None
        assert c.score == 100.0

    def test_overreaching_text(self):
        c = _training_candidate(5, 300.0, 4, self._acwr(1.4, "overreaching"))
        assert "overreaching" in c.text.lower()
        assert "1.40" in c.text

    def test_danger_zone_score_100(self):
        c = _training_candidate(7, 420.0, 5, self._acwr(2.1, "danger"))
        assert c.score == 100.0
        assert "overreaching" in c.text.lower()

    def test_volume_up_contains_up_from(self):
        c = _training_candidate(10, 600.0, 6, self._acwr(1.1, "sweet_spot"))
        assert c is not None
        assert "up from 6" in c.text

    def test_volume_up_score_above_40(self):
        c = _training_candidate(10, 600.0, 6, self._acwr(1.1, "sweet_spot"))
        assert c.score > 40.0

    def test_volume_down_contains_lighter(self):
        c = _training_candidate(3, 180.0, 8, self._acwr(0.7, "recovery"))
        assert c is not None
        assert "lighter" in c.text.lower()

    def test_stable_score_below_30(self):
        c = _training_candidate(5, 300.0, 5, None)
        assert c is not None
        assert c.score < 30.0

    def test_no_acwr_shows_na(self):
        c = _training_candidate(4, 240.0, None, None)
        assert "N/A" in c.text

    def test_singular_session_grammar(self):
        c = _training_candidate(1, 60.0, 0, None)
        assert "1 session" in c.text
        assert "sessions" not in c.text


class TestSleepCandidate:
    def test_improved_contains_better(self):
        c = _sleep_candidate(480.0, 120.0, +15.0)
        assert c is not None
        assert "better" in c.text.lower()

    def test_improved_includes_hours(self):
        c = _sleep_candidate(480.0, 120.0, +15.0)
        assert "8.0h" in c.text

    def test_improved_includes_deep_pct(self):
        c = _sleep_candidate(480.0, 120.0, +15.0)
        assert "25%" in c.text  # 120/480=25%

    def test_declined_contains_dropped(self):
        c = _sleep_candidate(360.0, 72.0, -20.0)
        assert c is not None
        assert "dropped" in c.text.lower()

    def test_declined_includes_debt_status(self):
        # 6h = accumulating
        c = _sleep_candidate(360.0, 72.0, -20.0)
        assert "accumulating" in c.text.lower()

    def test_declined_manageable_debt(self):
        # 7h = manageable
        c = _sleep_candidate(420.0, 84.0, -12.0)
        assert "manageable" in c.text.lower()

    def test_declined_score_above_60(self):
        c = _sleep_candidate(360.0, 72.0, -20.0)
        assert c.score > 60.0

    def test_stable_score_below_20(self):
        c = _sleep_candidate(450.0, 90.0, 3.0)
        assert c is not None
        assert c.score < 20.0

    def test_none_sleep_returns_none(self):
        assert _sleep_candidate(None, None, None) is None


class TestRecoveryCandidate:
    def test_decline_contains_sluggish(self):
        c = _recovery_candidate(45.0, -30.0)
        assert c is not None
        assert "sluggish" in c.text.lower()

    def test_decline_with_limiting_factor(self):
        c = _recovery_candidate(45.0, -30.0, limiting_factor="HRV Trend")
        assert "HRV Trend" in c.text

    def test_decline_score_above_80(self):
        c = _recovery_candidate(45.0, -30.0)
        assert c.score > 80.0

    def test_gain_contains_up(self):
        c = _recovery_candidate(85.0, +20.0)
        assert c is not None
        assert "up" in c.text.lower()

    def test_stable_returns_none(self):
        # small delta — duplicate of readiness, so returns None
        c = _recovery_candidate(70.0, 3.0)
        assert c is None

    def test_none_recovery_returns_none(self):
        assert _recovery_candidate(None, -20.0) is None


class TestSelectTakeaways:
    def test_deduplicates_by_category(self):
        candidates = [
            _Candidate("A", score=90.0, category="readiness"),
            _Candidate("B", score=80.0, category="readiness"),  # dup
            _Candidate("C", score=70.0, category="training"),
        ]
        result = _select_takeaways(candidates, max_n=3)
        assert len(result) == 2
        assert "A" in result
        assert "C" in result
        assert "B" not in result

    def test_max_n_respected(self):
        candidates = [
            _Candidate("A", score=90.0, category="readiness"),
            _Candidate("B", score=80.0, category="training"),
            _Candidate("C", score=70.0, category="sleep"),
            _Candidate("D", score=60.0, category="recovery"),
        ]
        result = _select_takeaways(candidates, max_n=2)
        assert len(result) == 2
        assert "A" in result
        assert "B" in result

    def test_sorted_highest_score_first(self):
        candidates = [
            _Candidate("Low", score=10.0, category="training"),
            _Candidate("High", score=90.0, category="readiness"),
            _Candidate("Mid", score=50.0, category="sleep"),
        ]
        result = _select_takeaways(candidates, max_n=3)
        assert result[0] == "High"
        assert result[1] == "Mid"
        assert result[2] == "Low"

    def test_empty_candidates_returns_empty(self):
        assert _select_takeaways([], max_n=3) == []


# ---------------------------------------------------------------------------
# DB-backed integration tests
# ---------------------------------------------------------------------------


class TestNoData:
    """Empty DB → fallback takeaway is returned; result is a WeeklyDigest."""

    ANCHOR = date(2043, 1, 15)

    def test_returns_weekly_digest_instance(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert isinstance(result, WeeklyDigest)

    def test_takeaways_not_empty(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert len(result.takeaways) >= 1

    def test_week_start_and_end(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert result.week_end == self.ANCHOR
        assert result.week_start == self.ANCHOR - timedelta(days=6)

    def test_metrics_snapshot_is_dict(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert isinstance(result.metrics_snapshot, dict)


class TestRecoveryDecline:
    """Current-week recovery << prior-week recovery → sluggish recovery takeaway."""

    ANCHOR = date(2043, 3, 10)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Prior week: recovery=80
            prev_end = self.ANCHOR - timedelta(days=7)
            for i in range(7):
                d = (prev_end - timedelta(days=6 - i)).isoformat()
                s.merge(_daily(d, recovery=80.0))
            # Current week: recovery=48
            for i in range(7):
                d = (self.ANCHOR - timedelta(days=6 - i)).isoformat()
                s.merge(_daily(d, recovery=48.0))
            s.commit()

    def test_recovery_takeaway_present(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        combined = " ".join(result.takeaways).lower()
        assert "sluggish" in combined or "recovery" in combined

    def test_recovery_value_in_takeaway(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        combined = " ".join(result.takeaways)
        assert "48%" in combined

    def test_recovery_takeaway_is_first(self, engine):
        # Recovery decline (score=85) should beat training stable (score=20)
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert (
            "sluggish" in result.takeaways[0].lower() or "recovery" in result.takeaways[0].lower()
        )

    def test_at_most_three_takeaways(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert len(result.takeaways) <= 3


class TestOverreachingWarning:
    """ACWR > 1.5 (danger zone) → overreaching warning is first takeaway."""

    ANCHOR = date(2043, 5, 1)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # 21 low-strain days (chronic baseline): strain=5 each
            for i in range(21):
                d = (self.ANCHOR - timedelta(days=27 - i)).isoformat()
                s.merge(_workout(d, strain=5.0, uid=i))
            # 7 high-strain days (current week): strain=15 each
            # ACWR ≈ 15 / 7.5 = 2.0 → "danger"
            for i in range(7):
                d = (self.ANCHOR - timedelta(days=6 - i)).isoformat()
                s.merge(_workout(d, strain=15.0, uid=100 + i))
            s.commit()

    def test_overreaching_in_first_takeaway(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert "overreaching" in result.takeaways[0].lower()

    def test_acwr_value_in_takeaway(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        # ACWR ≈ 2.0 — some decimal representation should appear
        combined = " ".join(result.takeaways)
        # Just check a number resembling 2.0x is present
        import re

        assert re.search(r"\d+\.\d+", combined), "Expected numeric ACWR in takeaway"

    def test_returns_at_most_three(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert len(result.takeaways) <= 3


class TestMetricsSnapshot:
    """Metrics snapshot contains all expected keys regardless of data."""

    ANCHOR = date(2043, 6, 20)

    _EXPECTED_KEYS = {
        "avg_readiness",
        "avg_recovery",
        "avg_hrv",
        "total_strain",
        "workout_count",
        "total_training_hours",
        "avg_sleep_hours",
        "avg_deep_sleep_minutes",
        "acwr",
        "acwr_zone",
    }

    def test_all_expected_keys_present(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert self._EXPECTED_KEYS.issubset(result.metrics_snapshot.keys())

    def test_workout_count_is_int(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        assert isinstance(result.metrics_snapshot["workout_count"], int)

    def test_week_dates_span_seven_days(self, engine):
        result = get_weekly_digest(engine, None, self.ANCHOR)
        delta = result.week_end - result.week_start
        assert delta.days == 6  # 7 days inclusive = 6-day span
