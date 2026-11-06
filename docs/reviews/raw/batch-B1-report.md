# Batch B1 report

Commit 39e936f. Tests 941 passed (baseline 938, +3 new). ruff check clean.

Fixed: C1 (RuntimeError in lifespan on empty JWT_SECRET; conftest sets test default; test added), H1, H2 (fields read inside session; 2 real-session tests, verified they fail on old code), M4 (GarminClient._key_error sets auth.last_error), M8, M12, M13, M34 (_build_daily_row/_build_sleep_row), M38 (src/ingestion/sync_log.py start_sync_log/mark_sync_error), L2, L12, L14, L16 (3 files + garmin_pipeline.py which I touched), L25, L27 (garmin_upload only), L29, L30, L31 (moot, deleted with L2), L32, L36, L52, L54 (PrefetchCache dataclass), L55, L56, L65, L67, L68 (shared upsert_row used by Normalizer/CSV importer/both pipelines), L69 (_upsert_records).

Skipped / partial:
- L27 garmin_csv.py:300 part: file outside list.
- L29 garmin_pipeline "aborted" branch (expected GarminPersonalApiError) kept as logger.error; only unexpected-failure branch uses logger.exception.
- L30: callers confirmed to surface errors (warnings/row_errors in responses).
