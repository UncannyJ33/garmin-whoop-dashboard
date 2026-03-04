"""Tests for the Garmin background scheduler.

Covers:
- Scheduler is not started when TESTING env var is set
- start_scheduler / stop_scheduler lifecycle (idempotency)
- _run_garmin_sync error handling (exceptions don't propagate)
- create_scheduler respects interval_minutes
- FastAPI lifespan wires start/stop correctly
"""

from unittest.mock import MagicMock, patch

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

    import src.ingestion.scheduler as sched_mod

    mock_scheduler = MagicMock()
    mock_scheduler.running = False

    with patch.object(sched_mod, "create_scheduler", return_value=mock_scheduler):
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


def test_create_scheduler_uses_default_interval(monkeypatch):
    """create_scheduler uses settings.garmin_poll_interval_minutes by default."""
    import src.ingestion.scheduler as sched_mod

    mock_settings = MagicMock()
    mock_settings.garmin_poll_interval_minutes = 30

    captured = {}

    def fake_add_job(func, trigger, minutes, **kwargs):
        captured["minutes"] = minutes

    mock_bs = MagicMock()
    mock_bs.add_job.side_effect = fake_add_job

    with (
        patch("src.ingestion.scheduler.settings", mock_settings),
        patch("src.ingestion.scheduler.BackgroundScheduler", return_value=mock_bs),
    ):
        sched_mod.create_scheduler()

    assert captured["minutes"] == 30


def test_create_scheduler_respects_explicit_interval():
    """create_scheduler honours an explicit interval_minutes argument."""
    import src.ingestion.scheduler as sched_mod

    captured = {}

    def fake_add_job(func, trigger, minutes, **kwargs):
        captured["minutes"] = minutes

    mock_bs = MagicMock()
    mock_bs.add_job.side_effect = fake_add_job

    with patch("src.ingestion.scheduler.BackgroundScheduler", return_value=mock_bs):
        sched_mod.create_scheduler(interval_minutes=5)

    assert captured["minutes"] == 5


# ---------------------------------------------------------------------------
# _run_garmin_sync error handling
# ---------------------------------------------------------------------------


def test_run_garmin_sync_logs_and_suppresses_exceptions():
    """_run_garmin_sync must catch all exceptions and not propagate them."""
    import src.ingestion.scheduler as sched_mod

    with (
        patch("src.ingestion.scheduler.get_engine", side_effect=RuntimeError("DB down")),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        sched_mod._run_garmin_sync()  # must NOT raise

    mock_logger.exception.assert_called_once()
    assert "failed" in mock_logger.exception.call_args[0][0]


def test_run_garmin_sync_logs_completion_on_success():
    """_run_garmin_sync logs completion when the pipeline succeeds."""
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

    with (
        patch("src.ingestion.scheduler.get_engine"),
        patch("src.ingestion.scheduler.run_migrations"),
        patch("src.ingestion.scheduler.get_session_factory", return_value=mock_session_factory),
        patch("src.ingestion.scheduler.GarminPipeline", return_value=mock_pipeline),
        patch("src.ingestion.scheduler.logger") as mock_logger,
    ):
        sched_mod._run_garmin_sync()

    mock_pipeline.run.assert_called_once()
    mock_logger.info.assert_called()
    # The completion log should mention records_stored
    completion_calls = [str(c) for c in mock_logger.info.call_args_list]
    assert any("7" in c for c in completion_calls)


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
