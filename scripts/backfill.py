"""Backfill history from scratch, in chunks, oldest first.

Usage (from project root, venv active):
    python scripts/backfill.py --source {garmin,whoop,all} --start YYYY-MM-DD
        [--chunk-days N] [--daily-from YYYY-MM-DD] [--force]

The range always ends today. Both pipelines resume from the latest successful
SyncLog, so re-running after a failure continues where it stopped.

Garmin daily summaries only exist about 180 days back. Chunks older than that run
activities-only (no per-day calls): ``--daily-from`` sets the boundary, otherwise a short
probe finds it when ``--start`` is more than 180 days back.

Exit codes: 0 ok; 1 a source failed / no owner / several users / nothing ran;
2 usage error; 3 API server running and --force not given; 130 interrupted.
"""

import argparse
import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from src.analytics.anomaly_store import refresh_anomalies
from src.clients.garmin_client import GarminClient
from src.clients.garmin_personal_auth import GarminPersonalApiError
from src.clients.whoop_auth import WhoopAuth, WhoopReauthRequired, whoop_auth_error
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.models import SyncLog
from src.database.owner import get_owner_user_id
from src.ingestion.garmin_pipeline import GarminPipeline
from src.ingestion.whoop_pipeline import WhoopPipeline

logger = logging.getLogger(__name__)

GARMIN_MAX_CHUNK_DAYS = 31
DEFAULT_CHUNK_DAYS = 30
DAILY_HISTORY_DAYS = 180  # observed depth of Garmin daily summaries
DAILY_FROM_MARGIN_DAYS = 7

# Per-source outcomes.
OK, FAILED, SKIPPED = "ok", "failed", "skipped"


class _Interrupted(Exception):
    """Raised when Ctrl-C hits mid-chunk; carries the chunk start for the hint."""

    def __init__(self, source: str, chunk_start: date) -> None:
        super().__init__(source)
        self.source = source
        self.chunk_start = chunk_start


def _today() -> date:
    """Local calendar date (patched in tests)."""
    return datetime.now().date()


def _now() -> datetime:
    """Current aware UTC time (patched in tests)."""
    return datetime.now(tz=UTC)


def day_chunks(start: date, today: date, chunk_days: int) -> list[tuple[date, date]]:
    """Return inclusive, contiguous ``(start, end)`` day chunks, oldest first, ending today."""
    chunks: list[tuple[date, date]] = []
    s = start
    while s <= today:
        e = min(s + timedelta(days=chunk_days - 1), today)
        chunks.append((s, e))
        s = e + timedelta(days=1)
    return chunks


def whoop_windows(
    chunks: list[tuple[date, date]], now: datetime
) -> list[tuple[datetime, datetime]]:
    """Map day chunks to contiguous aware-UTC ``[start, end)`` windows; the last reaches ``now``."""
    windows = [
        (
            datetime.combine(s, time.min, tzinfo=UTC),
            datetime.combine(e + timedelta(days=1), time.min, tzinfo=UTC),
        )
        for s, e in chunks
    ]
    if windows:
        ws, we = windows[-1]
        windows[-1] = (ws, max(we, now))
    return windows


def api_running(port: int) -> bool:
    """Return True if this dashboard's API answers on ``port``; a timeout counts as running."""
    try:
        # trust_env=False: proxy env vars must not intercept a localhost probe.
        resp = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0, trust_env=False)
    except httpx.TimeoutException:
        return True
    except httpx.HTTPError:
        return False
    try:
        if resp.status_code == 200:
            body = resp.json()
            if body.get("app") == "pulse-dashboard":
                return True
            if body.get("status") == "ok" and "app" not in body:
                print(
                    f"Note: port {port} answers /api/health like an older build of this "
                    "dashboard; treating it as running."
                )
                return True
    except (ValueError, AttributeError):
        pass
    print(f"Note: port {port} is used by another program (not this dashboard).")
    return False


ResumeHint = Callable[[str, date], str]


def _resume_hint(source: str, chunk_start: date, port: int = 8001, chunk_days: int = 30) -> str:
    """Return the ``make backfill`` command that resumes from ``chunk_start``.

    ``PORT`` and ``CHUNK_DAYS`` are included only when they differ from the defaults.
    """
    extra = ""
    if port != 8001:
        extra += f" PORT={port}"
    if chunk_days != DEFAULT_CHUNK_DAYS:
        extra += f" CHUNK_DAYS={chunk_days}"
    return (
        f"  Resume with: make backfill SOURCE={source} START={chunk_start}{extra}\n"
        "  Run it before starting the server."
    )


def _print_chunk(source: str, s: date, e: date, log: SyncLog) -> None:
    print(
        f"  {source} {s} → {e}: {log.status} "
        f"(fetched {log.records_fetched}, stored {log.records_stored})"
    )


