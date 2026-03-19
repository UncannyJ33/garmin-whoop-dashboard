"""Acceptance-criteria tests for Task 6.6: Comprehensive Account Settings.

Covers:
1. Device management — Whoop disconnect removes token; status reflects disconnected state
2. Data export — GET /api/account/export returns user-scoped ZIP with 4 CSVs
3. Password change — correct password succeeds; wrong/short password rejected
4. Account deletion — removes ALL data from ALL tables
5. Deletion invalidates session — subsequent refresh fails with 401
6. Cross-user isolation — export and deletion only touch the calling user's rows
"""

from __future__ import annotations

import io
import os
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Never start the background scheduler during tests
os.environ.setdefault("TESTING", "1")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_A = "acct-aaaa-0001"
USER_B = "acct-bbbb-0002"
EMAIL_A = "alice@example.com"
EMAIL_B = "bob@example.com"
PASSWORD = "correct-horse-battery"  # ≥8 chars


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------


def _make_engine():
    """Fresh in-memory SQLite engine with all migrations applied."""
    from src.database.migrations import run

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run(engine=engine)
    return engine


def _make_client(engine) -> TestClient:
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    def _db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_engine_dep] = lambda: engine
    return TestClient(app, raise_server_exceptions=False)


def _auth(user_id: str) -> dict:
    from src.auth.security import create_access_token

    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _seed_user(engine, user_id: str, email: str, password: str) -> None:
    """Insert a user row with a real bcrypt hash."""
    from src.auth.security import hash_password

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO users"
                " (id, email, hashed_password, is_active, created_at)"
                " VALUES (:id, :email, :hp, 1, '2026-01-01T00:00:00')"
            ),
            {"id": user_id, "email": email, "hp": hash_password(password)},
        )


def _seed_whoop_token(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO token_store"
                " (service, access_token, refresh_token, expires_at, updated_at, user_id)"
                " VALUES (:svc, 'at', 'rt', '2099-01-01', '2026-01-01', :uid)"
            ),
            {"svc": f"whoop_{user_id}", "uid": user_id},
        )


def _seed_garmin_token(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO token_store"
                " (service, access_token, refresh_token, expires_at, updated_at, user_id)"
                " VALUES (:svc, 'at', 'rt', '2099-01-01', '2026-01-01', :uid)"
            ),
            {"svc": f"garmin_{user_id}", "uid": user_id},
        )


def _seed_garmin_credentials(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO garmin_credentials"
                " (user_id, encrypted_email, encrypted_password,"
                "  auto_sync_enabled, consent_given_at, created_at, updated_at)"
                " VALUES (:uid, 'enc_email', 'enc_pass', 1,"
                "  '2026-01-01', '2026-01-01', '2026-01-01')"
            ),
            {"uid": user_id},
        )


def _seed_sync_log(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_log"
                " (source, sync_type, started_at, status, user_id)"
                " VALUES ('whoop', 'incremental', '2026-01-01T00:00:00', 'success', :uid)"
            ),
            {"uid": user_id},
        )


def _seed_unified_daily(engine, user_id: str, date: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO unified_daily"
                " (date, last_updated, user_id)"
                " VALUES (:d, '2026-01-01', :uid)"
            ),
            {"d": date, "uid": user_id},
        )


def _seed_unified_sleep(engine, user_id: str, date: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO unified_sleep"
                " (date, last_updated, user_id)"
                " VALUES (:d, '2026-01-01', :uid)"
            ),
            {"d": date, "uid": user_id},
        )


def _seed_unified_workout(engine, user_id: str, wid: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO unified_workouts"
                " (id, date, start_time, last_updated, user_id)"
                " VALUES (:id, '2026-01-01', '2026-01-01T08:00:00', '2026-01-01', :uid)"
            ),
            {"id": wid, "uid": user_id},
        )


def _seed_whoop_cycle(engine, user_id: str, cycle_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO whoop_cycles"
                " (id, user_id, start_time, fetched_at, app_user_id)"
                " VALUES (:cid, 9999, '2026-01-01T06:00:00', '2026-01-01', :uid)"
            ),
            {"cid": cycle_id, "uid": user_id},
        )


