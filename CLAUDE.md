# Fitness Dashboard — Claude Code Context

## Project
Personal training dashboard integrating Garmin + Whoop data into a single view.
Python + FastAPI + SQLite + Streamlit (migrating to React later).

## Reference Docs
Full project planning docs are in opus_plan_src_files/. Read these when you need:
- Architecture and data flow → Technical_Design_Doc.md
- Database schema (exact table definitions) → Technical_Design_Doc.md Section 3
- Task details and acceptance criteria → Phase_Task_Breakdowns.md
- Overall roadmap and priorities → Garmin_Whoop_Dashboard_Roadmap_v2.md

## Current Phase
Phase 2 — Garmin Integration — **COMPLETE** (Tasks 2.1–2.8). Next: Phase 3 — Dashboard views.

## What's Built (Phase 1)
- Database layer: SQLAlchemy models, WAL mode, migrations (src/database/)
- Whoop OAuth 2.0: WhoopAuth class, /api/auth/whoop routes (src/clients/whoop_auth.py)
- Whoop API client: WhoopClient with pagination + retry logic (src/clients/whoop_client.py)
- Ingestion pipeline: WhoopPipeline fetch → transform → upsert (src/ingestion/whoop_pipeline.py)
- FastAPI app entry point: src/api/main.py
- Streamlit dashboard: frontend/app.py (Recovery, Sleep, Activities, Data Sources pages)
- Docker: Dockerfile + docker-compose.yml (backend port 8000, frontend port 8501, data/ volume)

## What's Built (Phase 2 — COMPLETE)
- Garmin auth: GarminAuth class with token persistence via garth (src/clients/garmin_auth.py)
  - Tokens stored at `data/garmin_tokens/` (GARMIN_TOKEN_DIR in .env)
  - Re-auth on 401, clear error messages for 429/403
- Garmin API client: GarminClient with rate limiting (1.5s default) + per-method error handling (src/clients/garmin_client.py)
  - Methods: get_activities, get_activity_detail, get_daily_summary, get_sleep, get_hrv
- Garmin DB schema: GarminActivity, GarminDailySummary, GarminSleep, GarminHRV models
- Migration 002: creates four Garmin tables idempotently (src/database/migrations/002_garmin_tables.py)
- Garmin pipeline: GarminPipeline with batch activity fetch + per-day loop (src/ingestion/garmin_pipeline.py)
- initial_sync.py: runs Whoop (async) then Garmin (sync) in sequence
- Schema comparison tool: src/normalization/comparison_tool.py + scripts/schema_review.py (Task 2.6)
- Schema unification review: config/field_mappings.yaml fully populated with all source/primary/transformation decisions (Task 2.7)
- Normalization layer: migration 003, whoop_mapper.py, garmin_mapper.py, deduplication.py, normalizer.py; both pipelines call normalize_all() after sync (Task 2.8)
- Frontend migrated to unified tables: all views read from unified_daily/unified_sleep/unified_workouts; new Data Sources page (frontend/views/data_sources.py)

## Key Decisions
- Whoop = source of truth for recovery, sleep quality, body vitals
- Garmin = source of truth for workout detail, running dynamics
- Deduplication by timestamp + duration only
- Store raw API responses in raw_json column for reprocessing
- Garmin sleep/HRV data will be missing most nights — the watch is not worn during sleep (Whoop is worn instead). `get_sleep` and `get_hrv` returning None is expected and normal, not an error.
- `get_activity_detail` is NOT called during ingestion — running dynamics (ground contact time, stride length, vertical oscillation, vertical ratio, VO2 max, training load) are already present in the activity list response. `avg_ground_contact_balance` is not available in either endpoint and is stored as NULL. Revisit if needed later.

## Schema Unification — Alignment Decisions
These decisions were made during the schema review phase (comparison_tool.py) and govern how Whoop and Garmin data are joined for combined views. Will be refined once normalization layer is built.

