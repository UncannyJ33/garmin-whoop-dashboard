"""Tests for the sync routes (status scoping, trigger gating) and the Garmin status endpoint."""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from config.settings import settings

# Ensure scheduler never starts during tests
os.environ.setdefault("TESTING", "1")

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
                "INSERT OR IGNORE INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES (:id, :email, 'x', '2026-01-01T00:00:00', 1)"
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


@pytest.fixture(scope="module")
def sync_client():
    engine = _make_engine()
    _seed_user(engine, USER_A)
    _seed_user(engine, USER_B)
    client = _make_client(engine)
    yield client, engine
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

    def test_manual_garmin_sync_rejected_without_key(self, sync_client):
        """POST /api/sync/trigger/garmin with no Personal API key returns 403."""
        client, engine = sync_client
        r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_A))
        assert r.status_code == 403

    def test_whoop_trigger_403_when_not_connected(self, sync_client):
        """User with no Whoop token gets 403 on trigger."""
        engine = _make_engine()
        _seed_user(engine, USER_A)
        client = _make_client(engine)

        r = client.post("/api/sync/trigger/whoop", headers=_auth_header(USER_A))
        assert r.status_code == 403

    def test_manual_garmin_sync_allowed_with_key(self, monkeypatch):
        """With the key set, the single owner may trigger a manual Garmin sync."""
        from src.api.dependencies import get_db, get_engine_dep
        from src.api.main import app
        from src.api.routes import sync as sync_mod

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        engine = _make_engine()
        _seed_user(engine, USER_A)
        client = _make_client(engine)
        try:
            with patch("src.api.routes.sync.asyncio.create_task") as mock_task:
                mock_task.side_effect = lambda coro: (coro.close(), MagicMock())[1]
                r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_A))
            assert r.status_code == 200
        finally:
            sync_mod._running_syncs.pop(sync_mod._sync_key("garmin", USER_A), None)
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_engine_dep, None)

    def test_manual_garmin_sync_rejected_for_non_owner(self, monkeypatch):
        """With two users, nobody may start a Garmin sync; the pipeline is never built."""
        from src.api.dependencies import get_db, get_engine_dep
        from src.api.main import app

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        engine = _make_engine()
        _seed_user(engine, USER_A)
        _seed_user(engine, USER_B)
        client = _make_client(engine)
        try:
            with (
                patch("src.api.routes.sync.asyncio.create_task") as mock_task,
                patch("src.ingestion.garmin_pipeline.GarminPipeline") as pipeline_cls,
            ):
                r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_B))
            assert r.status_code == 403
            mock_task.assert_not_called()
            pipeline_cls.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_engine_dep, None)

    def test_manual_garmin_sync_rejected_for_non_owner_single_other(self, monkeypatch):
        """A token for a user id that is not the (only) owner is rejected."""
        from src.api.dependencies import get_db, get_engine_dep
        from src.api.main import app

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        engine = _make_engine()
        _seed_user(engine, USER_A)
        client = _make_client(engine)
        try:
            with patch("src.api.routes.sync.asyncio.create_task") as mock_task:
                r = client.post("/api/sync/trigger/garmin", headers=_auth_header(USER_B))
            assert r.status_code == 403
            mock_task.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_engine_dep, None)


class TestManualSyncTask:
    """_run_sync_task handles the pipeline's None (lock-skipped) and error results."""

    @pytest.mark.anyio
    @pytest.mark.parametrize("result", [None, MagicMock(status="error")])
    async def test_garmin_lock_skip_and_error_logged_not_raised(self, result, caplog):
        import logging

        from src.api.routes import sync as sync_mod

        engine = _make_engine()
        key = sync_mod._sync_key("garmin", USER_A)
        sync_mod._running_syncs[key] = True
        pipeline = MagicMock()
        pipeline.run.return_value = result
        with (
            patch("src.ingestion.garmin_pipeline.GarminPipeline", return_value=pipeline),
            caplog.at_level(logging.INFO, logger="src.api.routes.sync"),
        ):
            await sync_mod._run_sync_task("garmin", engine, USER_A)
        assert key not in sync_mod._running_syncs
        text_ = caplog.text
        if result is None:
            assert "skipped (another Garmin sync running)" in text_
            assert "Manual sync complete" not in text_
        else:
            assert "status=error" in text_


