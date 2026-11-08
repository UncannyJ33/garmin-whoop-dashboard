"""Server-side sleep target: settings API, sleep debt, no-store, migration 015."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_db, get_engine_dep
from src.auth.security import create_access_token
from src.database.connection import get_session_factory
from src.database.migrations import _load
from src.database.migrations import run as run_migrations
from src.database.models import UnifiedSleep

OWNER = "dddddddd-0000-0000-0000-000000000004"
NOW_ISO = datetime.now(UTC).isoformat()


def _engine():
    return create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


@pytest.fixture
def ctx():
    eng = _engine()
    run_migrations(engine=eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES (:id, 'd@example.test', 'x', '2026-01-01T00:00:00', 1)"
            ),
            {"id": OWNER},
        )
    Session = get_session_factory(eng)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    with patch("src.api.main.start_scheduler"), patch("src.api.main.stop_scheduler"):
        from src.api.main import app  # noqa: PLC0415

        app.dependency_overrides[get_engine_dep] = lambda: eng
        app.dependency_overrides[get_db] = _db
        with TestClient(app) as c:
            yield c, eng
        app.dependency_overrides.clear()
    eng.dispose()


def _auth() -> dict[str, str]:
    token, _ = create_access_token(OWNER)
    return {"Authorization": f"Bearer {token}"}


def test_settings_get_default_480(ctx):
    client, _ = ctx
    r = client.get("/api/settings", headers=_auth())
    assert r.status_code == 200
    assert r.json() == {"sleep_target_minutes": 480}


@pytest.mark.parametrize("minutes", [299, 721])
def test_settings_put_validates_range(ctx, minutes):
    client, _ = ctx
    r = client.put("/api/settings", json={"sleep_target_minutes": minutes}, headers=_auth())
    assert r.status_code == 422


def test_settings_put_accepts_bounds(ctx):
    client, _ = ctx
    for minutes in (300, 720):
        r = client.put("/api/settings", json={"sleep_target_minutes": minutes}, headers=_auth())
        assert r.status_code == 200


def test_settings_put_persists(ctx):
    client, _ = ctx
    r = client.put("/api/settings", json={"sleep_target_minutes": 420}, headers=_auth())
    assert r.status_code == 200 and r.json() == {"sleep_target_minutes": 420}
    assert client.get("/api/settings", headers=_auth()).json() == {"sleep_target_minutes": 420}


def test_settings_requires_auth(ctx):
    client, _ = ctx
    assert client.get("/api/settings").status_code in (401, 403)
    assert client.put("/api/settings", json={"sleep_target_minutes": 420}).status_code in (401, 403)


def test_settings_get_is_no_store(ctx):
    client, _ = ctx
    r = client.get("/api/settings", headers=_auth())
    assert r.headers["cache-control"] == "no-store"


def test_api_responses_are_no_store(ctx):
    client, _ = ctx
    for path in ("/api/settings", "/api/sleep/insights?start=2026-01-01&end=2026-01-07"):
        r = client.get(path, headers=_auth())
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
    # error responses too
    assert client.get("/api/settings").headers["cache-control"] == "no-store"


def test_sleep_debt_uses_user_target(ctx):
    client, eng = ctx
    Session = get_session_factory(eng)
    db = Session()
    for d in ("2026-03-01", "2026-03-02", "2026-03-03"):
        db.add(
            UnifiedSleep(
                date=d,
                total_sleep_minutes=400.0,
                awake_minutes=0.0,
                last_updated=NOW_ISO,
                user_id=OWNER,
            )
        )
    db.commit()
    db.close()
    url = "/api/sleep/insights?start=2026-03-03&end=2026-03-03"
    default = client.get(url, headers=_auth()).json()
    assert default[0]["sleep_debt_estimate"] == pytest.approx(-80.0)
    client.put("/api/settings", json={"sleep_target_minutes": 420}, headers=_auth())
    custom = client.get(url, headers=_auth()).json()
    assert custom[0]["sleep_debt_estimate"] == pytest.approx(-20.0)


def test_migration_015_idempotent():
    eng = _engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL,"
                " hashed_password TEXT NOT NULL, created_at TEXT NOT NULL,"
                " is_active BOOLEAN NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO users VALUES ('u1', 'e@x.test', 'x', '2026-01-01', 1)"))
    mig = _load("015_user_sleep_target.py")
    mig.run(engine=eng)
    mig.run(engine=eng)
    assert "sleep_target_minutes" in {c["name"] for c in inspect(eng).get_columns("users")}
    with eng.connect() as conn:
        assert conn.execute(text("SELECT sleep_target_minutes FROM users")).scalar() == 480
    eng.dispose()


def test_migration_015_noop_when_model_created_column():
    eng = _engine()
    run_migrations(engine=eng)  # 006 creates users from the model, 015 follows
    before = [c["name"] for c in inspect(eng).get_columns("users")]
    _load("015_user_sleep_target.py").run(engine=eng)
    assert [c["name"] for c in inspect(eng).get_columns("users")] == before
    assert "sleep_target_minutes" in before
    eng.dispose()