### Daily alignment
- **Chosen**: Key Whoop recovery by `DATE(whoop_cycles.start_time)` — a cycle starts at wake-up (~6–8am), so the date matches Garmin's `garmin_daily_summary.date` directly.
- Considered: keying by `DATE(whoop_sleep.end_time)` (wake-up time via sleep join) — more semantically precise but adds an extra join and edge-case risk. Revisit if off-by-one errors appear in practice.

### Sleep alignment
- **Chosen**: Whoop is source of truth. Key Whoop sleep by `DATE(whoop_sleep.end_time)` (the morning you woke up). Look up Garmin sleep by that same date. Garmin sleep `date` column already uses the wake-up calendar date so they align directly.
- Considered: keying by `DATE(start_time)` (night you went to bed) — would be off-by-one vs Garmin.
- Note: Garmin sleep rows will be sparse (watch not worn), so most rows will be Whoop-only.

### Workout alignment
- **Chosen**: Match Whoop strain workouts (strain IS NOT NULL) to Garmin activities using: start-time difference ≤5 min AND duration difference ≤20% of the longer activity.
- Considered: ≤10 min / ≤10% threshold (stricter time, looser duration); or same-date + sport name keyword match only (no time math).
- Whoop includes walks, stretches, yoga etc — filtering to strain-only reduces noise and improves match rate with intentional Garmin-tracked workouts.

### Field equivalencies (confirmed, not yet normalized)
- Whoop `total_sws_ms` ≡ Garmin `deep_sleep_seconds` (both = slow wave / deep sleep)
- Whoop `sleep_performance` ≠ Garmin `sleep_score` — different algorithms, not directly comparable
- Whoop `resting_heart_rate` (Float) ≡ Garmin `resting_heart_rate` (Integer) — same metric, safe to compare
- Whoop `spo2_pct` ≡ Garmin `avg_spo2` — both are daily SpO2 averages

### Schema review tooling
- `src/normalization/comparison_tool.py` — `run_comparison(engine, start, end)` returns dict of DataFrames and prints tabulated output
- `scripts/schema_review.py` — CLI runner; `python scripts/schema_review.py --days 14`
- CSVs saved to `data/review/` (gitignored — contains personal health data)

## Conventions
- Python 3.11+
- Type hints on all functions
- Docstrings on public functions
- Tests in tests/ using pytest
- Secrets in .env, never hardcoded
- Always use the venv environment (`source .venv/bin/activate`)
- Linting: `ruff` (installed as dev dep). Run via `make lint`. Auto-fix with `make fmt`.
- `timezone.utc` → use `datetime.UTC` (Python 3.11+, enforced by ruff UP017)
- Frontend `sys.path` manipulation requires `# noqa: E402` on the imports that follow it

## Common Commands (see Makefile)
- `make run-api` — start FastAPI on port 8000 with hot-reload
- `make run-frontend` — start Streamlit on port 8501
- `make run-sync` — run a Whoop data sync (30-day default)
- `make test` — run pytest with verbose output
- `make lint` — ruff check (no auto-fix)
- `make fmt` — ruff format + fix in place

## Whoop API — Actual Field Names
The v2 API field names differ from our DB column names. Key mappings:
- `start` / `end` → `start_time` / `end_time` (cycles, sleep, workouts)
- `score.kilojoule` → `kilojoules`
- `score.average_heart_rate` → `avg_heart_rate`
- `score.hrv_rmssd_milli` → `hrv_rmssd`
- `score.spo2_percentage` → `spo2_pct`
- `score.sleep_performance_percentage` → `sleep_performance` (same pattern for consistency/efficiency)
- Sleep stages nested under `score.stage_summary` (e.g. `total_in_bed_time_milli`)
- Cycle `id` is an integer — must `str()` it for our TEXT primary key
- Recovery has no `id` field — synthetic key `str(cycle_id)` used (one recovery per cycle)
- `score` can be `null` on workouts and pending cycles — always guard with `or {}`

