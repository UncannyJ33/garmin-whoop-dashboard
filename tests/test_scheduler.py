"""Tests for the Garmin + Whoop background scheduler.

Covers:
- Scheduler is not started when TESTING env var is set
- start_scheduler / stop_scheduler lifecycle (idempotency)
- get_owner_user_id and the single-owner Garmin / Whoop jobs
- catch-up scheduling on restart
- create_scheduler respects interval_minutes for both sources
- get_scheduler_status returns correct running/stopped state
- FastAPI lifespan wires start/stop correctly
"""

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from config.settings import settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_scheduler_module():
    """Reset the global _scheduler state between tests."""
    import src.ingestion.scheduler as sched_mod

    sched_mod._scheduler = None


# ---------------------------------------------------------------------------
# TESTING guard
# ---------------------------------------------------------------------------


def test_start_scheduler_no_op_when_testing_set(monkeypatch):
    """start_scheduler must not create a scheduler when TESTING is set."""
    monkeypatch.setenv("TESTING", "1")
    _reset_scheduler_module()

    import src.ingestion.scheduler as sched_mod

    with patch.object(sched_mod, "create_scheduler") as mock_create:
        sched_mod.start_scheduler()
        mock_create.assert_not_called()

    assert sched_mod._scheduler is None


# ---------------------------------------------------------------------------
# start_scheduler / stop_scheduler lifecycle
# ---------------------------------------------------------------------------


def test_start_scheduler_creates_and_starts(monkeypatch):
    """start_scheduler must create and start a BackgroundScheduler."""
    monkeypatch.delenv("TESTING", raising=False)
    _reset_scheduler_module()

    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.running = False

    with (
        patch.object(deps_mod, "_engine", MagicMock()),
        patch.object(sched_mod, "create_scheduler", return_value=mock_scheduler),
        patch.object(sched_mod, "_schedule_catchup_if_stale"),
    ):
        sched_mod.start_scheduler()

    mock_scheduler.start.assert_called_once()
    assert sched_mod._scheduler is mock_scheduler
    _reset_scheduler_module()


def test_start_scheduler_idempotent(monkeypatch):
    """Calling start_scheduler twice must not start the scheduler a second time."""
    monkeypatch.delenv("TESTING", raising=False)
    _reset_scheduler_module()

    import src.ingestion.scheduler as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.running = True  # simulate already running
    sched_mod._scheduler = mock_scheduler

    with patch.object(sched_mod, "create_scheduler") as mock_create:
        sched_mod.start_scheduler()
        mock_create.assert_not_called()

    mock_scheduler.start.assert_not_called()
    _reset_scheduler_module()


def test_stop_scheduler_shuts_down(monkeypatch):
    """stop_scheduler must call shutdown and clear _scheduler."""
    _reset_scheduler_module()

    import src.ingestion.scheduler as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    sched_mod._scheduler = mock_scheduler

    sched_mod.stop_scheduler()

    mock_scheduler.shutdown.assert_called_once_with(wait=False)
    assert sched_mod._scheduler is None


def test_stop_scheduler_idempotent_when_not_running():
    """stop_scheduler must not raise if the scheduler is already stopped."""
    _reset_scheduler_module()

    import src.ingestion.scheduler as sched_mod

    # No scheduler running at all
    sched_mod.stop_scheduler()  # must not raise

    # Scheduler exists but not running
    mock_scheduler = MagicMock()
    mock_scheduler.running = False
    sched_mod._scheduler = mock_scheduler
    sched_mod.stop_scheduler()  # must not raise
    _reset_scheduler_module()


# ---------------------------------------------------------------------------
# create_scheduler
# ---------------------------------------------------------------------------


