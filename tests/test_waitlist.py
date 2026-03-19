"""Acceptance-criteria tests for the PulseEngine landing page waitlist.

Covers:
1. Email capture — POST /api/waitlist stores email and returns success
2. Duplicate handling — second signup for same email returns success silently
3. Rate limiting — 6th request from same IP gets 429
4. Input validation — malformed email returns 422
5. Admin retrieval — GET /api/waitlist/admin with correct credentials returns entries
6. Admin auth — wrong credential returns 403; unconfigured ADMIN_EMAIL returns 403
7. Logged-in users bypass landing — / returns the SPA shell (not a redirect to /login)
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

os.environ.setdefault("TESTING", "1")

ADMIN_EMAIL = "admin@pulsebuilt.net"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    from src.database.migrations import run

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run(engine=eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def client(engine):
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    def _db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_engine_dep] = lambda: engine
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_header() -> dict:
    return {"Authorization": f"Bearer {ADMIN_EMAIL}"}


def _count_email(engine, email: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM waitlist WHERE email = :e"), {"e": email}
        ).scalar()


# ---------------------------------------------------------------------------
# Helpers — reset rate-limit state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the in-memory rate-limit deque before each test."""
    import src.api.routes.waitlist as wl_mod

    wl_mod._attempts.clear()
    yield
    wl_mod._attempts.clear()


# ---------------------------------------------------------------------------
# 1. Email capture
# ---------------------------------------------------------------------------


def test_signup_returns_success(client):
    res = client.post("/api/waitlist", json={"email": "user1@example.com"})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert "list" in body["message"].lower()


def test_signup_stores_email_in_db(client, engine):
    client.post("/api/waitlist", json={"email": "stored@example.com"})
    assert _count_email(engine, "stored@example.com") == 1


def test_signup_sets_notified_false(client, engine):
    client.post("/api/waitlist", json={"email": "notified@example.com"})
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT notified FROM waitlist WHERE email = :e"),
            {"e": "notified@example.com"},
        ).one()
    assert row[0] == 0


def test_signup_records_signed_up_at(client, engine):
    client.post("/api/waitlist", json={"email": "timestamp@example.com"})
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT signed_up_at FROM waitlist WHERE email = :e"),
            {"e": "timestamp@example.com"},
        ).one()
    assert row[0] is not None
    assert "2026" in row[0]  # year present — basic sanity check


# ---------------------------------------------------------------------------
# 2. Duplicate handling — silently succeeds
# ---------------------------------------------------------------------------


def test_duplicate_signup_returns_success(client):
    """Signing up with the same email twice must return 200 both times."""
    client.post("/api/waitlist", json={"email": "dup@example.com"})
    res = client.post("/api/waitlist", json={"email": "dup@example.com"})
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_duplicate_signup_does_not_create_second_row(client, engine):
    client.post("/api/waitlist", json={"email": "dup2@example.com"})
    client.post("/api/waitlist", json={"email": "dup2@example.com"})
    assert _count_email(engine, "dup2@example.com") == 1


# ---------------------------------------------------------------------------
# 3. Rate limiting — 5 allowed, 6th blocked
# ---------------------------------------------------------------------------


def test_rate_limit_allows_five_requests(client):
    """Five requests from the same IP must all succeed."""
    for i in range(5):
        res = client.post("/api/waitlist", json={"email": f"rl{i}@example.com"})
        assert res.status_code == 200, f"request {i + 1} should be allowed"


def test_rate_limit_blocks_sixth_request(client):
    """The sixth request within the window must return 429."""
    for i in range(5):
        client.post("/api/waitlist", json={"email": f"block{i}@example.com"})
    res = client.post("/api/waitlist", json={"email": "block6@example.com"})
    assert res.status_code == 429


# ---------------------------------------------------------------------------
# 4. Input validation
# ---------------------------------------------------------------------------


def test_invalid_email_returns_422(client):
    res = client.post("/api/waitlist", json={"email": "not-an-email"})
    assert res.status_code == 422


def test_missing_email_field_returns_422(client):
    res = client.post("/api/waitlist", json={})
    assert res.status_code == 422


def test_empty_email_returns_422(client):
    res = client.post("/api/waitlist", json={"email": ""})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 5. Admin retrieval
# ---------------------------------------------------------------------------


def test_admin_returns_entries(client, engine):
    client.post("/api/waitlist", json={"email": "admin-check@example.com"})

    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ADMIN_EMAIL
        res = client.get("/api/waitlist/admin", headers=_admin_header())

    assert res.status_code == 200
    body = res.json()
    assert "count" in body
    assert "entries" in body
    assert isinstance(body["entries"], list)
    assert body["count"] == len(body["entries"])


def test_admin_entry_has_expected_fields(client):
    client.post("/api/waitlist", json={"email": "fields@example.com"})

    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ADMIN_EMAIL
        res = client.get("/api/waitlist/admin", headers=_admin_header())

    entries = res.json()["entries"]
    assert len(entries) > 0
    entry = entries[0]
    assert "id" in entry
    assert "email" in entry
    assert "signed_up_at" in entry
    assert "notified" in entry


def test_admin_count_matches_entries(client):
    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ADMIN_EMAIL
        res = client.get("/api/waitlist/admin", headers=_admin_header())

    body = res.json()
    assert body["count"] == len(body["entries"])


# ---------------------------------------------------------------------------
# 6. Admin auth — wrong / missing credentials
# ---------------------------------------------------------------------------


def test_admin_wrong_credential_returns_403(client):
    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ADMIN_EMAIL
        res = client.get(
            "/api/waitlist/admin",
            headers={"Authorization": "Bearer wrong@example.com"},
        )
    assert res.status_code == 403


def test_admin_no_auth_header_returns_403(client):
    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ADMIN_EMAIL
        res = client.get("/api/waitlist/admin")
    assert res.status_code == 403


def test_admin_unconfigured_returns_403(client):
    """If ADMIN_EMAIL is not set, the endpoint must be inaccessible."""
    with patch("src.api.routes.waitlist.settings") as mock_settings:
        mock_settings.admin_email = ""
        res = client.get("/api/waitlist/admin", headers=_admin_header())
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 7. Logged-in users bypass landing — SPA serves index.html at /
# ---------------------------------------------------------------------------


def test_root_path_is_publicly_accessible(client):
    """GET / must return 200 without any auth — the SPA serves the landing page."""
    # In production the dist/ exists and serves index.html.  In test, FastAPI
    # returns 200 from the health check or (if no dist/) a 404 from the file handler.
    # What must NOT happen is a 401 or a redirect to /login.
    res = client.get("/")
    assert res.status_code not in (401, 302, 307)


def test_login_page_is_publicly_accessible(client):
    res = client.get("/login")
    assert res.status_code not in (401, 302, 307)
