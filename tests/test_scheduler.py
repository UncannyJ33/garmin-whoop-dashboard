"""Tests for the Garmin + Whoop background scheduler.

Covers:
- Scheduler is not started when TESTING env var is set
- start_scheduler / stop_scheduler lifecycle (idempotency)
- _run_garmin_sync error handling (exceptions don't propagate)
- _run_whoop_sync error handling (exceptions don't propagate)
- create_scheduler respects interval_minutes for both sources
- get_scheduler_status returns correct running/stopped state
- FastAPI lifespan wires start/stop correctly
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
        patch.object(sched_mod, "load_garmin_tokens_from_db", return_value=False),
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
# _run_garmin_multi_user error handling
# ---------------------------------------------------------------------------


def test_run_garmin_multi_user_suppresses_exceptions():
    """_run_garmin_multi_user must not propagate exceptions from get_users_to_sync."""
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod

    with (
        patch.object(deps_mod, "_engine", MagicMock()),
        patch.object(
            sched_mod, "get_users_to_sync", side_effect=RuntimeError("DB down")
        ),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        sched_mod._run_garmin_multi_user()  # must NOT raise

    mock_logger.exception.assert_called()


def test_run_garmin_multi_user_logs_completion_on_success():
    """_run_garmin_multi_user logs completion when the pipeline succeeds."""
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod

    mock_log = MagicMock()
    mock_log.records_stored = 7
    mock_log.status = "success"

    mock_pipeline = MagicMock()
    mock_pipeline.run.return_value = mock_log

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session)

    # One user with a garth token (no credentials — simulates legacy owner)
    users = [{"user_id": "owner-id", "garmin_auto_sync": False, "garmin_has_token": True}]

    with (
        patch.object(deps_mod, "_engine", MagicMock()),
        patch.object(sched_mod, "get_users_to_sync", return_value=users),
        patch("src.ingestion.scheduler.get_session_factory", return_value=mock_session_factory),
        patch("src.ingestion.scheduler.save_garmin_tokens_to_db"),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        import src.ingestion.garmin_pipeline as gp_mod

        with patch.object(gp_mod, "GarminPipeline", return_value=mock_pipeline):
            sched_mod._run_garmin_multi_user()

    mock_pipeline.run.assert_called_once()
    completion_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("7" in c for c in completion_calls)


# ---------------------------------------------------------------------------
# _run_whoop_multi_user error handling
# ---------------------------------------------------------------------------


def test_run_whoop_multi_user_suppresses_exceptions():
    """_run_whoop_multi_user must not propagate exceptions from get_users_to_sync."""
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod

    with (
        patch.object(deps_mod, "_engine", MagicMock()),
        patch.object(
            sched_mod, "get_users_to_sync", side_effect=RuntimeError("DB down")
        ),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        sched_mod._run_whoop_multi_user()  # must NOT raise

    mock_logger.exception.assert_called()


def test_run_whoop_multi_user_logs_completion_on_success():
    """_run_whoop_multi_user logs completion when the pipeline succeeds."""
    import src.api.dependencies as deps_mod
    import src.ingestion.scheduler as sched_mod

    mock_log = MagicMock()
    mock_log.records_stored = 3
    mock_log.status = "success"

    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=mock_log)

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session)

    users = [{"user_id": "user-abc", "whoop_connected": True}]

    with (
        patch.object(deps_mod, "_engine", MagicMock()),
        patch.object(sched_mod, "get_users_to_sync", return_value=users),
        patch("src.ingestion.scheduler.get_session_factory", return_value=mock_session_factory),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        import src.ingestion.whoop_pipeline as wp_mod

        with patch.object(wp_mod, "WhoopPipeline", return_value=mock_pipeline):
            sched_mod._run_whoop_multi_user()

    mock_logger.info.assert_called()
    completion_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("3" in c for c in completion_calls)


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