def test_create_scheduler_uses_default_garmin_interval(monkeypatch):
    """create_scheduler uses settings.garmin_poll_interval_minutes by default."""
    import src.ingestion.scheduler as sched_mod

    mock_settings = MagicMock()
    mock_settings.garmin_poll_interval_minutes = 30

    captured = []

    def fake_add_job(func, trigger, minutes, **kwargs):
        captured.append({"func": func, "minutes": minutes, "id": kwargs.get("id")})

    mock_bs = MagicMock()
    mock_bs.add_job.side_effect = fake_add_job

    with (
        patch("src.ingestion.scheduler.settings", mock_settings),
        patch("src.ingestion.scheduler.BackgroundScheduler", return_value=mock_bs),
    ):
        sched_mod.create_scheduler()

    garmin_job = next(c for c in captured if c["id"] == "garmin_incremental_sync")
    assert garmin_job["minutes"] == 30


def test_create_scheduler_respects_explicit_intervals():
    """create_scheduler honours explicit garmin_interval_minutes / whoop_interval_minutes."""
    import src.ingestion.scheduler as sched_mod

    captured = []

    def fake_add_job(func, trigger, minutes, **kwargs):
        captured.append({"minutes": minutes, "id": kwargs.get("id")})

    mock_bs = MagicMock()
    mock_bs.add_job.side_effect = fake_add_job

    with patch("src.ingestion.scheduler.BackgroundScheduler", return_value=mock_bs):
        sched_mod.create_scheduler(garmin_interval_minutes=5, whoop_interval_minutes=10)

    garmin_job = next(c for c in captured if c["id"] == "garmin_incremental_sync")
    whoop_job = next(c for c in captured if c["id"] == "whoop_incremental_sync")
    assert garmin_job["minutes"] == 5
    assert whoop_job["minutes"] == 10


def test_create_scheduler_default_whoop_interval():
    """create_scheduler uses 30-minute default for Whoop interval."""
    import src.ingestion.scheduler as sched_mod

    captured = []

    def fake_add_job(func, trigger, minutes, **kwargs):
        captured.append({"minutes": minutes, "id": kwargs.get("id")})

    mock_bs = MagicMock()
    mock_bs.add_job.side_effect = fake_add_job

    with patch("src.ingestion.scheduler.BackgroundScheduler", return_value=mock_bs):
        sched_mod.create_scheduler()

    whoop_job = next(c for c in captured if c["id"] == "whoop_incremental_sync")
    assert whoop_job["minutes"] == 30


# ---------------------------------------------------------------------------
# Single-owner helpers
# ---------------------------------------------------------------------------

OWNER = "owner-0001"


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


def _session_factory():
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_session)


@pytest.fixture
def garmin_key(monkeypatch):
    monkeypatch.setattr(settings, "garmin_personal_api_key", "test-key")


@pytest.fixture(autouse=True)
def _reset_no_key_flag():
    import src.ingestion.scheduler as sched_mod

    sched_mod._garmin_no_key_logged = False
    yield


# ---------------------------------------------------------------------------
# get_owner_user_id
# ---------------------------------------------------------------------------


def test_get_owner_user_id_none_one_many():
    from src.database.owner import get_owner_user_id

    engine = _make_engine()
    assert get_owner_user_id(engine) is None
    _seed_user(engine, "u-1")
    assert get_owner_user_id(engine) == "u-1"
    _seed_user(engine, "u-2")
    with pytest.raises(RuntimeError):
        get_owner_user_id(engine)


# ---------------------------------------------------------------------------
# _run_garmin_sync
# ---------------------------------------------------------------------------


def _run_garmin_job(engine, pipeline_cls):
    import src.api.dependencies as deps_mod
    import src.ingestion.garmin_pipeline as gp_mod
    import src.ingestion.scheduler as sched_mod

    with (
        patch.object(deps_mod, "_engine", engine),
        patch.object(gp_mod, "GarminPipeline", pipeline_cls),
        patch("src.ingestion.scheduler.get_session_factory", return_value=_session_factory()),
    ):
        sched_mod._run_garmin_sync()


