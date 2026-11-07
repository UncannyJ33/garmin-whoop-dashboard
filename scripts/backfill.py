"""Backfill history from scratch, in chunks, oldest first.

Usage (from project root, venv active):
    python scripts/backfill.py --source {garmin,whoop,all} --start YYYY-MM-DD
        [--chunk-days N] [--force]

The range always ends today. Both pipelines resume from the latest successful
SyncLog, so re-running after a failure continues where it stopped.

Exit codes: 0 ok; 1 a source failed / no owner / several users / nothing ran;
2 usage error; 3 API server running and --force not given; 130 interrupted.
"""

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from src.analytics.anomaly_store import refresh_anomalies
from src.clients.whoop_auth import WhoopAuth, WhoopReauthRequired, whoop_auth_error
from src.database.connection import get_engine, get_session_factory
from src.database.migrations import run as run_migrations
from src.database.owner import get_owner_user_id
from src.ingestion.garmin_pipeline import GarminPipeline
from src.ingestion.whoop_pipeline import WhoopPipeline

logger = logging.getLogger(__name__)

GARMIN_MAX_CHUNK_DAYS = 31
DEFAULT_CHUNK_DAYS = 30

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


def garmin_chunks(start: date, today: date, chunk_days: int) -> list[tuple[date, date]]:
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
    """Return True if an API server answers on ``port``; a timeout counts as running."""
    try:
        httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
    except httpx.ConnectError:
        return False
    except httpx.TimeoutException:
        return True
    return True


def _resume_hint(source: str, chunk_start: date) -> str:
    return (
        f"  Resume with: make backfill SOURCE={source} START={chunk_start}\n"
        "  Run it before starting the server."
    )


def _print_chunk(source: str, s: date, e: date, log) -> None:
    print(
        f"  {source} {s} → {e}: {log.status} "
        f"(fetched {log.records_fetched}, stored {log.records_stored})"
    )


def _run_garmin(db: Session, owner: str, chunks: list[tuple[date, date]]) -> tuple[str, int]:
    """Run Garmin chunks oldest first; return ``(outcome, records_stored)``."""
    stored = 0
    for s, e in chunks:
        try:
            log = GarminPipeline(db, user_id=owner).run(start=s, end=e)
        except KeyboardInterrupt:
            raise _Interrupted("garmin", s) from None
        except Exception as exc:
            logger.exception("Garmin chunk %s → %s failed", s, e)
            print(f"  garmin {s} → {e}: FAILED {type(exc).__name__}: {exc}")
            print(_resume_hint("garmin", s))
            return FAILED, stored
        if log is None:
            print(f"  garmin {s} → {e}: skipped, another Garmin sync is running")
            print(_resume_hint("garmin", s))
            return FAILED, stored
        _print_chunk("garmin", s, e, log)
        if log.status == "error":
            print(f"    error: {log.error_message}")
            print(_resume_hint("garmin", s))
            return FAILED, stored
        stored += log.records_stored or 0
    return OK, stored


def _run_whoop(
    db: Session,
    owner: str,
    chunks: list[tuple[date, date]],
    windows: list[tuple[datetime, datetime]],
) -> tuple[str, int]:
    """Run Whoop windows oldest first; return ``(outcome, records_stored)``."""
    stored = 0
    for (s, e), (ws, we) in zip(chunks, windows, strict=True):
        try:
            log = asyncio.run(WhoopPipeline(db, user_id=owner).run(start=ws, end=we))
        except KeyboardInterrupt:
            raise _Interrupted("whoop", s) from None
        except WhoopReauthRequired:
            logger.exception("Whoop chunk %s → %s: token rejected", s, e)
            print("  Whoop rejected the token; reconnect in Settings, then resume.")
            print(_resume_hint("whoop", s))
            return FAILED, stored
        except Exception as exc:
            logger.exception("Whoop chunk %s → %s failed", s, e)
            print(f"  whoop {s} → {e}: FAILED {type(exc).__name__}: {exc}")
            print(_resume_hint("whoop", s))
            return FAILED, stored
        if log is None:
            print(f"  whoop {s} → {e}: skipped, another Whoop sync is running")
            print(_resume_hint("whoop", s))
            return FAILED, stored
        _print_chunk("whoop", s, e, log)
        stored += log.records_stored or 0
    return OK, stored


def _parse_args(argv: list[str] | None, today: date) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chunked, oldest-first history backfill.")
    parser.add_argument("--source", choices=["garmin", "whoop", "all"], default="all")
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("--chunk-days", type=int, default=DEFAULT_CHUNK_DAYS)
    parser.add_argument("--force", action="store_true", help="run even if the API is up")
    args = parser.parse_args(argv)
    if args.start > today:
        parser.error("--start must not be in the future")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    """Run the backfill; return the process exit code."""
    today = _today()
    args = _parse_args(argv, today)

    port = settings.app_port
    if api_running(port) and not args.force:
        print(
            f"The API server is running on port {port}; its scheduler would race the "
            "backfill. Stop it (Ctrl-C / `make down`) or pass --force."
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
            try:
                if args.source in ("garmin", "all"):
                    print("\nGarmin")
                    if not settings.garmin_personal_api_key:
                        print("  Skipped: GARMIN_PERSONAL_API_KEY is not set.")
                        outcomes["garmin"] = SKIPPED
                    else:
                        chunk_days = min(args.chunk_days, GARMIN_MAX_CHUNK_DAYS)
                        outcomes["garmin"], n = _run_garmin(
                            db, owner, garmin_chunks(args.start, today, chunk_days)
                        )
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
                        chunks = garmin_chunks(args.start, today, args.chunk_days)
                        windows = whoop_windows(chunks, _now())
                        outcomes["whoop"], n = _run_whoop(db, owner, chunks, windows)
                        stored_total += n
            except _Interrupted as intr:
                print(f"\nInterrupted during {intr.source}.")
                print(_resume_hint(intr.source, intr.chunk_start))
                return 130

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
