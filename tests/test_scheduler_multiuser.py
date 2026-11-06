"""Acceptance-criteria tests for Task 6.5: Per-User Sync Scheduling.

Covers:
1. Multiple users sync independently (all registry users are processed)
2. One user's failure doesn't block others (per-user try/except)
3. Rate limiting respects API constraints (sleep between users)
4. Sync status is per-user (running key, trigger auth, status endpoint)
5. Container restart triggers catch-up syncs (_schedule_catchup_if_stale)
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Ensure scheduler never starts during tests
os.environ.setdefault("TESTING", "1")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_ENC_KEY = Fernet.generate_key().decode()
USER_A = "user-aaaa-0001"
USER_B = "user-bbbb-0002"


def _make_engine():
    """In-memory SQLite engine with all migrations applied."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from src.database.migrations import run

    run(engine=engine)
    return engine


def _make_client(engine):
    """TestClient for the FastAPI app with DB + engine overrides."""
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    def _override_db():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_engine_dep] = lambda: engine
    return TestClient(app, raise_server_exceptions=False)


def _auth_header(user_id: str) -> dict:
    from src.auth.security import create_access_token

    token, _ = create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


def _seed_user(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR IGNORE INTO users (id, email, hashed_password, created_at)"
                " VALUES (:id, :email, 'x', '2026-01-01T00:00:00')"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )


def _seed_whoop_token(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO token_store"
                " (service, access_token, refresh_token, expires_at, updated_at)"
                " VALUES (:svc, 'at', 'rt', '2099-01-01', '2026-01-01')"
            ),
            {"svc": f"whoop_{user_id}"},
        )


def _seed_garmin_token(engine, user_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO token_store"
                " (service, access_token, refresh_token, expires_at, updated_at)"
                " VALUES (:svc, 'at', 'rt', '2099-01-01', '2026-01-01')"
            ),
            {"svc": f"garmin_{user_id}"},
        )


def _seed_garmin_credentials(engine, user_id: str, enc_key: str) -> None:
    f = Fernet(enc_key.encode())
    enc_email = f.encrypt(b"g@example.com").decode()
    enc_pass = f.encrypt(b"secret").decode()
    now = "2026-01-01T00:00:00"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT OR REPLACE INTO garmin_credentials"
                " (user_id, encrypted_email, encrypted_password,"
                "  auto_sync_enabled, consent_given_at, created_at, updated_at)"
                " VALUES (:uid, :email, :pass, 1, :now, :now, :now)"
            ),
            {"uid": user_id, "email": enc_email, "pass": enc_pass, "now": now},
        )


