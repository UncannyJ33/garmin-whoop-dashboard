"""scripts/backfill.py: chunking, guards, failure handling, exit codes."""

from contextlib import ExitStack
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from scripts import backfill
from scripts.backfill import api_running, day_chunks, main, whoop_windows
from src.clients.whoop_auth import WhoopReauthRequired
from src.database.models import Base, SyncLog

TODAY = date(2026, 11, 7)
NOW = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
OWNER = "owner-1"


def _log(status: str = "success", stored: int = 5) -> MagicMock:
    return MagicMock(
        status=status, records_fetched=stored, records_stored=stored, error_message="boom"
    )


class Env:
    """Patched collaborators for one main() run."""

    def __init__(self, stack: ExitStack, **kw: Any) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        p = stack.enter_context
        self.probe = p(patch("scripts.backfill.api_running", return_value=kw.get("api", False)))
        self.migrate = p(patch("scripts.backfill.run_migrations"))
        p(patch("scripts.backfill.get_engine", return_value=self.engine))
        self.owner = p(
            patch("scripts.backfill.get_owner_user_id", **kw.get("owner", {"return_value": OWNER}))
        )
        p(patch("scripts.backfill._today", return_value=TODAY))
        p(patch("scripts.backfill._now", return_value=NOW))
        p(
            patch(
                "scripts.backfill.settings",
                SimpleNamespace(
                    app_port=8123, garmin_personal_api_key="k" if kw.get("garmin", True) else ""
                ),
            )
        )
        self.garmin_cls = p(patch("scripts.backfill.GarminPipeline"))
        self.garmin_run = self.garmin_cls.return_value.run
        self.garmin_run.side_effect = kw.get("garmin_side", lambda start, end: _log())
        self.whoop_cls = p(patch("scripts.backfill.WhoopPipeline"))
        self.whoop_run = AsyncMock(side_effect=kw.get("whoop_side", lambda start, end: _log()))
        self.whoop_cls.return_value.run = self.whoop_run
        auth = p(patch("scripts.backfill.WhoopAuth"))
        auth.has_token.return_value = kw.get("token", True)
        p(patch("scripts.backfill.whoop_auth_error", return_value=kw.get("auth_err")))
        self.refresh = p(patch("scripts.backfill.refresh_anomalies", return_value=7))

    def garmin_calls(self) -> list[tuple[date, date]]:
        return [(c.kwargs["start"], c.kwargs["end"]) for c in self.garmin_run.call_args_list]


def run(argv: list[str], **kw: Any) -> tuple[int, Env]:
    with ExitStack() as stack:
        env = Env(stack, **kw)
        code = main(argv)
    return code, env


def _start(days_back: int) -> str:
    return str(TODAY - timedelta(days=days_back))


def test_backfill_requires_owner() -> None:
    code, env = run(["--start", _start(5)], owner={"return_value": None})
    assert code == 1
    env.garmin_cls.assert_not_called()
    env.whoop_cls.assert_not_called()
    code, env = run(["--start", _start(5)], owner={"side_effect": RuntimeError("more than one")})
    assert code == 1
    env.garmin_cls.assert_not_called()


def test_backfill_refuses_when_api_up() -> None:
    code, env = run(["--start", _start(5)], api=True)
    assert code == 3
    env.migrate.assert_not_called()
    env.garmin_cls.assert_not_called()
    env.whoop_cls.assert_not_called()
    code, env = run(["--start", _start(5), "--force"], api=True)
    assert code == 0
    env.garmin_cls.assert_called()


def _resp(status: int = 200, body: dict | None = None, bad_json: bool = False) -> MagicMock:
    r = MagicMock(status_code=status)
    if bad_json:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = body
    return r


def test_probe_true_for_this_app() -> None:
    ok = _resp(200, {"status": "ok", "app": "pulse-dashboard"})
    with patch("scripts.backfill.httpx.get", return_value=ok) as g:
        assert api_running(8123) is True
    assert "127.0.0.1:8123/api/health" in g.call_args.args[0]


def test_probe_false_for_other_app(capsys: pytest.CaptureFixture[str]) -> None:
    for r in (
        _resp(200, {"app": "zoncheck"}),
        _resp(200, bad_json=True),
        _resp(404, {"detail": "nf"}),
    ):
        with patch("scripts.backfill.httpx.get", return_value=r):
            assert api_running(8000) is False
    assert (
        "Note: port 8000 is used by another program (not this dashboard)."
        in capsys.readouterr().out
    )