def test_garmin_job_skips_when_multiple_users(garmin_key, caplog):
    engine = _make_engine()
    _seed_user(engine, "u-1")
    _seed_user(engine, "u-2")
    pipeline_cls = MagicMock()
    with caplog.at_level(logging.ERROR, logger="src.ingestion.scheduler"):
        _run_garmin_job(engine, pipeline_cls)
    pipeline_cls.assert_not_called()
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_garmin_job_skips_without_key():
    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    _run_garmin_job(engine, pipeline_cls)
    pipeline_cls.assert_not_called()


def test_garmin_job_skips_without_owner(garmin_key):
    pipeline_cls = MagicMock()
    _run_garmin_job(_make_engine(), pipeline_cls)
    pipeline_cls.assert_not_called()


def test_garmin_job_runs_for_owner(garmin_key):
    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run.return_value = MagicMock(
        status="success", records_fetched=4, records_stored=3, error_message=None
    )
    _run_garmin_job(engine, pipeline_cls)
    assert pipeline_cls.call_args.kwargs["user_id"] == OWNER
    pipeline_cls.return_value.run.assert_called_once_with()


def test_garmin_job_logs_error_status_without_raising(garmin_key, caplog):
    from src.database.models import SyncLog

    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run.return_value = SyncLog(
        status="error", error_message="key rejected"
    )  # counts are None
    with caplog.at_level(logging.INFO, logger="src.ingestion.scheduler"):
        _run_garmin_job(engine, pipeline_cls)
    assert "key rejected" in caplog.text


def test_garmin_job_handles_lock_skipped_none(garmin_key, caplog):
    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run.return_value = None
    with caplog.at_level(logging.INFO, logger="src.ingestion.scheduler"):
        _run_garmin_job(engine, pipeline_cls)
    assert "already running" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_garmin_job_suppresses_unexpected_exception(garmin_key):
    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run.side_effect = RuntimeError("boom")
    _run_garmin_job(engine, pipeline_cls)  # must not raise


# ---------------------------------------------------------------------------
# _run_whoop_sync
# ---------------------------------------------------------------------------


def _run_whoop_job(engine, pipeline_cls):
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod
    import src.ingestion.whoop_pipeline as wp_mod

    with (
        patch.object(deps_mod, "_engine", engine),
        patch.object(wp_mod, "WhoopPipeline", pipeline_cls),
        patch("src.ingestion.scheduler.get_session_factory", return_value=_session_factory()),
    ):
        sched_mod._run_whoop_sync()


def test_whoop_job_skips_without_token():
    engine = _make_engine()
    _seed_user(engine, OWNER)
    pipeline_cls = MagicMock()
    _run_whoop_job(engine, pipeline_cls)
    pipeline_cls.assert_not_called()


def test_whoop_job_skips_when_multiple_users():
    engine = _make_engine()
    _seed_user(engine, "u-1")
    _seed_user(engine, "u-2")
    _seed_whoop_token(engine, "u-1")
    pipeline_cls = MagicMock()
    _run_whoop_job(engine, pipeline_cls)
    pipeline_cls.assert_not_called()