def _sync_log_success(engine, source: str, user_id: str, completed_at: str) -> None:
    """Insert a successful sync_log row."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_log"
                " (source, sync_type, status, records_fetched, records_stored,"
                "  started_at, completed_at, user_id)"
                " VALUES (:src, 'incremental', 'success', 0, 5, :ca, :ca, :uid)"
            ),
            {"src": source, "ca": completed_at, "uid": user_id},
        )


# ===========================================================================
# 1. Multiple users sync independently (registry covers all users)
# ===========================================================================


class TestSyncRegistry:
    """get_users_to_sync returns every user across all auth pathways."""

    def test_returns_empty_when_no_users(self):
        engine = _make_engine()
        from src.ingestion.scheduler import get_users_to_sync

        assert get_users_to_sync(engine) == []

    def test_returns_whoop_user(self):
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_whoop_token(engine, USER_A)

        from src.ingestion.scheduler import get_users_to_sync

        users = get_users_to_sync(engine)
        assert len(users) == 1
        u = users[0]
        assert u["user_id"] == USER_A
        assert u["whoop_connected"] is True
        assert u["garmin_auto_sync"] is False
        assert u["garmin_has_token"] is False

    def test_returns_garmin_credential_user(self, monkeypatch):
        monkeypatch.setenv("GARMIN_ENCRYPTION_KEY", TEST_ENC_KEY)
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_garmin_credentials(engine, USER_A, TEST_ENC_KEY)

        from src.ingestion.scheduler import get_users_to_sync

        users = get_users_to_sync(engine)
        assert len(users) == 1
        u = users[0]
        assert u["user_id"] == USER_A
        assert u["garmin_auto_sync"] is True
        assert u["garmin_has_token"] is False
        assert u["whoop_connected"] is False

    def test_returns_garmin_token_user(self):
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_garmin_token(engine, USER_A)

        from src.ingestion.scheduler import get_users_to_sync

        users = get_users_to_sync(engine)
        assert len(users) == 1
        u = users[0]
        assert u["user_id"] == USER_A
        assert u["garmin_has_token"] is True
        assert u["garmin_auto_sync"] is False
        assert u["whoop_connected"] is False

    def test_returns_all_users_across_pathways(self, monkeypatch):
        """User A has Whoop, User B has Garmin credentials, both are returned."""
        monkeypatch.setenv("GARMIN_ENCRYPTION_KEY", TEST_ENC_KEY)
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_user(engine, USER_B)
        _seed_whoop_token(engine, USER_A)
        _seed_garmin_credentials(engine, USER_B, TEST_ENC_KEY)

        from src.ingestion.scheduler import get_users_to_sync

        users = get_users_to_sync(engine)
        ids = {u["user_id"] for u in users}
        assert ids == {USER_A, USER_B}
        a = next(u for u in users if u["user_id"] == USER_A)
        b = next(u for u in users if u["user_id"] == USER_B)
        assert a["whoop_connected"] is True
        assert b["garmin_auto_sync"] is True

    def test_user_with_both_whoop_and_garmin(self, monkeypatch):
        monkeypatch.setenv("GARMIN_ENCRYPTION_KEY", TEST_ENC_KEY)
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_whoop_token(engine, USER_A)
        _seed_garmin_credentials(engine, USER_A, TEST_ENC_KEY)

        from src.ingestion.scheduler import get_users_to_sync

        users = get_users_to_sync(engine)
        assert len(users) == 1  # same user deduplicated
        u = users[0]
        assert u["whoop_connected"] is True
        assert u["garmin_auto_sync"] is True

    def test_returns_empty_on_db_error(self):
        from sqlalchemy import create_engine as ce

        from src.ingestion.scheduler import get_users_to_sync

        bad_engine = ce("sqlite:///nonexistent_path_xyz/db.sqlite")
        result = get_users_to_sync(bad_engine)
        assert result == []

    def test_garmin_job_processes_all_eligible_users(self, monkeypatch):
        """_run_garmin_multi_user calls pipeline.run() once per eligible user."""
        monkeypatch.setenv("GARMIN_ENCRYPTION_KEY", TEST_ENC_KEY)
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "garmin_auto_sync": False, "garmin_has_token": True},
            {"user_id": USER_B, "garmin_auto_sync": False, "garmin_has_token": True},
        ]

        synced_users = []

        mock_log = MagicMock(records_stored=3, status="success")
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_log

        class CapturePipeline:
            def __init__(self, db, *, user_id):
                synced_users.append(user_id)

            def run(self):
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.garmin_pipeline as gp_mod
            with patch.object(gp_mod, "GarminPipeline", side_effect=CapturePipeline):
                sched_mod._run_garmin_multi_user()

        assert set(synced_users) == {USER_A, USER_B}

    def test_whoop_job_processes_all_eligible_users(self):
        """_run_whoop_multi_user calls pipeline.run() once per eligible user."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "whoop_connected": True},
            {"user_id": USER_B, "whoop_connected": True},
        ]

        synced_users = []

        mock_log = MagicMock(records_stored=2, status="success")

        class CaptureWhoopPipeline:
            def __init__(self, db, *, user_id):
                synced_users.append(user_id)

            async def run(self):
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.whoop_pipeline as wp_mod
            with patch.object(wp_mod, "WhoopPipeline", side_effect=CaptureWhoopPipeline):
                sched_mod._run_whoop_multi_user()

        assert set(synced_users) == {USER_A, USER_B}


# ===========================================================================
# 2. One user's failure doesn't block others
# ===========================================================================