def _has_daily(client: GarminClient, d: date) -> bool:
    """Return True if any daily summary for ``d``, ``d+1`` or ``d+2`` is non-empty.

    A single empty day proves nothing (watch off all day looks like past-the-depth),
    so three days are checked; a 3-day all-off streak is the residual false negative.
    """
    return any(client.get_daily_summary(d + timedelta(days=i)) for i in range(3))


def _find_daily_from(client: GarminClient, start: date, today: date) -> date | None:
    """Find where Garmin daily summaries begin, or None to run daily on every chunk.

    Probes ``start`` (data -> None) and ``today - 180`` (no data -> the depth assumption
    no longer holds -> None), otherwise binary-searches the earliest date with data and
    subtracts a 7-day margin. Raises ``GarminPersonalApiError`` on API failure.
    """
    if _has_daily(client, start):
        return None
    recent = today - timedelta(days=DAILY_HISTORY_DAYS)
    if not _has_daily(client, recent):
        print(
            "  Note: no Garmin daily summaries found 180 days back either; the history-depth "
            "assumption no longer holds, so daily summaries run for every chunk."
        )
        return None
    lo, hi = start, recent  # lo: no data, hi: data
    while (hi - lo).days > 1:
        mid = lo + (hi - lo) // 2
        if _has_daily(client, mid):
            hi = mid
        else:
            lo = mid
    return hi - timedelta(days=DAILY_FROM_MARGIN_DAYS)


def _run_garmin(
    db: Session,
    owner: str,
    chunks: list[tuple[date, date]],
    hint: ResumeHint,
    daily_from: date | None = None,
) -> tuple[str, int]:
    """Run Garmin chunks oldest first; return ``(outcome, records_stored)``.

    Chunks ending before ``daily_from`` run activities-only (``daily=False``).
    The anomaly refresh is skipped per chunk; ``_run`` refreshes once at the end.
    """
    stored = 0
    for s, e in chunks:
        daily = daily_from is None or e >= daily_from
        try:
            log = GarminPipeline(db, user_id=owner).run(
                start=s, end=e, daily=daily, refresh_anomalies=False
            )
        except KeyboardInterrupt:
            db.rollback()
            raise _Interrupted("garmin", s) from None
        except Exception as exc:
            db.rollback()
            logger.exception("Garmin chunk %s → %s failed", s, e)
            print(f"  garmin {s} → {e}: FAILED {type(exc).__name__}: {exc}")
            print(hint("garmin", s))
            return FAILED, stored
        if log is None:
            print(f"  garmin {s} → {e}: skipped, another Garmin sync is running")
            print(hint("garmin", s))
            return FAILED, stored
        _print_chunk("garmin", s, e, log)
        if log.status == "error":
            print(f"    error: {log.error_message}")
            print(hint("garmin", s))
            return FAILED, stored
        stored += log.records_stored or 0
    return OK, stored


def _run_whoop(
    db: Session,
    owner: str,
    chunks: list[tuple[date, date]],
    windows: list[tuple[datetime, datetime]],
    hint: ResumeHint,
) -> tuple[str, int]:
    """Run Whoop windows oldest first; return ``(outcome, records_stored)``."""
    stored = 0
    for (s, e), (ws, we) in zip(chunks, windows, strict=True):
        try:
            log = asyncio.run(
                WhoopPipeline(db, user_id=owner).run(start=ws, end=we, refresh_anomalies=False)
            )
        except KeyboardInterrupt:
            db.rollback()
            raise _Interrupted("whoop", s) from None
        except WhoopReauthRequired:
            db.rollback()
            logger.exception("Whoop chunk %s → %s: token rejected", s, e)
            print("  Whoop rejected the token; reconnect in Settings, then resume.")
            print(hint("whoop", s))
            return FAILED, stored
        except Exception as exc:
            db.rollback()
            logger.exception("Whoop chunk %s → %s failed", s, e)
            print(f"  whoop {s} → {e}: FAILED {type(exc).__name__}: {exc}")
            print(hint("whoop", s))
            return FAILED, stored
        if log is None:
            print(f"  whoop {s} → {e}: skipped, another Whoop sync is running")
            print(hint("whoop", s))
            return FAILED, stored
        _print_chunk("whoop", s, e, log)
        if log.status == "error":
            print(f"    error: {log.error_message}")
            print(hint("whoop", s))
            return FAILED, stored
        stored += log.records_stored or 0
    return OK, stored


def _parse_args(argv: list[str] | None, today: date) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunked, oldest-first history backfill.")
    parser.add_argument("--source", choices=["garmin", "whoop", "all"], default="all")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--chunk-days", type=int, default=DEFAULT_CHUNK_DAYS)
    parser.add_argument(
        "--daily-from",
        type=date.fromisoformat,
        default=None,
        help="YYYY-MM-DD: Garmin chunks ending before this run activities-only (no probe)",
    )
    parser.add_argument("--force", action="store_true", help="run even if the API is up")
    args = parser.parse_args(argv)
    if args.start > today:
        parser.error("--start must not be in the future")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be >= 1")
    return args


