"""Tests for src/analytics/anomaly_store.py incremental refresh (Phase 8 task 1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.analytics.anomaly_store import get_cached_anomalies, refresh_anomalies
from src.analytics.trends import _ENRICHED_METRIC_LABELS
from src.database.connection import get_engine
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily

UID = "user-anomaly"
NOW_ISO = datetime.now(UTC).isoformat()
LAST = date(2033, 3, 30)
_JITTER = (60.0, 62.0, 58.0)


@pytest.fixture
def engine():
    eng = get_engine("sqlite:///:memory:")
    run_migrations(engine=eng)
    yield eng
    eng.dispose()


def _seed(engine, last_value: float) -> None:
    """30 jittered days around 60, then ``last_value`` on LAST."""
    with Session(engine) as s:
        for i in range(30):
            d = LAST - timedelta(days=29 - i)
            s.merge(
                UnifiedDaily(
                    date=d.isoformat(),
                    whoop_recovery_score=last_value if d == LAST else _JITTER[i % 3],
                    data_sources='["whoop"]',
                    last_updated=NOW_ISO,
                    user_id=UID,
                )
            )
        s.commit()


def _insert_cache(engine, d: date) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO anomaly_cache (user_id, date, metric, metric_label, value,"
                " direction, severity, context_json, explanation, computed_at)"
                " VALUES (:u, :d, 'recovery', 'Recovery Score', 20, 'low', 3.0, '{}', 'x', :n)"
            ),
            {"u": UID, "d": d.isoformat(), "n": NOW_ISO},
        )


def test_incremental_refresh_flags_latest_day(engine):
    _seed(engine, 20.0)
    assert refresh_anomalies(engine, UID, LAST, LAST) >= 1
    items = get_cached_anomalies(engine, UID, LAST, LAST)
    assert any(
        i["direction"] == "low" and i["metric"] == _ENRICHED_METRIC_LABELS["recovery"]
        for i in items
    )


def test_refresh_does_not_touch_rows_outside_window(engine):
    _seed(engine, 20.0)
    old = LAST - timedelta(days=10)
    _insert_cache(engine, old)
    refresh_anomalies(engine, UID, LAST, LAST)
    assert get_cached_anomalies(engine, UID, old, old)


def test_refresh_clears_resolved_anomaly_in_window(engine):
    _seed(engine, 60.0)
    _insert_cache(engine, LAST)
    refresh_anomalies(engine, UID, LAST, LAST)
    assert get_cached_anomalies(engine, UID, LAST, LAST) == []