class TestFailureIsolation:
    """A sync failure for one user must not prevent other users from syncing."""

    def test_garmin_auth_failure_user_a_does_not_block_user_b(self):
        """GarminAuthError for user A: user B still syncs successfully."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "garmin_auto_sync": False, "garmin_has_token": True},
            {"user_id": USER_B, "garmin_auto_sync": False, "garmin_has_token": True},
        ]
        synced_users = []
        mock_log = MagicMock(records_stored=1, status="success")

        call_count = [0]

        class FlakeyPipeline:
            def __init__(self, db, *, user_id):
                self._uid = user_id

            def run(self):
                from src.clients.garmin_auth import GarminAuthError
                call_count[0] += 1
                if self._uid == USER_A:
                    raise GarminAuthError("401 bad creds")
                synced_users.append(self._uid)
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=MagicMock(fetchall=MagicMock(return_value=[])))
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", mock_engine),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.garmin_pipeline as gp_mod
            with patch.object(gp_mod, "GarminPipeline", side_effect=FlakeyPipeline):
                sched_mod._run_garmin_multi_user()  # must NOT raise

        # Both pipelines were attempted; user B synced despite A failing
        assert call_count[0] == 2
        assert synced_users == [USER_B]

    def test_garmin_unexpected_error_user_a_does_not_block_user_b(self):
        """Unexpected exception for user A: user B still syncs."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "garmin_auto_sync": False, "garmin_has_token": True},
            {"user_id": USER_B, "garmin_auto_sync": False, "garmin_has_token": True},
        ]
        synced_users = []
        mock_log = MagicMock(records_stored=1, status="success")

        class FlakeyPipeline:
            def __init__(self, db, *, user_id):
                self._uid = user_id

            def run(self):
                if self._uid == USER_A:
                    raise RuntimeError("network timeout")
                synced_users.append(self._uid)
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.garmin_pipeline as gp_mod
            with patch.object(gp_mod, "GarminPipeline", side_effect=FlakeyPipeline):
                sched_mod._run_garmin_multi_user()  # must NOT raise

        assert synced_users == [USER_B]

    def test_whoop_pipeline_error_user_a_does_not_block_user_b(self):
        """Whoop pipeline failure for user A: user B still syncs."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "whoop_connected": True},
            {"user_id": USER_B, "whoop_connected": True},
        ]
        synced_users = []
        mock_log = MagicMock(records_stored=2, status="success")

        class FlakeyWhoopPipeline:
            def __init__(self, db, *, user_id):
                self._uid = user_id

            async def run(self):
                if self._uid == USER_A:
                    raise RuntimeError("upstream API down")
                synced_users.append(self._uid)
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.whoop_pipeline as wp_mod
            with patch.object(wp_mod, "WhoopPipeline", side_effect=FlakeyWhoopPipeline):
                sched_mod._run_whoop_multi_user()  # must NOT raise

        assert synced_users == [USER_B]

    def test_whoop_token_failure_removes_token_and_continues(self):
        """Whoop token expiry for user A: token removed, user B still syncs."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": USER_A, "whoop_connected": True},
            {"user_id": USER_B, "whoop_connected": True},
        ]
        synced_users = []
        mock_log = MagicMock(records_stored=1, status="success")

        class TokenFailPipeline:
            def __init__(self, db, *, user_id):
                self._uid = user_id

            async def run(self):
                if self._uid == USER_A:
                    raise Exception("Token refresh failed: 401")
                synced_users.append(self._uid)
                return mock_log

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        deleted_keys = []
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = lambda stmt, params=None: (
            deleted_keys.append(params.get("key")) if params and "key" in params else None
        )
        mock_begin_ctx = MagicMock()
        mock_begin_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_begin_ctx.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.begin.return_value = mock_begin_ctx

        with (
            patch.object(deps_mod, "_engine", mock_engine),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.time"),
        ):
            import src.ingestion.whoop_pipeline as wp_mod
            with patch.object(wp_mod, "WhoopPipeline", side_effect=TokenFailPipeline):
                sched_mod._run_whoop_multi_user()

        assert synced_users == [USER_B]
        assert f"whoop_{USER_A}" in deleted_keys


# ===========================================================================
# 3. Rate limiting respects API constraints
# ===========================================================================