## Frontend — Streamlit Dashboard
- Run: `streamlit run frontend/app.py`
- Views live in `frontend/views/` — do NOT use `frontend/pages/`; Streamlit auto-discovers any `pages/` directory and adds them as nav items, breaking manual sidebar routing
- Shared DB connection: `frontend/db.py` via `@st.cache_resource`
- All charts use Altair directly (not `st.line_chart` / `st.bar_chart`)
- No zoom on any chart — user preference; do not add `selection_interval` to charts
- Altair 6.0.0 installed — use `alt.SelectionParameter`, not `alt.Selection` (renamed in v6)
- All views read from unified tables (unified_daily, unified_sleep, unified_workouts) — not raw whoop_* tables
- Activity split: strain activities from unified_workouts, recovery activities from whoop_workouts WHERE strain IS NULL
- Running data table filters by `activity_type LIKE '%run%'` (case-insensitive)
- `whoop_skin_temp` (°C) displayed as Fahrenheit: `°F = °C × 9/5 + 32`
- data_sources.py has no date range arg — sync log is not date-filtered

## Garmin API — Actual Field Names
Key mappings from live API inspection (confirmed against real responses):
- `activityId` → `activity_id` (must `str()` — large int)
- `activityType.typeKey` → `activity_type`
- `startTimeLocal` / `startTimeGMT` → `start_time` / `start_time_gmt`
- `averageHR` / `maxHR` → `avg_heart_rate` / `max_heart_rate` (cast to int — API returns float)
- `averageRunningCadenceInStepsPerMinute` → `avg_running_cadence`
- `vO2MaxValue` → `vo2_max`
- `aerobicTrainingEffect` / `anaerobicTrainingEffect` → `training_effect_aerobic` / `training_effect_anaerobic`
- `activityTrainingLoad` → `training_load`
- `avgGroundContactTime` / `avgVerticalOscillation` / `avgVerticalRatio` → same pattern
- Daily summary: `totalSteps`, `totalDistanceMeters`, `activeKilocalories`, `bodyBatteryHighestValue`, `bodyBatteryLowestValue`, `averageSpo2`, `lowestSpo2`, `averageStressLevel`, `maxStressLevel`
- Sleep: nested under `dailySleepDTO`; timestamps are Unix ms → converted to ISO 8601 at ingest
- HRV: nested under `hrvSummary` + `baseline` sub-dict; `weeklyAvg`, `lastNight`, `lastNight5MinHigh`
- `get_body_battery()` returns a list — take `[0]` for the target date

## Data Notes (from live 30-day sync)
- 128 workouts in 30 days — Whoop counts walks, stretches, etc. as workouts, not just training
- Garmin 30-day sync: 56 activities, 31 daily summaries, 31 sleep rows, 0 HRV rows (watch not worn at night)
- Sync window stored in `sync_log.metadata_json` as `{"sync_start": ..., "sync_end": ...}`
- Incremental syncs pick up from `sync_end` of last successful sync_log entry
- GarminPipeline sync window uses `date` objects (not `datetime`) in metadata_json

## Environment
- GitHub repo: https://github.com/UncannyJ33/garmin-whoop-dashboard (private)
- `gh` CLI installed and authenticated as UncannyJ33
- `uv` at `/opt/homebrew/bin/uv` — may need `export PATH="/opt/homebrew/bin:$PATH"` in fresh shells

## Testing Patterns
- In-memory SQLite: always share one engine across fixtures (`sqlite:///:memory:` is per-engine isolated)
- Mock httpx: patch `httpx.AsyncClient` at module level, set `__aenter__`/`__aexit__` on the mock instance
- Mock asyncio.sleep: `patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock)`
- Migration files starting with digits (001_initial.py) can't be imported directly — loaded via `importlib.util` in migrations/__init__.py

## Future Considerations
- **Garmin sleep schema**: Current design assumes the Garmin watch is not worn during sleep (Whoop is worn instead), so `garmin_sleep` and `garmin_hrv` are nearly empty. If users sleep with Garmin on, both tables will have real data and the unified sleep schema needs to handle two populated sources simultaneously. May need two separate unified sleep schemas (Whoop-primary vs Garmin-primary) or a configurable `sleep_device` setting per user. Needs thought before the normalization layer is finalized.

## Notes
- **Repo will go public.** Never commit or push: `.env`, credentials, access/refresh tokens, or personal data (user_id, email, health metrics). Confirm nothing sensitive is staged before every commit.