"""scripts/smoke_api.py core function against an in-memory seeded DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from scripts.smoke_api import check_response, run_smoke
from src.api.dependencies import get_db, get_engine_dep
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, UnifiedWorkout

NOW_ISO = datetime.now(UTC).isoformat()
UID = "dddddddd-0000-0000-0000-000000000009"


@pytest.fixture(scope="module")
def client():
    eng = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    run_migrations(engine=eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES (:id, 's@example.test', 'x', '2026-01-01T00:00:00', 1)"
            ),
            {"id": UID},
        )
    Session = get_session_factory(eng)
    db = Session()
    today = date.today()
    for i in range(10):
        d = (today - timedelta(days=i)).isoformat()
        db.add(
            UnifiedDaily(
                date=d,
                user_id=UID,
                garmin_total_steps=1000 + i,
                data_sources='["garmin"]',
                last_updated=NOW_ISO,
            )
        )
        db.add(
            UnifiedWorkout(
                id=f"g_{i}",
                date=d,
                start_time=f"{d}T10:00:00+00:00",
                activity_type="strength_training" if i == 0 else "running",
                duration_minutes=30.0,
                user_id=UID,
                primary_source="garmin",
                matched=False,
                last_updated=NOW_ISO,
            )
        )
    db.commit()
    db.close()

    def _db_override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    with patch("src.api.main.start_scheduler"), patch("src.api.main.stop_scheduler"):
        from src.api.main import app  # noqa: PLC0415

        app.dependency_overrides[get_engine_dep] = lambda: eng
        app.dependency_overrides[get_db] = _db_override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()
    eng.dispose()


def test_smoke_runs_clean_on_seeded_db(client):
    token, _ = create_access_token(UID)
    results = run_smoke(client, {"Authorization": f"Bearer {token}"}, created_today())
    ran = [r for r in results if not r.skipped]
    assert len(ran) > 50
    assert [r for r in ran if r.failed] == []
    assert any(r.route.endswith("/exercise-summary") for r in ran)


def created_today() -> date:
    return datetime.now(UTC).date()


def test_check_response_flags_problems():
    assert check_response("/x", "-", 200, '{"a": 1}', 5.0, False).failed is False
    assert check_response("/x", "-", 200, '{"a": NaN}', 5.0, False).failed
    assert check_response("/x", "-", 200, '{"a": "None"}', 5.0, False).failed
    assert check_response("/x", "-", 500, "{}", 5.0, False).failed
    assert check_response("/x", "-", 204, "", 5.0, True).failed is False
    slow = check_response("/x", "-", 200, "{}", 2500.0, False)
    assert "slow" in slow.flags and not slow.failed
