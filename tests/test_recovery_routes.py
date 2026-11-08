"""Recovery routes date Whoop recovery activities by local time (Phase 8 task 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_engine_dep
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedDaily, WhoopWorkout

UID = "cccccccc-0000-0000-0000-000000000003"
NOW_ISO = datetime.now(UTC).isoformat()


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
                " VALUES (:id, 'c@example.test', 'x', '2026-01-01T00:00:00', 1)"
            ),
            {"id": UID},
        )
    Session = get_session_factory(eng)
    db = Session()
    for d, rec in (("2024-02-05", 50.0), ("2024-02-06", 80.0)):
        db.add(
            UnifiedDaily(
                date=d,
                whoop_recovery_score=rec,
                data_sources='["whoop"]',
                last_updated=NOW_ISO,
                user_id=UID,
            )
        )
    # Yoga at 21:00 local on 2024-02-05 (UTC-5) == 02:00Z on 2024-02-06
    db.add(
        WhoopWorkout(
            id="yoga-eve",
            start_time="2024-02-06T02:00:00Z",
            end_time="2024-02-06T02:30:00Z",
            timezone_offset="-05:00",
            sport_name="yoga",
            strain=None,
            fetched_at=NOW_ISO,
            user_id=UID,
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


def _auth() -> dict[str, str]:
    token, _ = create_access_token(UID)
    return {"Authorization": f"Bearer {token}"}


def test_recovery_activity_dated_locally(client):
    r = client.get("/api/recovery?start=2024-02-05&end=2024-02-05", headers=_auth())
    assert r.status_code == 200
    items = r.json()
    assert [i["date"] for i in items] == ["2024-02-05"]
    assert items[0]["next_day_recovery"] == pytest.approx(80.0)
    # The UTC date (02-06) must not list it
    r = client.get("/api/recovery?start=2024-02-06&end=2024-02-06", headers=_auth())
    assert r.json() == []

    r = client.get("/api/recovery/with-without?start=2024-02-06&end=2024-02-06", headers=_auth())
    body = r.json()
    assert body["with_count"] == 1
    assert body["with_avg"] == pytest.approx(80.0)


def test_with_without_recovery_dates_query_is_bounded(client):
    """The all-recovery-dates query only reads start-2d .. end+2d, not the whole history."""
    from sqlalchemy import event  # noqa: PLC0415

    from src.api.main import app  # noqa: PLC0415

    eng = app.dependency_overrides[get_engine_dep]()
    seen: list[tuple] = []

    def _spy(conn, cursor, statement, parameters, context, executemany):
        if "SELECT DISTINCT start_time" in statement:
            seen.append((statement, parameters))

    event.listen(eng, "before_cursor_execute", _spy)
    try:
        r = client.get(
            "/api/recovery/with-without?start=2024-02-06&end=2024-02-06", headers=_auth()
        )
    finally:
        event.remove(eng, "before_cursor_execute", _spy)
    assert r.status_code == 200
    assert r.json()["with_count"] == 1  # unchanged by the bound
    assert len(seen) == 1
    statement, params = seen[0]
    assert "start_time >=" in statement and "start_time <" in statement
    assert "2024-02-04" in params and "2024-02-08" in params