class TestRateLimiting:
    """Sleep is called the correct number of times between user syncs."""

    def test_garmin_sleeps_2s_between_users(self):
        """time.sleep(2) called N-1 times for N Garmin users."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [
            {"user_id": f"u{i}", "garmin_auto_sync": False, "garmin_has_token": True}
            for i in range(3)
        ]
        mock_log = MagicMock(records_stored=0, status="success")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        sleep_calls = []

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
            patch("src.ingestion.scheduler.time") as mock_time,
        ):
            mock_time.sleep.side_effect = lambda n: sleep_calls.append(n)
            import src.ingestion.garmin_pipeline as gp_mod
            with patch.object(gp_mod, "GarminPipeline", return_value=MagicMock(run=MagicMock(return_value=mock_log))):
                sched_mod._run_garmin_multi_user()

        # 3 users → 2 sleeps, each of 2 seconds
        assert len(sleep_calls) == 2
        assert all(s == 2 for s in sleep_calls)

    def test_garmin_no_sleep_for_single_user(self):
        """time.sleep is not called when there is only one Garmin user."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [{"user_id": USER_A, "garmin_auto_sync": False, "garmin_has_token": True}]
        mock_log = MagicMock(records_stored=0, status="success")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
            patch("src.ingestion.scheduler.time") as mock_time,
        ):
            import src.ingestion.garmin_pipeline as gp_mod
            with patch.object(gp_mod, "GarminPipeline", return_value=MagicMock(run=MagicMock(return_value=mock_log))):
                sched_mod._run_garmin_multi_user()

        mock_time.sleep.assert_not_called()

    def test_whoop_sleeps_1s_between_users(self):
        """time.sleep(1) called N-1 times for N Whoop users."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [{"user_id": f"u{i}", "whoop_connected": True} for i in range(4)]
        mock_log = MagicMock(records_stored=0, status="success")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        sleep_calls = []

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.time") as mock_time,
        ):
            mock_time.sleep.side_effect = lambda n: sleep_calls.append(n)
            import src.ingestion.whoop_pipeline as wp_mod
            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_log)
            with patch.object(wp_mod, "WhoopPipeline", return_value=mock_pipeline):
                sched_mod._run_whoop_multi_user()

        # 4 users → 3 sleeps, each of 1 second
        assert len(sleep_calls) == 3
        assert all(s == 1 for s in sleep_calls)

    def test_whoop_no_sleep_for_single_user(self):
        """time.sleep is not called when there is only one Whoop user."""
        import src.api.dependencies as deps_mod
        import src.ingestion.scheduler as sched_mod

        users = [{"user_id": USER_A, "whoop_connected": True}]
        mock_log = MagicMock(records_stored=0, status="success")
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(deps_mod, "_engine", MagicMock()),
            patch.object(sched_mod, "get_users_to_sync", return_value=users),
            patch("src.ingestion.scheduler.get_session_factory", return_value=MagicMock(return_value=mock_session)),
            patch("src.ingestion.scheduler.time") as mock_time,
        ):
            import src.ingestion.whoop_pipeline as wp_mod
            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_log)
            with patch.object(wp_mod, "WhoopPipeline", return_value=mock_pipeline):
                sched_mod._run_whoop_multi_user()

        mock_time.sleep.assert_not_called()


# ===========================================================================
# 4. Sync status is per-user
# ===========================================================================


@pytest.fixture(scope="module")
def sync_client():
    engine = _make_engine()
    _seed_user(engine, USER_A)
    _seed_user(engine, USER_B)
    client = _make_client(engine)
    yield client, engine
    # cleanup
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_engine_dep, None)


class TestSyncStatusPerUser:
    """GET /api/sync/status returns only the authenticated user's data."""

    def test_status_scoped_to_requesting_user(self, sync_client):
        """User A only sees their own records in /api/sync/status."""
        client, engine = sync_client

        now = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        _sync_log_success(engine, "whoop", USER_A, now)
        _sync_log_success(engine, "garmin", USER_B, stale)

        r = client.get("/api/sync/status", headers=_auth_header(USER_A))
        assert r.status_code == 200
        sources = {item["source"]: item for item in r.json()}

        # User A has a recent Whoop sync
        assert sources["whoop"]["status"] == "success"
        # User A has no Garmin sync — should be "never_synced"
        assert sources["garmin"]["status"] == "never_synced"

    def test_running_sync_key_is_per_user(self):
        """_running_syncs uses '{source}:{user_id}' keys — no cross-user collision."""
        from src.api.routes.sync import _running_syncs, _sync_key

        _running_syncs.clear()
        key_a = _sync_key("garmin", USER_A)
        key_b = _sync_key("garmin", USER_B)

        assert key_a != key_b
        assert ":" in key_a

        _running_syncs[key_a] = True
        # User B's key is unaffected
        assert _running_syncs.get(key_b, False) is False
        _running_syncs.clear()

    def test_trigger_for_user_a_does_not_block_user_b(self, sync_client):
        """409 conflict is per-user: user A in-progress doesn't block user B."""
        from src.api.routes import sync as sync_mod

        client, engine = sync_client
        _seed_whoop_token(engine, USER_A)
        _seed_whoop_token(engine, USER_B)

        # Manually mark user A's whoop sync as running
        sync_mod._running_syncs[sync_mod._sync_key("whoop", USER_A)] = True

        try:
            with patch("src.api.routes.sync.asyncio.create_task"):
                r = client.post("/api/sync/trigger/whoop", headers=_auth_header(USER_B))
            # User B should NOT get a 409 — their key is clear
            assert r.status_code == 200
        finally:
            sync_mod._running_syncs.pop(sync_mod._sync_key("whoop", USER_A), None)
            sync_mod._running_syncs.pop(sync_mod._sync_key("whoop", USER_B), None)

    def test_trigger_returns_409_for_same_user_in_progress(self, sync_client):
        """POST /api/sync/trigger returns 409 if the same user already has a running sync."""
        from src.api.routes import sync as sync_mod

        client, engine = sync_client
        _seed_whoop_token(engine, USER_A)

        sync_mod._running_syncs[sync_mod._sync_key("whoop", USER_A)] = True
        try:
            r = client.post("/api/sync/trigger/whoop", headers=_auth_header(USER_A))
            assert r.status_code == 409
        finally:
            sync_mod._running_syncs.pop(sync_mod._sync_key("whoop", USER_A), None)

    def test_garmin_trigger_works_with_credentials_no_token(self, sync_client, monkeypatch):
        """User with only credentials (no session token) can trigger Garmin sync."""
        monkeypatch.setenv("GARMIN_ENCRYPTION_KEY", TEST_ENC_KEY)
        client, engine = sync_client
        _seed_garmin_credentials(engine, USER_B, TEST_ENC_KEY)

        with patch("src.api.routes.sync.asyncio.create_task"):
            r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_B))
        assert r.status_code == 200

        from src.api.routes import sync as sync_mod
        sync_mod._running_syncs.pop(sync_mod._sync_key("garmin", USER_B), None)

    def test_garmin_trigger_403_when_no_connection(self, sync_client):
        """User with no Garmin token and no credentials gets 403."""
        client, engine = sync_client
        # USER_A has no garmin token and no credentials (only whoop from earlier test)
        r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_A))
        assert r.status_code == 403

    def test_whoop_trigger_403_when_not_connected(self, sync_client):
        """User with no Whoop token gets 403 on trigger."""
        engine = _make_engine()
        _seed_user(engine, USER_A)
        client = _make_client(engine)

        r = client.post("/api/sync/trigger/whoop", headers=_auth_header(USER_A))
        assert r.status_code == 403