def test_whoop_job_runs_for_owner_only():
    engine = _make_engine()
    _seed_user(engine, OWNER)
    _seed_whoop_token(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run = AsyncMock(
        return_value=MagicMock(records_stored=3, status="success")
    )
    _run_whoop_job(engine, pipeline_cls)
    assert pipeline_cls.call_args.kwargs["user_id"] == OWNER


def test_whoop_token_failure_removes_token_and_continues():
    """Whoop 401: token row removed, no exception escapes.

    Phase 3 changes this behavior (token rotation) — flip this test then.
    """
    engine = _make_engine()
    _seed_user(engine, OWNER)
    _seed_whoop_token(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run = AsyncMock(side_effect=Exception("Token refresh failed: 401"))
    _run_whoop_job(engine, pipeline_cls)  # must NOT raise
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM token_store WHERE service = :k"), {"k": f"whoop_{OWNER}"}
        ).scalar()
    assert n == 0


def test_whoop_transient_failure_keeps_token():
    engine = _make_engine()
    _seed_user(engine, OWNER)
    _seed_whoop_token(engine, OWNER)
    pipeline_cls = MagicMock()
    pipeline_cls.return_value.run = AsyncMock(side_effect=Exception("Token refresh failed: 503"))
    _run_whoop_job(engine, pipeline_cls)
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM token_store")).scalar()
    assert n == 1


# ---------------------------------------------------------------------------
# create_scheduler job registration
# ---------------------------------------------------------------------------


def test_scheduler_registers_two_jobs():
    import src.ingestion.scheduler as sched_mod

    scheduler = sched_mod.create_scheduler()
    jobs = {j.id: j for j in scheduler.get_jobs()}
    assert set(jobs) == {"garmin_incremental_sync", "whoop_incremental_sync"}
    garmin_interval = jobs["garmin_incremental_sync"].trigger.interval
    assert garmin_interval == timedelta(minutes=settings.garmin_poll_interval_minutes)
    assert jobs["garmin_incremental_sync"].func is sched_mod._run_garmin_sync
    assert jobs["whoop_incremental_sync"].func is sched_mod._run_whoop_sync


# ---------------------------------------------------------------------------
# Catch-up on restart
# ---------------------------------------------------------------------------


class TestCatchupOnRestart:
    """_schedule_catchup_if_stale schedules jobs for stale sources."""

    @staticmethod
    def _ids(mock_scheduler):
        return {c[1].get("id") for c in mock_scheduler.add_job.call_args_list}

    def test_schedules_catchup_when_no_sync_exists(self):
        import src.ingestion.scheduler as sched_mod

        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, _make_engine())
        assert {"garmin_catchup", "whoop_catchup"} <= self._ids(mock_scheduler)

    def test_schedules_catchup_when_last_sync_is_stale(self):
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, OWNER)
        stale = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        _sync_log_success(engine, "garmin", OWNER, stale)
        _sync_log_success(engine, "whoop", OWNER, stale)
        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)
        assert {"garmin_catchup", "whoop_catchup"} <= self._ids(mock_scheduler)

    def test_no_catchup_when_recent_sync_exists(self):
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, OWNER)
        recent = datetime.now(UTC).isoformat()
        _sync_log_success(engine, "garmin", OWNER, recent)
        _sync_log_success(engine, "whoop", OWNER, recent)
        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)
        mock_scheduler.add_job.assert_not_called()

    def test_catchup_jobs_use_single_owner_functions(self):
        import src.ingestion.scheduler as sched_mod

        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, _make_engine())
        job_funcs = [c[0][0] for c in mock_scheduler.add_job.call_args_list]
        assert sched_mod._run_garmin_sync in job_funcs
        assert sched_mod._run_whoop_sync in job_funcs

    def test_partial_catchup_only_stale_source(self):
        import src.ingestion.scheduler as sched_mod

        engine = _make_engine()
        _seed_user(engine, OWNER)
        _sync_log_success(engine, "whoop", OWNER, datetime.now(UTC).isoformat())
        _sync_log_success(
            engine, "garmin", OWNER, (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        )
        mock_scheduler = MagicMock()
        sched_mod._schedule_catchup_if_stale(mock_scheduler, engine)
        ids = self._ids(mock_scheduler)
        assert "garmin_catchup" in ids
        assert "whoop_catchup" not in ids


# ---------------------------------------------------------------------------
# get_scheduler_status
# ---------------------------------------------------------------------------


def test_get_scheduler_status_when_not_running():
    """get_scheduler_status returns running=False when scheduler is None."""
    _reset_scheduler_module()

    import src.ingestion.scheduler as sched_mod

    status = sched_mod.get_scheduler_status()
    assert status == {"running": False, "jobs": {}}


def test_get_scheduler_status_when_running():
    """get_scheduler_status returns running=True and job info when active."""
    _reset_scheduler_module()

    from datetime import UTC, datetime

    import src.ingestion.scheduler as sched_mod

    mock_job = MagicMock()
    mock_job.id = "garmin_incremental_sync"
    mock_job.name = "Garmin incremental sync"
    mock_job.next_run_time = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)

    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    mock_scheduler.get_jobs.return_value = [mock_job]
    sched_mod._scheduler = mock_scheduler

    status = sched_mod.get_scheduler_status()

    assert status["running"] is True
    assert "garmin_incremental_sync" in status["jobs"]
    assert status["jobs"]["garmin_incremental_sync"]["next_run_at"] is not None
    _reset_scheduler_module()