def _seed_whoop_recovery(engine, user_id: str, cycle_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO whoop_recovery"
                " (id, cycle_id, score_state, recovery_score, fetched_at, user_id)"
                " VALUES (:rid, :cid, 'SCORED', 75.0, '2026-01-01', :uid)"
            ),
            {"rid": f"rec_{cycle_id}", "cid": cycle_id, "uid": user_id},
        )


def _seed_whoop_sleep(engine, user_id: str, cycle_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO whoop_sleep"
                " (id, cycle_id, start_time, end_time, fetched_at, user_id)"
                " VALUES (:sid, :cid, '2026-01-01T00:00:00', '2026-01-01T07:00:00',"
                "  '2026-01-01', :uid)"
            ),
            {"sid": f"sl_{cycle_id}", "cid": cycle_id, "uid": user_id},
        )


def _seed_whoop_workout(engine, user_id: str, cycle_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO whoop_workouts"
                " (id, cycle_id, start_time, end_time, fetched_at, user_id)"
                " VALUES (:wid, :cid, '2026-01-01T08:00:00', '2026-01-01T09:00:00',"
                "  '2026-01-01', :uid)"
            ),
            {"wid": f"wo_{cycle_id}", "cid": cycle_id, "uid": user_id},
        )


def _count(engine, table: str, user_col: str, user_id: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {user_col} = :uid"),
            {"uid": user_id},
        ).one()
    return row[0]


def _token_exists(engine, service: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM token_store WHERE service = :svc"),
            {"svc": service},
        ).one()
    return row[0] > 0


# ---------------------------------------------------------------------------
# 1. Device management — Whoop disconnect
# ---------------------------------------------------------------------------


class TestWhoopDisconnect:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = _make_engine()
        _seed_user(self.engine, USER_A, EMAIL_A, PASSWORD)
        self.client = _make_client(self.engine)

    def test_disconnect_removes_token(self):
        _seed_whoop_token(self.engine, USER_A)
        assert _token_exists(self.engine, f"whoop_{USER_A}")

        res = self.client.delete("/api/auth/whoop/disconnect", headers=_auth(USER_A))
        assert res.status_code == 204
        assert not _token_exists(self.engine, f"whoop_{USER_A}")

    def test_status_returns_not_connected_after_disconnect(self):
        _seed_whoop_token(self.engine, USER_A)
        self.client.delete("/api/auth/whoop/disconnect", headers=_auth(USER_A))

        res = self.client.get("/api/auth/whoop/status", headers=_auth(USER_A))
        assert res.status_code == 200
        assert res.json()["connected"] is False

    def test_disconnect_is_idempotent_when_no_token(self):
        """204 even if the token doesn't exist — safe to call multiple times."""
        res = self.client.delete("/api/auth/whoop/disconnect", headers=_auth(USER_A))
        assert res.status_code == 204

    def test_disconnect_requires_auth(self):
        res = self.client.delete("/api/auth/whoop/disconnect")
        assert res.status_code == 401

    def test_disconnect_does_not_affect_other_user(self):
        _seed_user(self.engine, USER_B, EMAIL_B, PASSWORD)
        _seed_whoop_token(self.engine, USER_A)
        _seed_whoop_token(self.engine, USER_B)

        self.client.delete("/api/auth/whoop/disconnect", headers=_auth(USER_A))

        assert not _token_exists(self.engine, f"whoop_{USER_A}")
        assert _token_exists(self.engine, f"whoop_{USER_B}")


# ---------------------------------------------------------------------------
# 2. Data export
# ---------------------------------------------------------------------------


