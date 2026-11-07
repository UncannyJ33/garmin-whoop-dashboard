"""initial_sync refuses to run without an owner account."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.initial_sync import main
from src.clients.whoop_auth import WhoopAuthError
from src.database.connection import get_engine


def test_initial_sync_exits_without_owner(capsys: pytest.CaptureFixture[str]) -> None:
    """With no owner row, main() prints guidance and exits 1 before building pipelines."""
    engine = get_engine("sqlite:///:memory:")
    with (
        patch("scripts.initial_sync.get_engine", return_value=engine),
        patch("scripts.initial_sync.WhoopPipeline") as whoop_cls,
        patch("scripts.initial_sync.GarminPipeline") as garmin_cls,
        pytest.raises(SystemExit) as exc,
    ):
        asyncio.run(main())

    assert exc.value.code == 1
    assert "No owner account" in capsys.readouterr().out
    whoop_cls.assert_not_called()
    garmin_cls.assert_not_called()


def _owner_engine():
    """In-memory engine with migrations applied and one owner row."""
    from sqlalchemy import text

    from src.database.migrations import run

    engine = get_engine("sqlite:///:memory:")
    run(engine=engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, hashed_password, created_at, is_active)"
                " VALUES ('owner-1', 'o@example.com', 'x', '2026-01-01T00:00:00', 1)"
            )
        )
    return engine


def _log() -> MagicMock:
    log = MagicMock()
    log.status = "success"
    log.error_message = None
    return log


def test_whoop_failure_still_runs_garmin_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Whoop pipeline exception does not stop Garmin; the script exits 1 at the end."""
    engine = _owner_engine()
    with (
        patch("scripts.initial_sync.get_engine", return_value=engine),
        patch("scripts.initial_sync.run_migrations"),
        patch("scripts.initial_sync.WhoopPipeline") as whoop_cls,
        patch("scripts.initial_sync.GarminPipeline") as garmin_cls,
        pytest.raises(SystemExit) as exc,
    ):
        whoop_cls.return_value.run = AsyncMock(side_effect=WhoopAuthError("nope"))
        garmin_cls.return_value.run.return_value = _log()
        asyncio.run(main())

    assert exc.value.code == 1
    garmin_cls.assert_called_once()
    garmin_cls.return_value.run.assert_called_once()
    out = capsys.readouterr().out
    assert "Whoop sync FAILED" in out
    assert "Garmin Sync Summary" in out


def test_both_sources_succeed_exits_zero() -> None:
    """When both sources succeed, main() returns normally (exit 0)."""
    engine = _owner_engine()
    with (
        patch("scripts.initial_sync.get_engine", return_value=engine),
        patch("scripts.initial_sync.run_migrations"),
        patch("scripts.initial_sync.WhoopPipeline") as whoop_cls,
        patch("scripts.initial_sync.GarminPipeline") as garmin_cls,
    ):
        whoop_cls.return_value.run = AsyncMock(return_value=_log())
        garmin_cls.return_value.run.return_value = _log()
        asyncio.run(main())  # no SystemExit
