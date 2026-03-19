"""Migrate all data from SQLite to PostgreSQL (Supabase).

Reads source from SQLITE_URL env var or the default SQLite path.
Reads destination from DATABASE_URL env var (must be PostgreSQL).

Usage:
    # Use .env values
    python scripts/migrate_to_postgres.py

    # Override source and/or destination
    python scripts/migrate_to_postgres.py \
        --source sqlite:///data/fitness_dashboard.db \
        --dest "postgresql://postgres.[ref]:[pw]@aws-0-us-east-1.pooler.supabase.com:5432/postgres"

    # Skip the confirmation prompt when destination already has data
    python scripts/migrate_to_postgres.py --force
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import inspect, text  # noqa: E402

from src.database.connection import get_engine  # noqa: E402

# Migration order: parents before children (FK dependency order).
TABLE_ORDER = [
    "whoop_cycles",
    "whoop_recovery",
    "whoop_sleep",
    "whoop_workouts",
    "garmin_activities",
    "garmin_exercise_sets",
    "garmin_daily_summary",
    "garmin_sleep",
    "garmin_hrv",
    "unified_daily",
    "unified_sleep",
    "unified_workouts",
    "sync_log",
    "token_store",
]

# Columns that SQLite stores as 0/1 but PostgreSQL expects bool
BOOL_COLUMNS: dict[str, set[str]] = {
    "whoop_sleep": {"nap"},
    "unified_workouts": {"matched"},
}

BATCH_SIZE = 500
DEFAULT_USER_ID = "owner"


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer == "y"


def migrate(
    src_url: str, dst_url: str, force: bool = False, user_id: str = DEFAULT_USER_ID
) -> None:
    print(f"\nSource : {src_url}")
    dst_display = dst_url.split("@")[-1] if "@" in dst_url else dst_url
    print(f"Dest   : {dst_display}")
    print(f"user_id: {user_id!r}\n")

    if not dst_url.startswith("postgresql"):
        print("ERROR: --dest must be a PostgreSQL URL.")
        sys.exit(1)

    src_engine = get_engine(src_url)
    dst_engine = get_engine(dst_url)

    src_inspector = inspect(src_engine)
    dst_inspector = inspect(dst_engine)

    src_tables = set(src_inspector.get_table_names())
    dst_tables = set(dst_inspector.get_table_names())

    # Check whether destination already has data
    with dst_engine.connect() as dst_conn:
        dst_totals = {}
        for table in TABLE_ORDER:
            if table in dst_tables:
                dst_totals[table] = dst_conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table}"')
                ).scalar()

    has_existing = any(v > 0 for v in dst_totals.values())
    if has_existing and not force:
        print("Destination already contains data:")
        for t, n in dst_totals.items():
            if n:
                print(f"  {t}: {n} rows")
        if not _confirm("\nClear destination tables and re-import?"):
            print("Aborted.")
            sys.exit(0)

    results: list[dict] = []

    for table in TABLE_ORDER:
        if table not in src_tables:
            print(f"  {table}: not in source — skipping")
            results.append({"table": table, "src": 0, "dst": 0, "ok": True})
            continue

        bool_cols = BOOL_COLUMNS.get(table, set())
        src_cols = [c["name"] for c in src_inspector.get_columns(table)]
        has_user_id = "user_id" in src_cols

        with src_engine.connect() as src_conn:
            rows = src_conn.execute(text(f'SELECT * FROM "{table}"')).mappings().all()

        src_count = len(rows)
        print(f"  {table}: {src_count} rows ...", end=" ", flush=True)

        if src_count == 0:
            results.append({"table": table, "src": 0, "dst": 0, "ok": True})
            print("(empty)")
            continue

        with dst_engine.begin() as dst_conn:
            # Clear destination table if it had existing rows
            if dst_totals.get(table, 0) > 0:
                dst_conn.execute(text(f'DELETE FROM "{table}"'))

            # Build column list from source (always include user_id)
            col_names = list(src_cols)
            if not has_user_id and "user_id" not in col_names:
                col_names.append("user_id")

            placeholders = ", ".join(f":{c}" for c in col_names)
            col_list = ", ".join(f'"{c}"' for c in col_names)
            insert_sql = text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})')

            for batch_start in range(0, src_count, BATCH_SIZE):
                batch = rows[batch_start : batch_start + BATCH_SIZE]
                params = []
                for row in batch:
                    d = dict(row)
                    # Bool conversion: SQLite 0/1 → Python bool
                    for col in bool_cols:
                        if col in d and d[col] is not None:
                            d[col] = bool(d[col])
                    # Set app user_id if missing
                    if "user_id" not in d or d["user_id"] is None:
                        d["user_id"] = user_id
                    # Restrict to known columns
                    params.append({c: d.get(c) for c in col_names})
                dst_conn.execute(insert_sql, params)

        # Verify count
        with dst_engine.connect() as dst_conn:
            dst_count = dst_conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

        ok = dst_count == src_count
        status = "✓" if ok else "✗ MISMATCH"
        print(f"{status} ({dst_count} in dest)")
        results.append({"table": table, "src": src_count, "dst": dst_count, "ok": ok})

    # Summary
    print(f"\n{'=' * 55}")
    print(f"{'Table':<30} {'Source':>8} {'Dest':>8} {'Status':>8}")
    print(f"{'─' * 55}")
    all_ok = True
    for r in results:
        status = "✓" if r["ok"] else "✗"
        if not r["ok"]:
            all_ok = False
        print(f"  {r['table']:<28} {r['src']:>8} {r['dst']:>8} {status:>8}")
    print(f"{'=' * 55}")
    print("Migration complete — " + ("all counts match ✓" if all_ok else "MISMATCHES FOUND ✗"))

    # Spot-check: first + last row of each non-empty table
    if all_ok:
        print("\nSpot-check (first row of each non-empty table):")
        for r in results:
            if r["src"] == 0:
                continue
            table = r["table"]
            pk_col = _pk_col(src_inspector, table)
            with src_engine.connect() as sc, dst_engine.connect() as dc:
                src_first = sc.execute(text(f'SELECT * FROM "{table}" LIMIT 1')).mappings().first()
                dst_first = dc.execute(text(f'SELECT * FROM "{table}" LIMIT 1')).mappings().first()
            if src_first and dst_first:
                src_pk = src_first.get(pk_col)
                dst_pk = dst_first.get(pk_col)
                uid = dst_first.get("user_id")
                print(
                    f"  {table}: pk={dst_pk!r}  user_id={uid!r}  {'✓' if src_pk == dst_pk else '≠ (ordering differs — ok)'}"
                )
        print()


def _pk_col(inspector, table: str) -> str:
    pk = inspector.get_pk_constraint(table)
    cols = pk.get("constrained_columns", [])
    return cols[0] if cols else "id"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL")
    parser.add_argument(
        "--source",
        default=os.getenv("SQLITE_URL", "sqlite:///data/fitness_dashboard.db"),
        help="Source SQLite URL (default: sqlite:///data/fitness_dashboard.db)",
    )
    parser.add_argument(
        "--dest",
        default=os.getenv("DATABASE_URL", ""),
        help="Destination PostgreSQL URL (reads DATABASE_URL env if omitted)",
    )
    parser.add_argument(
        "--user-id",
        default=DEFAULT_USER_ID,
        help=f"Value to assign to user_id on all migrated rows (default: {DEFAULT_USER_ID!r})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation when destination already has data",
    )
    args = parser.parse_args()

    if not args.dest:
        print("ERROR: --dest is required (or set DATABASE_URL in .env).")
        sys.exit(1)

    migrate(args.source, args.dest, force=args.force, user_id=args.user_id)


if __name__ == "__main__":
    main()
