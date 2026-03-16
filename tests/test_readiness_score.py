"""Tests for src/analytics/readiness_score.py.

Covers:
- _normalize_hrv_trend: edge cases and z-score math
- _normalize_training_load: ratio → score mapping
- _get_recommendation: all four threshold bands
- _compute_from_data: weight redistribution, confidence, score math
- compute_readiness: full DB-backed integration
- get_readiness_history: date range output shape and ordering
"""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.readiness_score import (
    READINESS_WEIGHTS,
    ReadinessResult,
    _compute_from_data,
    _get_recommendation,
    _normalize_hrv_trend,
    _normalize_training_load,
    compute_readiness,
    get_readiness_history,
)
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, UnifiedSleep

IN_MEMORY = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW_ISO = datetime.now(UTC).isoformat()


def _daily(
    date_str: str,
    recovery: float | None = 75.0,
    hrv: float | None = 55.0,
    strain: float | None = 8.0,
    body_battery: int | None = 70,
) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        whoop_hrv_rmssd=hrv,
        whoop_strain=strain,
        garmin_body_battery_high=body_battery,
        data_sources='["whoop","garmin"]',
        last_updated=NOW_ISO,
    )


def _sleep(date_str: str, performance: float | None = 80.0) -> UnifiedSleep:
    return UnifiedSleep(
        date=date_str,
        whoop_performance=performance,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


def _row(**kwargs) -> dict:
    """Build a minimal unified_daily-style dict for pure-function tests."""
    defaults = {
        "whoop_recovery_score": None,
        "whoop_hrv_rmssd": None,
        "whoop_strain": None,
        "garmin_body_battery_high": None,
    }
    defaults.update(kwargs)
    return defaults


def _sleep_row(performance: float | None = None) -> dict:
    return {"whoop_performance": performance}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """Shared in-memory engine with all migrations applied."""
    eng = get_engine(IN_MEMORY)
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Fresh session per test, rolled back on teardown."""
    db = Session(engine)
    yield db
    db.rollback()
    db.close()


# ---------------------------------------------------------------------------
# _normalize_hrv_trend
# ---------------------------------------------------------------------------


class TestNormalizeHrvTrend:
    def test_returns_none_when_today_hrv_missing(self):
        assert _normalize_hrv_trend(None, [50.0, 52.0, 48.0, 55.0]) is None

    def test_returns_neutral_when_no_history(self):
        assert _normalize_hrv_trend(55.0, []) == 50.0

    def test_returns_neutral_when_insufficient_history(self):
        # < 3 valid values → neutral
        assert _normalize_hrv_trend(60.0, [50.0, 55.0]) == 50.0
        assert _normalize_hrv_trend(60.0, [50.0, None, None]) == 50.0

    def test_returns_neutral_when_zero_std(self):
        # All history identical → std = 0 → neutral
        assert _normalize_hrv_trend(60.0, [50.0, 50.0, 50.0, 50.0]) == 50.0

    def test_today_equals_mean_returns_50(self):
        history = [45.0, 50.0, 55.0, 50.0, 45.0, 55.0, 50.0]
        mean = sum(history) / len(history)  # 50.0
        result = _normalize_hrv_trend(mean, history)
        assert result == pytest.approx(50.0, abs=0.01)

    def test_two_std_above_mean_clamps_to_100(self):
        history = [45.0, 50.0, 55.0, 50.0, 45.0, 55.0, 50.0]
        mean = 50.0
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance)
        today = mean + 2 * std  # z = +2 → 100
        result = _normalize_hrv_trend(today, history)
        assert result == pytest.approx(100.0, abs=0.1)

    def test_two_std_below_mean_clamps_to_0(self):
        history = [45.0, 50.0, 55.0, 50.0, 45.0, 55.0, 50.0]
        mean = 50.0
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance)
        today = mean - 2 * std  # z = -2 → 0
        result = _normalize_hrv_trend(today, history)
        assert result == pytest.approx(0.0, abs=0.1)

    def test_one_std_above_returns_75(self):
        history = [45.0, 50.0, 55.0, 50.0, 45.0, 55.0, 50.0]
        mean = 50.0
        variance = sum((v - mean) ** 2 for v in history) / len(history)
        std = math.sqrt(variance)
        today = mean + std  # z = +1 → 75
        result = _normalize_hrv_trend(today, history)
        assert result == pytest.approx(75.0, abs=0.1)

    def test_none_values_in_history_are_ignored(self):
        # Same as zero-std test but with Nones mixed in
        history = [50.0, None, 50.0, None, 50.0, 50.0, None]
        # All valid = 50 → std = 0 → neutral
        assert _normalize_hrv_trend(60.0, history) == 50.0

    def test_output_always_in_0_100(self):
        history = [50.0, 52.0, 48.0, 51.0, 49.0, 50.0, 50.0]
        for today in [0.0, 200.0, -100.0]:
            result = _normalize_hrv_trend(today, history)
            assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# _normalize_training_load
# ---------------------------------------------------------------------------


class TestNormalizeTrainingLoad:
    def test_returns_none_when_no_data(self):
        assert _normalize_training_load([], []) is None
        assert _normalize_training_load([None, None], [None]) is None

    def test_returns_neutral_when_history_avg_is_zero(self):
        # All-zero history → neutral
        assert _normalize_training_load([5.0, 6.0, 7.0], [0.0, 0.0, 0.0]) == 50.0

    def test_returns_neutral_when_empty_history(self):
        # No history but some recent data → can't compute ratio → neutral
        assert _normalize_training_load([8.0, 9.0], []) == 50.0

    def test_ratio_1_returns_50(self):
        # recent_avg == history_avg → ratio = 1.0 → 50
        history = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
        recent = [10.0, 10.0, 10.0]
        assert _normalize_training_load(recent, history) == pytest.approx(50.0)

    def test_low_load_returns_above_50(self):
        # recent_avg = 5, history_avg = 10 → ratio = 0.5 → 75
        history = [10.0] * 7
        recent = [5.0, 5.0, 5.0]
        assert _normalize_training_load(recent, history) == pytest.approx(75.0)

    def test_double_load_clamps_to_0(self):
        # recent_avg = 20, history_avg = 10 → ratio = 2.0 → 0
        history = [10.0] * 7
        recent = [20.0, 20.0, 20.0]
        assert _normalize_training_load(recent, history) == pytest.approx(0.0)

    def test_very_high_load_clamps_to_0(self):
        history = [10.0] * 7
        recent = [100.0, 100.0, 100.0]
        assert _normalize_training_load(recent, history) == 0.0

    def test_zero_recent_returns_100(self):
        # Complete rest → ratio = 0 → 100
        history = [10.0] * 7
        recent = [0.0, 0.0, 0.0]
        assert _normalize_training_load(recent, history) == pytest.approx(100.0)

    def test_none_values_in_recent_ignored(self):
        history = [10.0] * 7
        # Only [10.0] is valid in recent → avg = 10 → ratio = 1 → 50
        assert _normalize_training_load([None, None, 10.0], history) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# _get_recommendation
# ---------------------------------------------------------------------------


class TestGetRecommendation:
    def test_80_and_above_push_hard(self):
        assert "Push hard" in _get_recommendation(80.0)
        assert "Push hard" in _get_recommendation(100.0)
        assert "Push hard" in _get_recommendation(95.5)

    def test_boundary_79_9_train_normally(self):
        assert "Train normally" in _get_recommendation(79.9)

    def test_60_to_79_train_normally(self):
        assert "Train normally" in _get_recommendation(60.0)
        assert "Train normally" in _get_recommendation(70.0)

    def test_boundary_59_9_go_easy(self):
        assert "Go easy" in _get_recommendation(59.9)

    def test_40_to_59_go_easy(self):
        assert "Go easy" in _get_recommendation(40.0)
        assert "Go easy" in _get_recommendation(50.0)

    def test_boundary_39_9_rest_day(self):
        assert "Rest day" in _get_recommendation(39.9)

    def test_0_to_39_rest_day(self):
        assert "Rest day" in _get_recommendation(0.0)
        assert "Rest day" in _get_recommendation(20.0)
        assert "Rest day" in _get_recommendation(39.0)


# ---------------------------------------------------------------------------
# _compute_from_data — weight redistribution and score math
# ---------------------------------------------------------------------------


class TestComputeFromData:
    TARGET = date(2026, 2, 15)

    def _build_daily_dict(self, target: date, **kwargs) -> dict[str, dict]:
        """Build daily_by_date with today + 7 history rows all using defaults."""
        rows = {}
        for i in range(8):
            d = (target - timedelta(days=i)).isoformat()
            rows[d] = _row(
                whoop_recovery_score=kwargs.get("recovery", 75.0),
                whoop_hrv_rmssd=kwargs.get("hrv", 55.0),
                whoop_strain=kwargs.get("strain", 8.0),
                garmin_body_battery_high=kwargs.get("body_battery", 70),
            )
        return rows

    def test_returns_readiness_result(self):
        daily = self._build_daily_dict(self.TARGET)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert isinstance(result, ReadinessResult)

    def test_all_components_confidence_1(self):
        daily = self._build_daily_dict(self.TARGET)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert result.confidence == pytest.approx(1.0, abs=0.001)

    def test_all_components_effective_weights_sum_to_1(self):
        daily = self._build_daily_dict(self.TARGET)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        total_eff = sum(v["effective_weight"] for v in result.contributing_factors.values())
        assert total_eff == pytest.approx(1.0, abs=0.001)

    def test_missing_body_battery_redistributes_weight(self):
        daily = self._build_daily_dict(self.TARGET, body_battery=None)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        # body_battery should have effective_weight 0
        assert result.contributing_factors["body_battery"]["effective_weight"] == 0.0
        # confidence = sum of available weights = 1 - 0.15
        assert result.confidence == pytest.approx(0.85, abs=0.001)
        # remaining effective weights should sum to 1
        total_eff = sum(v["effective_weight"] for v in result.contributing_factors.values())
        assert total_eff == pytest.approx(1.0, abs=0.001)

    def test_missing_whoop_recovery_redistributes_weight(self):
        daily = self._build_daily_dict(self.TARGET, recovery=None)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert result.contributing_factors["whoop_recovery"]["effective_weight"] == 0.0
        assert result.confidence == pytest.approx(0.75, abs=0.001)

    def test_only_whoop_recovery_present(self):
        # All other fields None — only recovery contributes
        daily = {self.TARGET.isoformat(): _row(whoop_recovery_score=80.0)}
        result = _compute_from_data(self.TARGET, daily, {})
        assert result.score == pytest.approx(80.0, abs=0.5)
        assert result.confidence == pytest.approx(READINESS_WEIGHTS["whoop_recovery"], abs=0.001)

    def test_only_body_battery_present(self):
        daily = {self.TARGET.isoformat(): _row(garmin_body_battery_high=60)}
        result = _compute_from_data(self.TARGET, daily, {})
        assert result.score == pytest.approx(60.0, abs=0.5)
        assert result.confidence == pytest.approx(READINESS_WEIGHTS["body_battery"], abs=0.001)

    def test_no_data_returns_none_score_confidence_0(self):
        result = _compute_from_data(self.TARGET, {}, {})
        assert result.score is None
        assert result.confidence == 0.0

    def test_score_clamped_0_to_100(self):
        # All components at 100 → score should be 100
        daily = self._build_daily_dict(
            self.TARGET, recovery=100.0, hrv=200.0, body_battery=100, strain=0.0
        )
        sleep = {self.TARGET.isoformat(): _sleep_row(100.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert 0.0 <= result.score <= 100.0

    def test_all_components_have_required_keys(self):
        daily = self._build_daily_dict(self.TARGET)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        required_keys = {"name", "raw_value", "normalized_value", "weight", "effective_weight"}
        for key, component in result.contributing_factors.items():
            assert required_keys.issubset(component.keys()), f"Component '{key}' missing keys"

    def test_custom_weights_applied(self):
        # Give recovery weight=1.0 and everything else 0 — score should equal recovery
        custom = {k: 0.0 for k in READINESS_WEIGHTS}
        custom["whoop_recovery"] = 1.0
        daily = self._build_daily_dict(self.TARGET, recovery=65.0)
        sleep = {self.TARGET.isoformat(): _sleep_row(80.0)}
        result = _compute_from_data(self.TARGET, daily, sleep, weights=custom)
        assert result.score == pytest.approx(65.0, abs=0.5)

    def test_high_readiness_day_recommendation(self):
        # All sources pointing to great recovery.
        # HRV history has variance so today's elevated HRV registers as positive.
        # Strain history is higher than recent load so training_load scores well.
        hrv_history = [52.0, 56.0, 50.0, 54.0, 58.0, 51.0, 55.0]  # mean≈53.7, std≈2.6
        daily = {}
        for i in range(8):
            d = (self.TARGET - timedelta(days=i)).isoformat()
            if i == 0:  # today: HRV well above history avg, low recent strain
                daily[d] = _row(
                    whoop_recovery_score=92.0,
                    whoop_hrv_rmssd=85.0,  # z ≈ +12 → clamped to 100
                    whoop_strain=3.0,
                    garmin_body_battery_high=95,
                )
            else:  # history: elevated average strain so recent looks light
                daily[d] = _row(
                    whoop_recovery_score=92.0,
                    whoop_hrv_rmssd=hrv_history[i - 1],
                    whoop_strain=12.0,  # high history avg → recent ratio ≈ 0.25 → load ≈ 87.5
                    garmin_body_battery_high=95,
                )
        sleep = {self.TARGET.isoformat(): _sleep_row(90.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert result.score >= 80.0
        assert "Push hard" in result.recommendation

    def test_low_readiness_day_recommendation(self):
        # All sources pointing to poor recovery
        daily = {}
        for i in range(8):
            d = (self.TARGET - timedelta(days=i)).isoformat()
            daily[d] = _row(
                whoop_recovery_score=22.0,
                whoop_hrv_rmssd=55.0 if i > 0 else 35.0,  # today well below avg
                whoop_strain=18.0,  # high recent load
                garmin_body_battery_high=15,
            )
        sleep = {self.TARGET.isoformat(): _sleep_row(40.0)}
        result = _compute_from_data(self.TARGET, daily, sleep)
        assert result.score < 40.0
        assert "Rest day" in result.recommendation


# ---------------------------------------------------------------------------
# compute_readiness — DB integration
# ---------------------------------------------------------------------------


class TestComputeReadiness:
    TARGET = date(2026, 1, 20)

    def _insert_window(self, session, target: date, **kwargs):
        """Insert 8 daily rows (today + 7 history) and one sleep row."""
        for i in range(8):
            d = (target - timedelta(days=i)).isoformat()
            session.merge(
                _daily(
                    d,
                    recovery=kwargs.get("recovery", 75.0),
                    hrv=kwargs.get("hrv_history", 55.0) if i > 0 else kwargs.get("hrv_today", 55.0),
                    strain=kwargs.get("strain", 8.0),
                    body_battery=kwargs.get("body_battery", 70),
                )
            )
        session.merge(_sleep(target.isoformat(), kwargs.get("sleep", 80.0)))
        session.commit()

    def test_returns_readiness_result_type(self, engine):
        with Session(engine) as s:
            self._insert_window(s, self.TARGET)
        result = compute_readiness(self.TARGET, engine)
        assert isinstance(result, ReadinessResult)
        assert result.date == self.TARGET

    def test_score_in_valid_range(self, engine):
        with Session(engine) as s:
            self._insert_window(s, self.TARGET)
        result = compute_readiness(self.TARGET, engine)
        assert 0.0 <= result.score <= 100.0

    def test_high_readiness_scenario(self, engine):
        target = date(2026, 1, 10)
        with Session(engine) as s:
            self._insert_window(
                s,
                target,
                recovery=90.0,
                hrv_history=55.0,
                hrv_today=70.0,  # well above average
                strain=3.0,  # low load
                body_battery=90,
                sleep=90.0,
            )
        result = compute_readiness(target, engine)
        assert result.score >= 70.0  # should be high
        assert result.confidence == pytest.approx(1.0, abs=0.001)

    def test_low_readiness_scenario(self, engine):
        target = date(2026, 1, 11)
        with Session(engine) as s:
            self._insert_window(
                s,
                target,
                recovery=20.0,
                hrv_history=65.0,
                hrv_today=45.0,  # well below average
                strain=18.0,  # heavy load
                body_battery=10,
                sleep=35.0,
            )
        result = compute_readiness(target, engine)
        assert result.score < 50.0
        assert result.confidence == pytest.approx(1.0, abs=0.001)

    def test_missing_garmin_data(self, engine):
        target = date(2026, 1, 12)
        with Session(engine) as s:
            for i in range(8):
                d = (target - timedelta(days=i)).isoformat()
                session_obj = s
                session_obj.merge(_daily(d, recovery=75.0, hrv=55.0, strain=8.0, body_battery=None))
            s.merge(_sleep(target.isoformat(), 80.0))
            s.commit()
        result = compute_readiness(target, engine)
        # body_battery weight redistributed; confidence < 1
        assert result.confidence == pytest.approx(0.85, abs=0.001)
        assert result.contributing_factors["body_battery"]["effective_weight"] == 0.0

    def test_date_with_no_data_returns_none_score(self, engine):
        # Date far in the future — no rows in DB
        target = date(2099, 12, 31)
        result = compute_readiness(target, engine)
        assert result.score is None
        assert result.confidence == 0.0

    def test_custom_weights_accepted(self, engine):
        target = date(2026, 1, 13)
        with Session(engine) as s:
            self._insert_window(s, target, recovery=80.0)
        custom = {k: 0.0 for k in READINESS_WEIGHTS}
        custom["whoop_recovery"] = 1.0
        result = compute_readiness(target, engine, weights=custom)
        assert result.score == pytest.approx(80.0, abs=1.0)


# ---------------------------------------------------------------------------
# get_readiness_history
# ---------------------------------------------------------------------------


class TestGetReadinessHistory:
    START = date(2026, 3, 1)
    END = date(2026, 3, 7)

    def _insert_range(self, session, start: date, end: date):
        current = start - timedelta(days=7)  # pre-load history window too
        while current <= end:
            d = current.isoformat()
            session.merge(_daily(d))
            session.merge(_sleep(d))
            current += timedelta(days=1)
        session.commit()

    def test_returns_correct_number_of_entries(self, engine):
        with Session(engine) as s:
            self._insert_range(s, self.START, self.END)
        results = get_readiness_history(self.START, self.END, engine)
        expected_days = (self.END - self.START).days + 1
        assert len(results) == expected_days

    def test_dates_are_sequential_ascending(self, engine):
        with Session(engine) as s:
            self._insert_range(s, self.START, self.END)
        results = get_readiness_history(self.START, self.END, engine)
        dates = [r["date"] for r in results]
        assert dates == sorted(dates)
        assert dates[0] == self.START.isoformat()
        assert dates[-1] == self.END.isoformat()

    def test_each_entry_has_required_fields(self, engine):
        with Session(engine) as s:
            self._insert_range(s, self.START, self.END)
        results = get_readiness_history(self.START, self.END, engine)
        for entry in results:
            assert "date" in entry
            assert "score" in entry
            assert "recommendation" in entry
            assert "confidence" in entry

    def test_scores_in_valid_range(self, engine):
        with Session(engine) as s:
            self._insert_range(s, self.START, self.END)
        results = get_readiness_history(self.START, self.END, engine)
        for entry in results:
            assert 0.0 <= entry["score"] <= 100.0
            assert 0.0 <= entry["confidence"] <= 1.0

    def test_single_date_range(self, engine):
        target = date(2026, 3, 5)
        with Session(engine) as s:
            self._insert_range(s, target, target)
        results = get_readiness_history(target, target, engine)
        assert len(results) == 1
        assert results[0]["date"] == target.isoformat()

    def test_no_data_returns_empty_list(self, engine):
        # Date range with no DB rows → empty list (confidence==0 entries are filtered)
        start = date(2099, 1, 1)
        end = date(2099, 1, 3)
        results = get_readiness_history(start, end, engine)
        assert results == []

    def test_custom_weights_propagated(self, engine):
        with Session(engine) as s:
            self._insert_range(s, self.START, self.END)
        custom = {k: 0.0 for k in READINESS_WEIGHTS}
        custom["whoop_recovery"] = 1.0
        results = get_readiness_history(self.START, self.END, engine, weights=custom)
        # With recovery=75 as only source, all scores should be ~75
        for entry in results:
            assert entry["score"] == pytest.approx(75.0, abs=1.0)
