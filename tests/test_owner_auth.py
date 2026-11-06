"""Owner-only auth: registration is closed and only the single owner's token is accepted."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("TESTING", "1")

OWNER = "owner-0001"
OTHER = "other-0002"


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from src.database.migrations import run

    run(engine=eng)
    return eng


@pytest.fixture
def client(engine):
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    def _db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_engine_dep] = lambda: engine
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _seed_user(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES (:id, :email, 'x', '2026-01-01T00:00:00', 1)"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )


def _auth(user_id: str) -> dict:
    from src.auth.security import create_access_token

    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def test_register_route_gone(client):
    res = client.post("/api/auth/register", json={"email": "x@y.test", "password": "p" * 12})
    assert res.status_code in (404, 405)


def test_owner_token_accepted(client, engine):
    _seed_user(engine, OWNER)
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 200


def test_non_owner_token_rejected(client, engine):
    _seed_user(engine, OWNER)
    assert client.get("/api/auth/me", headers=_auth(OTHER)).status_code == 401


def test_no_users_rejects_every_token(client):
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 401


def test_multiple_users_rejects_every_token(client, engine, caplog):
    _seed_user(engine, OWNER)
    _seed_user(engine, OTHER)
    with caplog.at_level("ERROR", logger="src.auth.dependencies"):
        assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 401
    assert any(r.levelname == "ERROR" and "more than one" in r.getMessage() for r in caplog.records)


def test_owner_cache_sees_owner_created_after_first_request(client, engine):
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 401
    _seed_user(engine, OWNER)
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 200


def test_whoop_url_available_to_owner(client, engine, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "whoop_client_id", "test-client-id")
    _seed_user(engine, OWNER)
    res = client.get("/api/auth/whoop/url", headers=_auth(OWNER))
    assert res.status_code == 200
    assert "state=" in res.json()["url"]


def test_feature_flags_route_gone(client):
    assert client.get("/api/auth/feature-flags").status_code in (404, 405)