# ===========================================================================
# 5. Container restart triggers catch-up syncs
# ===========================================================================


class TestCatchupOnRestart:
    """_schedule_catchup_if_stale schedules jobs for stale sources."""

    def test_schedules_catchup_when_no_sync_exists(self):
        """No sync_log rows → catchup scheduled for both sources."""
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        mock_scheduler = MagicMock()

        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)

        call_kwargs = [c[1] for c in mock_scheduler.add_job.call_args_list]
        scheduled_ids = {kw.get("id") for kw in call_kwargs}
        assert "garmin_catchup" in scheduled_ids
        assert "whoop_catchup" in scheduled_ids

    def test_schedules_catchup_when_last_sync_is_stale(self):
        """sync_log success older than threshold → catchup scheduled."""
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, USER_A)
        stale_time = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        _sync_log_success(engine, "garmin", USER_A, stale_time)
        _sync_log_success(engine, "whoop", USER_A, stale_time)

        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)

        call_kwargs = [c[1] for c in mock_scheduler.add_job.call_args_list]
        scheduled_ids = {kw.get("id") for kw in call_kwargs}
        assert "garmin_catchup" in scheduled_ids
        assert "whoop_catchup" in scheduled_ids

    def test_no_catchup_when_recent_sync_exists(self):
        """sync_log success within threshold → no catchup job added."""
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, USER_A)
        recent_time = datetime.now(UTC).isoformat()
        _sync_log_success(engine, "garmin", USER_A, recent_time)
        _sync_log_success(engine, "whoop", USER_A, recent_time)

        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)

        mock_scheduler.add_job.assert_not_called()

    def test_catchup_uses_multi_user_job_functions(self):
        """Catchup jobs reference the multi-user sync functions."""
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()  # empty — all sources stale
        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)

        job_funcs = [c[0][0] for c in mock_scheduler.add_job.call_args_list]
        assert sched_mod._run_garmin_multi_user in job_funcs
        assert sched_mod._run_whoop_multi_user in job_funcs

    def test_partial_catchup_only_stale_source(self):
        """Only the stale source gets a catchup — the fresh one does not."""
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, USER_A)
        recent_time = datetime.now(UTC).isoformat()
        stale_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        _sync_log_success(engine, "whoop", USER_A, recent_time)
        _sync_log_success(engine, "garmin", USER_A, stale_time)

        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)

        call_kwargs = [c[1] for c in mock_scheduler.add_job.call_args_list]
        scheduled_ids = {kw.get("id") for kw in call_kwargs}
        assert "garmin_catchup" in scheduled_ids
        assert "whoop_catchup" not in scheduled_ids
