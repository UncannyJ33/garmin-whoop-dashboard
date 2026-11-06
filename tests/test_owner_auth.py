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


def test_multiple_users_rejects_every_token(client, engine):
    _seed_user(engine, OWNER)
    _seed_user(engine, OTHER)
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 401


def test_owner_cache_sees_owner_created_after_first_request(client, engine):
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 401
    _seed_user(engine, OWNER)
    assert client.get("/api/auth/me", headers=_auth(OWNER)).status_code == 200
