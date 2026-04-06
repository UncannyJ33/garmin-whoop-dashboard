#!/usr/bin/env python3
"""Verify composite indexes are being used by key analytics queries.

Usage:
    DATABASE_URL=postgresql://... python scripts/explain_indexes.py

Runs EXPLAIN ANALYZE on the most frequent queries and prints whether
each uses an Index Scan (good) or Seq Scan (indexes not helping).
"""

import os
import sys

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL or "sqlite" in DATABASE_URL:
    print("ERROR: Set DATABASE_URL to a PostgreSQL connection string.")
    print("  Example: DATABASE_URL=postgresql://user:pass@host:5432/db python scripts/explain_indexes.py")
    sys.exit(1)

engine = create_engine(DATABASE_URL, connect_args={"sslmode": "require"})

# Queries that should benefit from composite indexes.
# Each tuple: (description, SQL with :params, params dict)
QUERIES = [
    (
        "unified_daily — user + date range",
        "SELECT * FROM unified_daily WHERE user_id = :uid AND date >= :s AND date <= :e",
        {"uid": "test-user", "s": "2026-01-01", "e": "2026-03-26"},
    ),
    (
        "unified_sleep — user + date range",
        "SELECT * FROM unified_sleep WHERE user_id = :uid AND date >= :s AND date <= :e",
        {"uid": "test-user", "s": "2026-01-01", "e": "2026-03-26"},
    ),
    (
        "unified_workouts — user + date range",
        "SELECT * FROM unified_workouts WHERE user_id = :uid AND date >= :s AND date <= :e",
        {"uid": "test-user", "s": "2026-01-01", "e": "2026-03-26"},
    ),
    (
        "whoop_cycles — user + start_time range",
        "SELECT * FROM whoop_cycles WHERE user_id = :uid AND start_time >= :s AND start_time <= :e",
        {"uid": "test-user", "s": "2026-01-01T00:00:00", "e": "2026-03-26T23:59:59"},
    ),
    (
        "whoop_sleep — user + end_time range (no SUBSTR)",
        "SELECT * FROM whoop_sleep WHERE user_id = :uid AND nap = false AND end_time >= :s AND end_time <= :e",
        {"uid": "test-user", "s": "2026-01-01T00:00:00", "e": "2026-03-26T23:59:59"},
    ),
    (
        "garmin_activities — user + start_time_gmt range",
        "SELECT * FROM garmin_activities WHERE user_id = :uid AND start_time_gmt >= :s AND start_time_gmt <= :e",
        {"uid": "test-user", "s": "2026-01-01T00:00:00", "e": "2026-03-26T23:59:59"},
    ),
]

print("=" * 70)
print("EXPLAIN ANALYZE — Composite Index Verification")
print("=" * 70)

with engine.connect() as conn:
    for desc, sql, params in QUERIES:
        print(f"\n--- {desc} ---")
        try:
            rows = conn.execute(text(f"EXPLAIN ANALYZE {sql}"), params).fetchall()
            plan = "\n".join(r[0] for r in rows)

            uses_index = "Index Scan" in plan or "Index Only Scan" in plan or "Bitmap Index Scan" in plan
            uses_seq = "Seq Scan" in plan

            if uses_index and not uses_seq:
                status = "INDEX SCAN"
            elif uses_seq and not uses_index:
                status = "SEQ SCAN (index not used)"
            else:
                status = "MIXED"

            print(f"  Result: {status}")
            # Print first 5 lines of plan for context
            for line in plan.split("\n")[:5]:
                print(f"    {line}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

print("\n" + "=" * 70)
print("Done. Index Scan = good. Seq Scan on small tables is OK (planner")
print("may prefer it when table fits in memory). Watch for Seq Scan on")
print("large tables (>10K rows) — that indicates a missing/unused index.")
print("=" * 70)