class TestDataExport:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = _make_engine()
        _seed_user(self.engine, USER_A, EMAIL_A, PASSWORD)
        self.client = _make_client(self.engine)

    def test_export_returns_zip(self):
        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        assert res.status_code == 200
        assert "application/zip" in res.headers["content-type"]

    def test_export_contains_four_csv_files(self):
        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            names = set(zf.namelist())
        assert names == {"workouts.csv", "sleep.csv", "daily_metrics.csv", "recovery.csv"}

    def test_export_includes_own_data(self):
        """Seeded rows appear in the export."""
        _seed_unified_workout(self.engine, USER_A, "export-w-a1")
        _seed_unified_sleep(self.engine, USER_A, "2026-02-01")
        _seed_unified_daily(self.engine, USER_A, "2026-02-01")
        cycle_id = "export-cycle-a1"
        _seed_whoop_cycle(self.engine, USER_A, cycle_id)
        _seed_whoop_recovery(self.engine, USER_A, cycle_id)

        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            workouts_csv = zf.read("workouts.csv").decode()
            sleep_csv = zf.read("sleep.csv").decode()
            daily_csv = zf.read("daily_metrics.csv").decode()
            recovery_csv = zf.read("recovery.csv").decode()

        assert "export-w-a1" in workouts_csv
        assert "2026-02-01" in sleep_csv
        assert "2026-02-01" in daily_csv
        assert f"rec_{cycle_id}" in recovery_csv

    def test_export_excludes_other_user_data(self):
        """Rows belonging to USER_B must not appear in USER_A's export."""
        _seed_user(self.engine, USER_B, EMAIL_B, PASSWORD)
        _seed_unified_workout(self.engine, USER_B, "export-w-b1")
        _seed_unified_sleep(self.engine, USER_B, "2026-03-01")

        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            workouts_csv = zf.read("workouts.csv").decode()
            sleep_csv = zf.read("sleep.csv").decode()

        assert "export-w-b1" not in workouts_csv
        assert "2026-03-01" not in sleep_csv

    def test_export_requires_auth(self):
        res = self.client.get("/api/account/export")
        assert res.status_code == 401

    def test_export_content_disposition_header(self):
        """Response includes a downloadable filename in Content-Disposition."""
        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        cd = res.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".zip" in cd


# ---------------------------------------------------------------------------
# 3. Password change
# ---------------------------------------------------------------------------


class TestChangePassword:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = _make_engine()
        _seed_user(self.engine, USER_A, EMAIL_A, PASSWORD)
        self.client = _make_client(self.engine)

    def test_change_password_success(self):
        res = self.client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "new-hunter2-secret"},
            headers=_auth(USER_A),
        )
        assert res.status_code == 204

    def test_new_password_works_for_login(self):
        """After a successful change, login with the new password succeeds."""
        new_pw = "new-hunter2-secret2"
        self.client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": new_pw},
            headers=_auth(USER_A),
        )
        res = self.client.post(
            "/api/auth/login",
            json={"email": EMAIL_A, "password": new_pw},
        )
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_wrong_current_password_returns_400(self):
        res = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong-password", "new_password": "new-hunter2-3"},
            headers=_auth(USER_A),
        )
        assert res.status_code == 400
        assert "incorrect" in res.json()["detail"].lower()

    def test_new_password_too_short_returns_400(self):
        res = self.client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers=_auth(USER_A),
        )
        assert res.status_code == 400
        assert "8" in res.json()["detail"]

    def test_change_password_requires_auth(self):
        res = self.client.post(
            "/api/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "new-hunter2-4"},
        )
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# 4 + 5. Account deletion — removes all data; JWT invalidated
# ---------------------------------------------------------------------------


