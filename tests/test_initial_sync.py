"""initial_sync refuses to run without an owner account."""

import asyncio
from unittest.mock import patch

import pytest

from scripts.initial_sync import main
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