# ===========================================================================
# GET /api/auth/garmin/status
# ===========================================================================


@pytest.fixture
def status_client(monkeypatch):
    import src.api.routes.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_garmin_probe_cache", None)
    engine = _make_engine()
    _seed_user(engine, USER_A)
    client = _make_client(engine)
    yield client
    from src.api.dependencies import get_db, get_engine_dep
    from src.api.main import app

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_engine_dep, None)


def _stub_client(monkeypatch, *, raises=None, calls=None):
    """Replace GarminClient so the probe never touches the network."""
    import src.clients.garmin_client as gc_mod

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def get_user_settings(self):
            if calls is not None:
                calls.append(1)
            if raises is not None:
                raise raises
            return {"displayName": "secret-name", "timeZone": "UTC"}

    monkeypatch.setattr(gc_mod, "GarminClient", _Stub)


class TestGarminStatus:
    def _get(self, client):
        return client.get("/api/auth/garmin/status", headers=_auth_header(USER_A))

    def test_garmin_status_unconfigured(self, status_client):
        r = self._get(status_client)
        assert r.json() == {"connected": False, "configured": False, "error": None}

    def test_garmin_status_connected(self, status_client, monkeypatch):
        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        _stub_client(monkeypatch)
        r = self._get(status_client)
        assert r.json() == {"connected": True, "configured": True, "error": None}
        assert "secret-name" not in r.text

    def test_garmin_status_reports_key_error(self, status_client, monkeypatch):
        from src.clients.garmin_personal_auth import GarminKeyError

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        _stub_client(monkeypatch, raises=GarminKeyError("rejected"))
        r = self._get(status_client)
        assert r.json() == {"connected": False, "configured": True, "error": "rejected"}

    def test_garmin_status_transient_error_not_connected(self, status_client, monkeypatch):
        from src.clients.garmin_personal_auth import GarminTransientError, get_default_auth

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        _stub_client(monkeypatch, raises=GarminTransientError("boom"))
        r = self._get(status_client)
        assert r.json() == {"connected": False, "configured": True, "error": "boom"}
        assert get_default_auth().last_error is None

    def test_garmin_status_unexpected_probe_exception_does_not_500(
        self, status_client, monkeypatch
    ):
        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        _stub_client(monkeypatch, raises=ValueError("https://secret.example/url"))
        r = self._get(status_client)
        assert r.status_code == 200
        assert r.json() == {"connected": False, "configured": True, "error": "ValueError"}
        assert "secret.example" not in r.text

    def test_garmin_status_reports_scheduler_key_error_without_probe(
        self, status_client, monkeypatch
    ):
        from src.clients.garmin_personal_auth import get_default_auth

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        calls: list[int] = []
        _stub_client(monkeypatch, calls=calls)
        get_default_auth().last_error = "key rejected by scheduler"
        r = self._get(status_client)
        assert r.json() == {
            "connected": False,
            "configured": True,
            "error": "key rejected by scheduler",
        }
        assert calls == []

    def test_garmin_status_probe_cached_then_bypassed_by_last_error(
        self, status_client, monkeypatch
    ):
        from src.clients.garmin_personal_auth import get_default_auth

        monkeypatch.setattr(settings, "garmin_personal_api_key", "k")
        calls: list[int] = []
        _stub_client(monkeypatch, calls=calls)
        self._get(status_client)
        self._get(status_client)
        assert calls == [1]  # second call served from cache
        get_default_auth().last_error = "now broken"
        assert self._get(status_client).json()["connected"] is False
        assert calls == [1]


def test_startup_refuses_empty_jwt_secret(monkeypatch):
    """Empty JWT_SECRET must fail fast at startup (forgeable tokens otherwise)."""
    import asyncio

    from src.api.main import app, lifespan

    monkeypatch.setattr(settings, "jwt_secret", "")

    async def _enter():
        async with lifespan(app):
            pass

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        asyncio.run(_enter())