class TestDeleteAccount:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = _make_engine()
        _seed_user(self.engine, USER_A, EMAIL_A, PASSWORD)
        self.client = _make_client(self.engine)

    def _seed_full_dataset(self, user_id: str) -> None:
        """Seed one row into every table the delete endpoint touches."""
        cycle_id = f"del-cycle-{user_id}"
        _seed_whoop_token(self.engine, user_id)
        _seed_garmin_token(self.engine, user_id)
        _seed_garmin_credentials(self.engine, user_id)
        _seed_sync_log(self.engine, user_id)
        _seed_unified_workout(self.engine, user_id, f"del-w-{user_id}")
        _seed_unified_sleep(self.engine, user_id, f"2026-04-0{user_id[-1]}")
        _seed_unified_daily(self.engine, user_id, f"2026-04-0{user_id[-1]}")
        _seed_whoop_cycle(self.engine, user_id, cycle_id)
        _seed_whoop_recovery(self.engine, user_id, cycle_id)
        _seed_whoop_sleep(self.engine, user_id, cycle_id)
        _seed_whoop_workout(self.engine, user_id, cycle_id)

    def test_delete_removes_user_row(self):
        res = self.client.delete("/api/account", headers=_auth(USER_A))
        assert res.status_code == 204

        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT id FROM users WHERE id = :uid"), {"uid": USER_A}
            ).one_or_none()
        assert row is None

    def test_delete_removes_all_table_data(self):
        self._seed_full_dataset(USER_A)

        self.client.delete("/api/account", headers=_auth(USER_A))

        # Token store
        assert not _token_exists(self.engine, f"whoop_{USER_A}")
        assert not _token_exists(self.engine, f"garmin_{USER_A}")

        # Credentials
        assert _count(self.engine, "garmin_credentials", "user_id", USER_A) == 0

        # Sync log
        assert _count(self.engine, "sync_log", "user_id", USER_A) == 0

        # Unified tables
        assert _count(self.engine, "unified_workouts", "user_id", USER_A) == 0
        assert _count(self.engine, "unified_sleep", "user_id", USER_A) == 0
        assert _count(self.engine, "unified_daily", "user_id", USER_A) == 0

        # Whoop source tables
        assert _count(self.engine, "whoop_recovery", "user_id", USER_A) == 0
        assert _count(self.engine, "whoop_sleep", "user_id", USER_A) == 0
        assert _count(self.engine, "whoop_workouts", "user_id", USER_A) == 0
        assert _count(self.engine, "whoop_cycles", "app_user_id", USER_A) == 0

        # User row
        assert _count(self.engine, "users", "id", USER_A) == 0

    def test_delete_invalidates_refresh_token(self):
        """After account deletion, the refresh endpoint must return 401."""
        # Obtain a real refresh token before deletion
        res = self.client.post(
            "/api/auth/login", json={"email": EMAIL_A, "password": PASSWORD}
        )
        refresh_token = res.json()["refresh_token"]

        self.client.delete("/api/account", headers=_auth(USER_A))

        # Refresh must now fail because the user row no longer exists
        res = self.client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert res.status_code == 401

    def test_delete_requires_auth(self):
        res = self.client.delete("/api/account")
        assert res.status_code == 401

    def test_delete_is_idempotent_at_data_level(self):
        """A second DELETE after the user is already gone still returns 204
        (or at worst 404) — it must not raise an unhandled server error."""
        self.client.delete("/api/account", headers=_auth(USER_A))
        # Old JWT is still structurally valid even though user is gone
        res = self.client.delete("/api/account", headers=_auth(USER_A))
        assert res.status_code in (204, 404)


# ---------------------------------------------------------------------------
# 6. Cross-user isolation — deletion only touches the calling user's rows
# ---------------------------------------------------------------------------


class TestDeleteCrossUserIsolation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = _make_engine()
        _seed_user(self.engine, USER_A, EMAIL_A, PASSWORD)
        _seed_user(self.engine, USER_B, EMAIL_B, PASSWORD)
        self.client = _make_client(self.engine)

    def test_delete_leaves_other_user_intact(self):
        cycle_b = "iso-cycle-b"
        _seed_whoop_token(self.engine, USER_A)
        _seed_whoop_token(self.engine, USER_B)
        _seed_sync_log(self.engine, USER_A)
        _seed_sync_log(self.engine, USER_B)
        _seed_whoop_cycle(self.engine, USER_B, cycle_b)
        _seed_whoop_recovery(self.engine, USER_B, cycle_b)

        self.client.delete("/api/account", headers=_auth(USER_A))

        # USER_A's data is gone
        assert not _token_exists(self.engine, f"whoop_{USER_A}")
        assert _count(self.engine, "sync_log", "user_id", USER_A) == 0

        # USER_B's data is untouched
        assert _token_exists(self.engine, f"whoop_{USER_B}")
        assert _count(self.engine, "sync_log", "user_id", USER_B) == 1
        assert _count(self.engine, "whoop_recovery", "user_id", USER_B) == 1
        assert _count(self.engine, "users", "id", USER_B) == 1

    def test_export_isolation(self):
        """USER_A's export contains only USER_A's workout, not USER_B's."""
        _seed_unified_workout(self.engine, USER_A, "iso-w-a")
        _seed_unified_workout(self.engine, USER_B, "iso-w-b")

        res = self.client.get("/api/account/export", headers=_auth(USER_A))
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            workouts_csv = zf.read("workouts.csv").decode()

        assert "iso-w-a" in workouts_csv
        assert "iso-w-b" not in workouts_csv
