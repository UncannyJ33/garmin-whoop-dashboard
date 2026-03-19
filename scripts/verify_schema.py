"""Verify database schema: tables, columns, and indexes.

Connects using DATABASE_URL from .env (or the env override below).
Prints a report you can share for review — no credentials appear in output.

Usage:
    # Check local SQLite (default .env)
    python scripts/verify_schema.py

    # Check Supabase without editing .env
    DATABASE_URL="postgresql://..." python scripts/verify_schema.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import inspect, text  # noqa: E402

from src.database.connection import get_engine  # noqa: E402

EXPECTED_TABLES = {
    "whoop_cycles": {
        "required_cols": [
            "id",
            "user_id",
            "start_time",
            "end_time",
            "strain",
            "kilojoules",
            "avg_heart_rate",
            "max_heart_rate",
            "score_state",
            "fetched_at",
            "raw_json",
        ],
        "indexed_cols": ["start_time"],
    },
    "whoop_recovery": {
        "required_cols": [
            "id",
            "cycle_id",
            "recovery_score",
            "resting_heart_rate",
            "hrv_rmssd",
            "spo2_pct",
            "skin_temp_celsius",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "whoop_sleep": {
        "required_cols": [
            "id",
            "cycle_id",
            "start_time",
            "end_time",
            "nap",
            "score_state",
            "total_in_bed_ms",
            "total_light_ms",
            "total_sws_ms",
            "total_rem_ms",
            "sleep_performance",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["end_time", "user_id"],
    },
    "whoop_workouts": {
        "required_cols": [
            "id",
            "cycle_id",
            "start_time",
            "end_time",
            "sport_id",
            "sport_name",
            "strain",
            "avg_heart_rate",
            "max_heart_rate",
            "kilojoules",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["start_time", "user_id"],
    },
    "garmin_activities": {
        "required_cols": [
            "activity_id",
            "activity_type",
            "activity_name",
            "start_time",
            "start_time_gmt",
            "duration_seconds",
            "calories",
            "vo2_max",
            "training_load",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["start_time_gmt", "user_id"],
    },
    "garmin_exercise_sets": {
        "required_cols": [
            "id",
            "activity_id",
            "set_order",
            "set_type",
            "exercise_category",
            "exercise_name",
            "repetition_count",
            "weight_kg",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["activity_id", "user_id"],
    },
    "garmin_daily_summary": {
        "required_cols": [
            "date",
            "total_steps",
            "active_calories",
            "resting_heart_rate",
            "body_battery_high",
            "body_battery_low",
            "avg_spo2",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "garmin_sleep": {
        "required_cols": [
            "date",
            "total_sleep_seconds",
            "deep_sleep_seconds",
            "light_sleep_seconds",
            "rem_sleep_seconds",
            "sleep_score",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "garmin_hrv": {
        "required_cols": [
            "date",
            "weekly_avg_ms",
            "last_night_avg_ms",
            "status",
            "fetched_at",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "unified_daily": {
        "required_cols": [
            "date",
            "whoop_recovery_score",
            "whoop_strain",
            "whoop_hrv_rmssd",
            "garmin_body_battery_high",
            "garmin_total_steps",
            "last_updated",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "unified_sleep": {
        "required_cols": [
            "date",
            "whoop_performance",
            "total_sleep_minutes",
            "deep_sleep_minutes",
            "rem_sleep_minutes",
            "primary_source",
            "last_updated",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
    "unified_workouts": {
        "required_cols": [
            "id",
            "date",
            "start_time",
            "activity_type",
            "duration_minutes",
            "matched",
            "primary_source",
            "last_updated",
            "user_id",
        ],
        "indexed_cols": ["date", "start_time", "user_id"],
    },
    "sync_log": {
        "required_cols": ["id", "source", "sync_type", "started_at", "status", "user_id"],
        "indexed_cols": ["user_id"],
    },
    "token_store": {
        "required_cols": [
            "service",
            "access_token",
            "refresh_token",
            "expires_at",
            "updated_at",
            "user_id",
        ],
        "indexed_cols": ["user_id"],
    },
}


def main() -> None:
    engine = get_engine()
    dialect = engine.dialect.name
    # Hide credentials from URL
    url_display = str(engine.url).split("@")[-1] if "@" in str(engine.url) else str(engine.url)
    print(f"\n{'=' * 60}")
    print(f"Schema verification — {dialect} @ {url_display}")
    print(f"{'=' * 60}\n")

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    issues: list[str] = []
    ok_count = 0

    for table, spec in EXPECTED_TABLES.items():
        print(f"── {table}")

        # Table presence
        if table not in existing_tables:
            issues.append(f"MISSING TABLE: {table}")
            print("   ✗ TABLE MISSING")
            continue

        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        # Also collect columns that are indexed (via index=True on Column)
        indexed_col_names: set[str] = set()
        for idx in inspector.get_indexes(table):
            indexed_col_names.update(idx["column_names"])

        # Column check
        col_ok = True
        for col in spec["required_cols"]:
            if col not in existing_cols:
                issues.append(f"MISSING COLUMN: {table}.{col}")
                print(f"   ✗ missing column: {col}")
                col_ok = False
        if col_ok:
            print(f"   ✓ columns ({len(existing_cols)} total)")

        # Index check
        idx_ok = True
        for col in spec["indexed_cols"]:
            if col not in indexed_col_names:
                issues.append(f"MISSING INDEX on: {table}.{col}")
                print(f"   ✗ no index on: {col}")
                idx_ok = False
        if idx_ok:
            print(f"   ✓ indexes ({', '.join(spec['indexed_cols'])})")

        # nap / matched Boolean types
        if table == "whoop_sleep":
            nap_col = next((c for c in inspector.get_columns(table) if c["name"] == "nap"), None)
            if nap_col:
                t = str(nap_col["type"]).upper()
                if "BOOL" in t or "BOOLEAN" in t:
                    print("   ✓ nap column is BOOLEAN")
                else:
                    print(f"   ~ nap column type: {nap_col['type']} (expected BOOLEAN)")

        if table == "unified_workouts":
            matched_col = next(
                (c for c in inspector.get_columns(table) if c["name"] == "matched"), None
            )
            if matched_col:
                t = str(matched_col["type"]).upper()
                if "BOOL" in t or "BOOLEAN" in t:
                    print("   ✓ matched column is BOOLEAN")
                else:
                    print(f"   ~ matched column type: {matched_col['type']} (expected BOOLEAN)")

        if col_ok and idx_ok:
            ok_count += 1

    # Row counts
    print(f"\n{'─' * 40}")
    print("Row counts (should be 0 on a fresh DB):")
    with engine.connect() as conn:
        for table in EXPECTED_TABLES:
            if table in existing_tables:
                row = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
                print(f"   {table}: {row}")

    # Summary
    print(f"\n{'=' * 60}")
    total = len(EXPECTED_TABLES)
    print(f"Result: {ok_count}/{total} tables fully verified")
    if issues:
        print(f"\nIssues found ({len(issues)}):")
        for issue in issues:
            print(f"  ✗ {issue}")
    else:
        print("No issues found ✓")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