# ---------------------------------------------------------------------------
# FastAPI lifespan wires scheduler start/stop
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_lifespan_starts_and_stops_scheduler():
    """The FastAPI lifespan context manager must start then stop the scheduler."""
    import src.api.main as main_mod

    started = []
    stopped = []

    def fake_start():
        started.append(True)

    def fake_stop():
        stopped.append(True)

    # main.py binds start_scheduler/stop_scheduler at import time, so patch there.
    with (
        patch.object(main_mod, "start_scheduler", side_effect=fake_start),
        patch.object(main_mod, "stop_scheduler", side_effect=fake_stop),
    ):
        async with main_mod.lifespan(main_mod.app):
            assert started == [True]
            assert stopped == []

    assert stopped == [True]


# ---------------------------------------------------------------------------
# Real-session regression: SyncLog fields must be read inside the session
# ---------------------------------------------------------------------------


def _real_pipeline_cls(engine, source: str, *, is_async: bool):
    """Pipeline stand-in whose run() commits a real SyncLog on the real session."""
    from src.database.models import SyncLog

    class _Pipeline:
        def __init__(self, db, user_id=None):
            self._db = db
            self._user_id = user_id

        def _make_log(self):
            log = SyncLog(
                source=source,
                sync_type="incremental",
                started_at="2026-01-01T00:00:00",
                status="success",
                records_fetched=7,
                records_stored=5,
                user_id=self._user_id,
            )
            self._db.add(log)
            self._db.commit()  # expires the instance, as the real pipelines do
            return log

        if is_async:

            async def run(self):
                return self._make_log()
        else:

            def run(self):
                return self._make_log()

    return _Pipeline


def test_garmin_job_real_session_does_not_hit_detached_instance(garmin_key, caplog):
    engine = _make_engine()
    _seed_user(engine, OWNER)
    caplog.set_level(logging.INFO, logger="src.ingestion.scheduler")
    import src.api.dependencies as deps_mod
    import src.ingestion.garmin_pipeline as gp_mod
    import src.ingestion.scheduler as sched_mod

    with (
        patch.object(deps_mod, "_engine", engine),
        patch.object(
            gp_mod, "GarminPipeline", _real_pipeline_cls(engine, "garmin", is_async=False)
        ),
    ):
        sched_mod._run_garmin_sync()
    assert "unexpected error" not in caplog.text
    assert "Garmin sync: success (fetched 7, stored 5)" in caplog.text


def test_whoop_job_real_session_does_not_hit_detached_instance(caplog):
    engine = _make_engine()
    _seed_user(engine, OWNER)
    _seed_whoop_token(engine, OWNER)
    caplog.set_level(logging.INFO, logger="src.ingestion.scheduler")
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod
    import src.ingestion.whoop_pipeline as wp_mod

    with (
        patch.object(deps_mod, "_engine", engine),
        patch.object(wp_mod, "WhoopPipeline", _real_pipeline_cls(engine, "whoop", is_async=True)),
    ):
        sched_mod._run_whoop_sync()
    assert "unexpected error" not in caplog.text
    assert "Whoop sync: 5 stored (status: success)" in caplog.text
    with engine.connect() as conn:  # token must survive
        assert conn.execute(text("SELECT COUNT(*) FROM token_store")).scalar() == 1