def test_probe_true_for_older_build_status_only(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("scripts.backfill.httpx.get", return_value=_resp(200, {"status": "ok"})):
        assert api_running(8000) is True
    assert "older build" in capsys.readouterr().out


def test_probe_ignores_proxy_env() -> None:
    with patch("scripts.backfill.httpx.get", return_value=_resp(200, {"app": "x"})) as g:
        api_running(8000)
    assert g.call_args.kwargs["trust_env"] is False
    assert g.call_args.kwargs["timeout"] == 1.0


def test_probe_true_on_timeout() -> None:
    with patch("scripts.backfill.httpx.get", side_effect=httpx.ReadTimeout("x")):
        assert api_running(8000) is True


def test_probe_false_on_connect_error() -> None:
    with patch("scripts.backfill.httpx.get", side_effect=httpx.ConnectError("x")):
        assert api_running(8000) is False


def test_backfill_chunks_oldest_first_and_end_today() -> None:
    code, env = run(["--source", "garmin", "--start", _start(65), "--chunk-days", "30"])
    assert code == 0
    calls = env.garmin_calls()
    assert len(calls) == 3
    assert calls == sorted(calls)
    assert calls[0][0] == TODAY - timedelta(days=65)
    assert calls[-1][1] == TODAY
    for (_, e1), (s2, _) in zip(calls, calls[1:], strict=False):
        assert s2 == e1 + timedelta(days=1)


def test_garmin_chunk_clamped_to_31_days() -> None:
    code, env = run(["--source", "garmin", "--start", _start(100), "--chunk-days", "60"])
    assert code == 0
    assert all((e - s).days + 1 <= 31 for s, e in env.garmin_calls())


@pytest.mark.parametrize(
    "now", [NOW, datetime(2026, 11, 9, 3, 0, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC)]
)
def test_whoop_windows_aware_contiguous_final_reaches_now(now) -> None:
    chunks = day_chunks(TODAY - timedelta(days=65), TODAY, 30)
    wins = whoop_windows(chunks, now)
    assert all(w.tzinfo == UTC for pair in wins for w in pair)
    for (_, e1), (s2, _) in zip(wins, wins[1:], strict=False):
        assert e1 == s2
    assert wins[-1][1] >= now
    assert wins[-1][1] >= datetime.combine(TODAY + timedelta(days=1), time.min, tzinfo=UTC)
    assert wins[-1][0] < wins[-1][1]


def test_backfill_stops_source_on_failed_chunk(capsys: pytest.CaptureFixture[str]) -> None:
    n = {"i": 0}

    def side(start, end):
        n["i"] += 1
        return _log("error") if n["i"] == 2 else _log()

    code, env = run(["--start", _start(65), "--chunk-days", "30"], garmin_side=side)
    assert code == 1
    calls = env.garmin_calls()
    assert len(calls) == 2
    env.whoop_run.assert_called()
    assert f"make backfill SOURCE=garmin START={calls[1][0]}" in capsys.readouterr().out


def test_backfill_stops_source_on_raised_exception(capsys: pytest.CaptureFixture[str]) -> None:
    n = {"i": 0}

    def side(start, end):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("kaput")
        return _log()

    code, env = run(["--start", _start(65), "--chunk-days", "30"], garmin_side=side)
    out = capsys.readouterr().out
    assert code == 1
    assert len(env.garmin_calls()) == 2
    env.whoop_run.assert_called()
    assert f"make backfill SOURCE=garmin START={env.garmin_calls()[1][0]}" in out

    def whoop_side(start, end):
        raise WhoopReauthRequired("nope")

    code, env = run(["--source", "whoop", "--start", _start(65)], whoop_side=whoop_side)
    out = capsys.readouterr().out
    assert code == 1
    assert env.whoop_run.call_count == 1
    assert "reconnect in Settings" in out
    assert "make backfill SOURCE=whoop START=" in out


def test_backfill_without_whoop_still_runs_garmin(capsys: pytest.CaptureFixture[str]) -> None:
    code, env = run(["--source", "all", "--start", _start(5)], token=False)
    assert code == 0
    env.whoop_cls.assert_not_called()
    env.garmin_run.assert_called()
    assert "connect Whoop in Settings" in capsys.readouterr().out


def test_backfill_skips_whoop_when_needs_reauth(capsys: pytest.CaptureFixture[str]) -> None:
    code, env = run(["--start", _start(5)], auth_err="expired")
    assert code == 0
    env.whoop_cls.assert_not_called()
    assert "needs reconnect" in capsys.readouterr().out


def test_backfill_nothing_to_run_returns_1() -> None:
    code, env = run(["--start", _start(5)], garmin=False, token=False)
    assert code == 1
    code, env = run(["--source", "whoop", "--start", _start(5)], token=False)
    assert code == 1


def test_backfill_refreshes_anomalies_once_over_full_range() -> None:
    code, env = run(["--start", _start(65)])
    assert code == 0
    env.refresh.assert_called_once_with(env.engine, OWNER, TODAY - timedelta(days=65), TODAY)
    code, env = run(
        ["--start", _start(65)],
        garmin_side=lambda start, end: _log(stored=0),
        whoop_side=lambda start, end: _log(stored=0),
    )
    env.refresh.assert_not_called()


def test_backfill_interrupt_returns_130(capsys: pytest.CaptureFixture[str]) -> None:
    def side(start, end):
        raise KeyboardInterrupt

    code, _ = run(["--source", "garmin", "--start", _start(5)], garmin_side=side)
    assert code == 130
    assert "make backfill SOURCE=garmin START=" in capsys.readouterr().out


def test_invalid_args_rejected() -> None:
    with ExitStack() as stack:
        Env(stack)
        for argv in (
            ["--start", str(TODAY + timedelta(days=1))],
            ["--start", _start(5), "--chunk-days", "0"],
        ):
            with pytest.raises(SystemExit) as exc:
                main(argv)
            assert exc.value.code == 2


def test_module_exports() -> None:
    assert backfill.GARMIN_MAX_CHUNK_DAYS == 31


def test_resume_hint_format() -> None:
    d = date(2025, 1, 1)
    assert backfill._resume_hint("garmin", d).splitlines()[0] == (
        "  Resume with: make backfill SOURCE=garmin START=2025-01-01"
    )
    assert backfill._resume_hint("garmin", d, port=8001, chunk_days=10).splitlines()[0] == (
        "  Resume with: make backfill SOURCE=garmin START=2025-01-01 PORT=8001 CHUNK_DAYS=10"
    )


def test_resume_hint_in_run_carries_port_and_chunk_days(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def side(start: date, end: date) -> None:
        raise RuntimeError("kaput")

    code, _ = run(
        ["--source", "garmin", "--start", _start(65), "--chunk-days", "10"], garmin_side=side
    )
    assert code == 1
    assert "PORT=8123 CHUNK_DAYS=10" in capsys.readouterr().out


def test_ctrl_c_in_anomaly_refresh_returns_130(capsys: pytest.CaptureFixture[str]) -> None:
    with ExitStack() as stack:
        env = Env(stack)
        env.refresh.side_effect = KeyboardInterrupt
        code = main(["--source", "garmin", "--start", _start(5)])
    assert code == 130
    out = capsys.readouterr().out
    assert "Interrupted." in out
    assert f"make backfill SOURCE=garmin START={_start(5)}" in out


def test_whoop_error_status_stops_source(capsys: pytest.CaptureFixture[str]) -> None:
    n = {"i": 0}

    def side(start: datetime, end: datetime) -> MagicMock:
        n["i"] += 1
        return _log("error")

    code, env = run(["--source", "whoop", "--start", _start(65)], whoop_side=side)
    assert code == 1
    assert env.whoop_run.call_count == 1
    assert "make backfill SOURCE=whoop START=" in capsys.readouterr().out


def test_session_rolled_back_after_garmin_db_error() -> None:
    """A DB error in the Garmin chunk must not poison the session for Whoop's checks."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)

    def boom(start: date, end: date) -> None:
        for _ in range(2):  # duplicate primary key -> failed flush
            db.add(SyncLog(id=1, source="x", sync_type="t", started_at="s", status="success"))
            db.flush()

    with patch("scripts.backfill.GarminPipeline") as cls:
        cls.return_value.run.side_effect = boom
        outcome, _ = backfill._run_garmin(db, OWNER, [(TODAY, TODAY)], lambda src, d: "hint")
    assert outcome == backfill.FAILED
    db.execute(text("select 1"))  # PendingRollbackError without the rollback
    db.close()
