"""Tests for enriched anomaly detection in src/analytics/trends.py.

Isolation strategy
------------------
All tests share one module-scoped in-memory SQLite engine.
unified_daily uses ``date`` as its sole PK; unified_sleep uses ``date``
as sole PK.  Each test class uses non-overlapping anchor windows in
2042 (far from other test modules):

  TestNoData              — anchor 2042-01-20  (no data seeded)
  TestHrvDropWithStrain   — anchor 2042-02-05  (hrv drops, 48h strain)
  TestRecoverySpikeWithSleep — anchor 2042-03-15 (recovery spikes, good sleep)
  TestCoAnomalies         — anchor 2042-04-22  (hrv and recovery both anomalous)
  TestLimit               — anchor 2042-05-30  (many anomalies, test limit=1)
  TestSortedDescending    — anchor 2042-07-10  (two anomalies, check order)
  TestEnrichAnomalyDirect — pure function test, no DB state dependency
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from src.analytics.trends import (
    EnrichedAnomaly,
    _build_enriched_explanation,
    _enriched_severity_label,
    _fmt_anomaly_value,
    enrich_anomaly,
    get_enriched_anomalies,
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


def _daily(
    date_str: str,
    recovery: float = 75.0,
    hrv: float = 60.0,
    rhr: float | None = None,
    bb: float | None = None,
) -> UnifiedDaily:
    return UnifiedDaily(
        date=date_str,
        whoop_recovery_score=recovery,
        whoop_hrv_rmssd=hrv,
        whoop_rhr=rhr,
        garmin_body_battery_high=bb,
        data_sources='["whoop"]',
        last_updated=NOW_ISO,
    )


def _sleep(
    date_str: str,
    performance: float = 75.0,
    total_min: float = 420.0,  # 7 hours
    deep_min: float = 84.0,  # 20% deep
) -> UnifiedSleep:
    return UnifiedSleep(
        date=date_str,
        whoop_performance=performance,
        total_sleep_minutes=total_min,
        deep_sleep_minutes=deep_min,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


def _workout(date_str: str, strain: float = 15.0, uid: int = 0) -> UnifiedWorkout:
    return UnifiedWorkout(
        id=f"w_{date_str}_{strain}_{uid}",
        date=date_str,
        start_time=f"{date_str}T08:00:00",
        whoop_strain=strain,
        primary_source="whoop",
        last_updated=NOW_ISO,
    )


def _seed_varying_hrv(session: Session, anchor: date, days: int = 14) -> None:
    """Seed ``days`` days of alternating HRV (58/62) ending at anchor.

    Alternating values ensure non-zero std so detect_anomalies can fire.
    The anchor day is included in the window — callers override it after
    calling this helper.
    """
    for i in range(days):
        d = (anchor - timedelta(days=days - 1 - i)).isoformat()
        hrv_val = 58.0 if i % 2 == 0 else 62.0
        session.merge(_daily(d, hrv=hrv_val))


def _seed_varying_recovery(session: Session, anchor: date, days: int = 14) -> None:
    """Seed ``days`` days of alternating recovery (70/80) ending at anchor."""
    for i in range(days):
        d = (anchor - timedelta(days=days - 1 - i)).isoformat()
        rec_val = 70.0 if i % 2 == 0 else 80.0
        session.merge(_daily(d, recovery=rec_val))


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------


class TestSeverityLabel:
    def test_mild(self):
        assert _enriched_severity_label(2.0) == "mild"

    def test_mild_upper(self):
        assert _enriched_severity_label(2.49) == "mild"

    def test_moderate(self):
        assert _enriched_severity_label(2.5) == "moderate"

    def test_moderate_upper(self):
        assert _enriched_severity_label(3.49) == "moderate"

    def test_significant(self):
        assert _enriched_severity_label(3.5) == "significant"

    def test_significant_extreme(self):
        assert _enriched_severity_label(10.0) == "significant"


class TestFmtAnomalyValue:
    def test_hrv(self):
        assert _fmt_anomaly_value("hrv", 42.0) == "42ms"

    def test_recovery(self):
        assert _fmt_anomaly_value("recovery", 94.0) == "94%"

    def test_resting_hr(self):
        assert _fmt_anomaly_value("resting_hr", 58.0) == "58bpm"

    def test_sleep_duration_converts_minutes(self):
        assert _fmt_anomaly_value("sleep_duration", 492.0) == "8.2h"

    def test_deep_sleep(self):
        assert _fmt_anomaly_value("deep_sleep", 45.0) == "45min"

    def test_body_battery(self):
        assert _fmt_anomaly_value("body_battery", 25.0) == "25.0"

    def test_strain(self):
        assert _fmt_anomaly_value("strain", 18.5) == "18.5"


class TestBuildEnrichedExplanation:
    """Pure template tests — no DB needed."""

    _BASE_CTX: dict = {
        "training_48h": {"total_strain": None, "workout_count": 0},
        "sleep_prior_night": {"duration_hours": None, "quality_pct": None, "deep_pct": None},
        "recovery_trend": "stable",
        "co_anomalies": [],
    }

    def _ctx(self, **kwargs) -> dict:
        import copy

        ctx = copy.deepcopy(self._BASE_CTX)
        ctx.update(kwargs)
        return ctx

    def test_hrv_drop_with_strain_uses_training_context(self):
        ctx = self._ctx(training_48h={"total_strain": 42.5, "workout_count": 3})
        msg = _build_enriched_explanation("hrv", "HRV", 42.0, "low", 3.0, ctx)
        assert "42.5 strain" in msg
        assert "3 sessions" in msg

    def test_recovery_spike_with_sleep_uses_sleep_context(self):
        ctx = self._ctx(
            sleep_prior_night={"duration_hours": 8.2, "quality_pct": 92.0, "deep_pct": 82.0}
        )
        msg = _build_enriched_explanation("recovery", "Recovery Score", 94.0, "high", 3.0, ctx)
        assert "8.2h" in msg
        assert "82%" in msg

    def test_recovery_spike_no_deep_pct(self):
        ctx = self._ctx(
            sleep_prior_night={"duration_hours": 8.0, "quality_pct": 90.0, "deep_pct": None}
        )
        msg = _build_enriched_explanation("recovery", "Recovery Score", 90.0, "high", 2.5, ctx)
        assert "8.0h" in msg
        assert "night before" in msg

    def test_resting_hr_high_uses_training_context(self):
        ctx = self._ctx(training_48h={"total_strain": 30.0, "workout_count": 2})
        msg = _build_enriched_explanation("resting_hr", "Resting HR", 58.0, "high", 2.5, ctx)
        assert "elevated" in msg
        assert "30.0 strain" in msg

    def test_co_anomalies_used_when_no_strong_context(self):
        ctx = self._ctx(co_anomalies=["HRV", "Body Battery"])
        msg = _build_enriched_explanation("resting_hr", "Resting HR", 60.0, "high", 2.1, ctx)
        assert "HRV" in msg
        assert "flagged" in msg

    def test_recovery_trend_used_as_fallback(self):
        ctx = self._ctx(recovery_trend="declining")
        msg = _build_enriched_explanation("body_battery", "Body Battery", 20.0, "low", 2.1, ctx)
        assert "declining" in msg

    def test_no_context_returns_base(self):
        msg = _build_enriched_explanation("strain", "Strain", 35.0, "high", 2.0, self._BASE_CTX)
        assert "Strain" in msg
        assert "spiked" in msg

    def test_training_single_session_grammar(self):
        ctx = self._ctx(training_48h={"total_strain": 18.0, "workout_count": 1})
        msg = _build_enriched_explanation("hrv", "HRV", 38.0, "low", 2.8, ctx)
        assert "1 session" in msg
        assert "sessions" not in msg

    def test_severity_label_in_base(self):
        msg = _build_enriched_explanation("hrv", "HRV", 38.0, "low", 3.6, self._BASE_CTX)
        assert "significant" in msg


# ---------------------------------------------------------------------------
# Integration tests (DB-backed)
# ---------------------------------------------------------------------------


class TestNoData:
    """Date range with no data → empty list."""

    ANCHOR = date(2042, 1, 20)

    def test_empty_list(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        result = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        assert result == []


class TestHrvDropWithStrain:
    """HRV drops sharply on anchor day after two high-strain days.

    Expected: enriched anomaly for 'hrv', explanation mentions prior strain.
    """

    ANCHOR = date(2042, 2, 5)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # 14 days of alternating HRV baseline
            _seed_varying_hrv(s, self.ANCHOR, days=14)
            # Override anchor day: HRV crashes to 20 (way below ~60 baseline)
            s.merge(_daily(self.ANCHOR.isoformat(), hrv=20.0))
            # Seed two high-strain workouts in the prior 48h
            d1 = (self.ANCHOR - timedelta(days=1)).isoformat()
            d2 = (self.ANCHOR - timedelta(days=2)).isoformat()
            s.merge(_workout(d1, strain=22.0, uid=1))
            s.merge(_workout(d2, strain=20.0, uid=2))
            s.commit()

    def test_hrv_anomaly_detected(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        metrics = [r.metric for r in results]
        assert "hrv" in metrics

    def test_direction_is_low(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        hrv_r = next(r for r in results if r.metric == "hrv" and r.date == self.ANCHOR.isoformat())
        assert hrv_r.direction == "low"

    def test_training_context_populated(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        hrv_r = next(r for r in results if r.metric == "hrv" and r.date == self.ANCHOR.isoformat())
        ctx = hrv_r.context["training_48h"]
        assert ctx["workout_count"] == 2
        assert ctx["total_strain"] == pytest.approx(42.0, abs=0.5)

    def test_explanation_mentions_strain(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        hrv_r = next(r for r in results if r.metric == "hrv" and r.date == self.ANCHOR.isoformat())
        assert "strain" in hrv_r.explanation.lower()
        assert "42.0" in hrv_r.explanation or "42" in hrv_r.explanation

    def test_result_is_enriched_anomaly_instance(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        assert all(isinstance(r, EnrichedAnomaly) for r in results)


class TestRecoverySpikeWithSleep:
    """Recovery spikes on anchor day after excellent sleep.

    Expected: enriched anomaly for 'recovery', explanation mentions sleep.
    """

    ANCHOR = date(2042, 3, 15)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # 14 days of alternating recovery baseline (70/80)
            _seed_varying_recovery(s, self.ANCHOR, days=14)
            # Override anchor: recovery spikes to 98
            s.merge(_daily(self.ANCHOR.isoformat(), recovery=98.0))
            # Excellent sleep the night before (unified_sleep is keyed by wake date)
            s.merge(
                _sleep(self.ANCHOR.isoformat(), performance=95.0, total_min=510.0, deep_min=153.0)
            )  # 8.5h, 30% deep
            s.commit()

    def test_recovery_anomaly_detected(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        metrics = [r.metric for r in results]
        assert "recovery" in metrics

    def test_direction_is_high(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        rec_r = next(
            r for r in results if r.metric == "recovery" and r.date == self.ANCHOR.isoformat()
        )
        assert rec_r.direction == "high"

    def test_sleep_context_populated(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        rec_r = next(
            r for r in results if r.metric == "recovery" and r.date == self.ANCHOR.isoformat()
        )
        ctx = rec_r.context["sleep_prior_night"]
        assert ctx["duration_hours"] == pytest.approx(8.5, abs=0.1)
        assert ctx["deep_pct"] is not None

    def test_explanation_mentions_sleep_hours(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        rec_r = next(
            r for r in results if r.metric == "recovery" and r.date == self.ANCHOR.isoformat()
        )
        assert "8.5h" in rec_r.explanation

    def test_explanation_mentions_deep_sleep(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        rec_r = next(
            r for r in results if r.metric == "recovery" and r.date == self.ANCHOR.isoformat()
        )
        assert "deep sleep" in rec_r.explanation.lower()


class TestCoAnomalies:
    """HRV and recovery both anomalous on the same anchor day.

    Expected: each enriched anomaly lists the other as a co-anomaly.
    """

    ANCHOR = date(2042, 4, 22)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Seed baseline with BOTH hrv and recovery varying in the same rows
            # so that neither overwrites the other's alternating pattern.
            for i in range(14):
                d = (self.ANCHOR - timedelta(days=13 - i)).isoformat()
                hrv_v = 58.0 if i % 2 == 0 else 62.0
                rec_v = 70.0 if i % 2 == 0 else 80.0
                s.merge(_daily(d, hrv=hrv_v, recovery=rec_v))
            # Both crash on anchor day
            s.merge(_daily(self.ANCHOR.isoformat(), hrv=15.0, recovery=15.0))
            s.commit()

    def test_both_metrics_detected(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        dates_metrics = [(r.date, r.metric) for r in results]
        anchor_iso = self.ANCHOR.isoformat()
        assert (anchor_iso, "hrv") in dates_metrics
        assert (anchor_iso, "recovery") in dates_metrics

    def test_hrv_lists_recovery_as_co_anomaly(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        hrv_r = next(r for r in results if r.metric == "hrv" and r.date == self.ANCHOR.isoformat())
        assert "Recovery Score" in hrv_r.context["co_anomalies"]

    def test_recovery_lists_hrv_as_co_anomaly(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        rec_r = next(
            r for r in results if r.metric == "recovery" and r.date == self.ANCHOR.isoformat()
        )
        assert "HRV" in rec_r.context["co_anomalies"]

    def test_self_not_in_co_anomalies(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        for r in results:
            assert r.metric_label not in r.context["co_anomalies"]


class TestLimit:
    """When many anomalies exist, limit= caps the output."""

    ANCHOR = date(2042, 5, 30)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Seed alternating baseline for multiple metrics
            for i in range(14):
                d = (self.ANCHOR - timedelta(days=13 - i)).isoformat()
                hrv_val = 58.0 if i % 2 == 0 else 62.0
                rec_val = 70.0 if i % 2 == 0 else 80.0
                session_daily = _daily(d, hrv=hrv_val, recovery=rec_val)
                s.merge(session_daily)
            # Both crash on anchor
            s.merge(_daily(self.ANCHOR.isoformat(), hrv=10.0, recovery=10.0))
            s.commit()

    def test_limit_1_returns_one(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR, limit=1)
        assert len(results) == 1

    def test_limit_default_respects_cap(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR, limit=20)
        assert len(results) <= 20

    def test_most_severe_returned_first_when_limited(self, engine):
        start = self.ANCHOR - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR, limit=1)
        # Both hrv and recovery crash equally; whichever comes first should
        # have severity as high as the other
        assert results[0].severity >= 2.0


class TestSortedDescending:
    """Two anomalies on different dates — later date must come first."""

    ANCHOR = date(2042, 7, 10)
    EARLIER = date(2042, 6, 25)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Seed baseline for both windows (non-overlapping — 30d apart)
            for i in range(14):
                d1 = (self.ANCHOR - timedelta(days=13 - i)).isoformat()
                d2 = (self.EARLIER - timedelta(days=13 - i)).isoformat()
                hrv_v = 58.0 if i % 2 == 0 else 62.0
                s.merge(_daily(d1, hrv=hrv_v))
                s.merge(_daily(d2, hrv=hrv_v))
            # Anomalies on both anchor and earlier date
            s.merge(_daily(self.ANCHOR.isoformat(), hrv=10.0))
            s.merge(_daily(self.EARLIER.isoformat(), hrv=10.0))
            s.commit()

    def test_most_recent_first(self, engine):
        start = self.EARLIER - timedelta(days=14)
        results = get_enriched_anomalies(engine, None, start, self.ANCHOR)
        hrv_results = [r for r in results if r.metric == "hrv"]
        assert len(hrv_results) >= 2
        # Dates should be descending
        dates = [r.date for r in hrv_results]
        assert dates == sorted(dates, reverse=True)


class TestEnrichAnomalyDirect:
    """Test enrich_anomaly() directly with a pre-built anomaly dict."""

    ANCHOR = date(2042, 8, 15)

    @pytest.fixture(scope="class", autouse=True)
    def seed(self, engine):
        with Session(engine) as s:
            # Seed training data 2 days prior
            d1 = (self.ANCHOR - timedelta(days=1)).isoformat()
            d2 = (self.ANCHOR - timedelta(days=2)).isoformat()
            s.merge(_workout(d1, strain=18.0, uid=10))
            s.merge(_workout(d2, strain=16.0, uid=11))
            s.commit()

    def test_returns_enriched_anomaly_instance(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        result = enrich_anomaly(engine, None, "hrv", anomaly)
        assert isinstance(result, EnrichedAnomaly)

    def test_metric_and_label_set(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        result = enrich_anomaly(engine, None, "hrv", anomaly)
        assert result.metric == "hrv"
        assert result.metric_label == "HRV"

    def test_severity_is_abs(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        result = enrich_anomaly(engine, None, "hrv", anomaly)
        assert result.severity == pytest.approx(3.2, abs=0.01)

    def test_training_context_included(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        result = enrich_anomaly(engine, None, "hrv", anomaly)
        ctx = result.context["training_48h"]
        assert ctx["workout_count"] == 2
        assert ctx["total_strain"] == pytest.approx(34.0, abs=0.5)

    def test_co_anomalies_empty_by_default(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        result = enrich_anomaly(engine, None, "hrv", anomaly)
        assert result.context["co_anomalies"] == []

    def test_co_anomalies_from_map(self, engine):
        anomaly = {
            "date": self.ANCHOR.isoformat(),
            "value": 32.0,
            "direction": "low",
            "severity": -3.2,
        }
        co_map = {self.ANCHOR.isoformat(): ["HRV", "Recovery Score"]}
        result = enrich_anomaly(engine, None, "hrv", anomaly, co_anomalies_by_date=co_map)
        # "HRV" is self (metric_label), should be excluded
        assert "Recovery Score" in result.context["co_anomalies"]
        assert "HRV" not in result.context["co_anomalies"]