def _resolve_daily_from(
    args: argparse.Namespace, today: date, chunks: list[tuple[date, date]]
) -> date | None:
    """Return the date daily summaries start from (None: every chunk runs daily); prints a note.

    ``--daily-from`` wins and needs no probe. Otherwise probe, but only when ``--start`` is
    more than 180 days back.
    """
    daily_from = args.daily_from
    if daily_from is None:
        if args.start >= today - timedelta(days=DAILY_HISTORY_DAYS):
            return None
        daily_from = _find_daily_from(GarminClient(), args.start, today)
        if daily_from is None:
            return None
    skipped = [c for c in chunks if c[1] < daily_from]
    if skipped:
        first_daily = next((c[0] for c in chunks if c[1] >= daily_from), today)
        print(
            f"  Garmin daily summaries start about {daily_from}; {len(skipped)} chunks before "
            f"{first_daily} run activities-only (override with --daily-from)."
        )
    return daily_from


def main(argv: list[str] | None = None) -> int:
    """Run the backfill; return the process exit code (130 on Ctrl-C, with a resume hint)."""
    today = _today()
    args = _parse_args(argv, today)
    port = settings.app_port

    def hint(source: str, chunk_start: date) -> str:
        return _resume_hint(source, chunk_start, port, args.chunk_days)

    try:
        return _run(args, today, port, hint)
    except _Interrupted as intr:
        print(f"\nInterrupted during {intr.source}.")
        print(hint(intr.source, intr.chunk_start))
        return 130
    except KeyboardInterrupt:
        print("\nInterrupted.")
        print(hint(args.source, args.start))
        return 130


def _run(argparse_args: argparse.Namespace, today: date, port: int, hint: ResumeHint) -> int:
    """Do the backfill work for ``main``; may raise ``_Interrupted`` / ``KeyboardInterrupt``."""
    args = argparse_args
    if api_running(port) and not args.force:
        print(
            f"The API server is running on port {port}; its scheduler would race the "
            "backfill. Stop it (Ctrl-C / `make down`), or force it: `make backfill ... FORCE=1` "
            "(`--force` when running the script directly)."
        )
        return 3

    engine = get_engine()
    try:
        run_migrations(engine=engine)
        try:
            owner = get_owner_user_id(engine)
        except RuntimeError as exc:
            print(f"{exc}")
            return 1
        if owner is None:
            print("No owner account. Run `make owner EMAIL=...` first.")
            return 1

        days = (today - args.start).days + 1
        print(
            f"Backfilling {days} days ({args.start} → {today}). Garmin makes about 3 calls "
            "per day at >= 1 s each, so 2 years takes about 40 min.\n"
            "Don't start the server until this finishes.\n"
            "Garmin daily summaries stop somewhere between 180 and 365 days back; older days "
            "log 'daily summary unavailable' and only activities come through. For older daily "
            "data, use a Garmin account export with `scripts/import_data.py`."
        )

        db = get_session_factory(engine)()
        outcomes: dict[str, str] = {}
        stored_total = 0
        try:
            if args.source in ("garmin", "all"):
                print("\nGarmin")
                if not settings.garmin_personal_api_key:
                    print("  Skipped: GARMIN_PERSONAL_API_KEY is not set.")
                    outcomes["garmin"] = SKIPPED
                else:
                    chunk_days = min(args.chunk_days, GARMIN_MAX_CHUNK_DAYS)
                    chunks = day_chunks(args.start, today, chunk_days)
                    try:
                        daily_from = _resolve_daily_from(args, today, chunks)
                    except GarminPersonalApiError as exc:
                        logger.exception("Garmin history-depth probe failed")
                        print(f"  probe FAILED {type(exc).__name__}: {exc}")
                        print(hint("garmin", args.start))
                        outcomes["garmin"] = FAILED
                    else:
                        outcomes["garmin"], n = _run_garmin(db, owner, chunks, hint, daily_from)
                        stored_total += n

            if args.source in ("whoop", "all"):
                print("\nWhoop")
                if not WhoopAuth.has_token(owner, db):
                    print("  Skipped: connect Whoop in Settings first.")
                    outcomes["whoop"] = SKIPPED
                elif whoop_auth_error(owner, db):
                    print("  Skipped: Whoop needs reconnect; reconnect in Settings first.")
                    outcomes["whoop"] = SKIPPED
                else:
                    chunks = day_chunks(args.start, today, args.chunk_days)
                    windows = whoop_windows(chunks, _now())
                    outcomes["whoop"], n = _run_whoop(db, owner, chunks, windows, hint)
                    stored_total += n

            if stored_total > 0:
                count = refresh_anomalies(engine, owner, args.start, today)
                print(f"\nAnomaly refresh over {args.start} → {today}: {count} stored.")
        finally:
            db.close()
    finally:
        engine.dispose()

    if FAILED in outcomes.values():
        return 1
    if OK not in outcomes.values():
        print("\nNothing ran.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
