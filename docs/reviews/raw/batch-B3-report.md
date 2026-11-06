# Batch B3 report
Commits: e27236e (analytics + test), 00e68fe (models/routes/db models).
Done: M5 M14 M15 M16 M27 M32 M33 M35 M36 M37 M40 L1 L11 L13 L18 L19 L20 L21 L22 L33 L34 L45 L46 L47 L48 L50 L64 L66 (partial: trends get_weekly_summary helpers only).
Skipped: L51 (cached context_json may be {} / legacy shape; TypedDict model would change validation), L63 (needs shared dependency in src/api/dependencies.py, outside list).
Extras: removed now-dead trends.AnomalyPoint dataclass; user_clause lives in training_load.py; tests/test_enriched_anomalies.py fixture updated to seed sleep on wake date (M5).
TS unions for Literals (api.ts) belong to the frontend batch.
Tests: 940 passed. make lint: 2 errors in src/ingestion/garmin_csv_parser.py (other batch).
