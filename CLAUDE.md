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
Phase 2 — Garmin Integration — **Tasks 2.1–2.4 COMPLETE**. Next: Phase 2 remaining tasks (normalization, combined views).

## What's Built (Phase 1)
- Database layer: SQLAlchemy models, WAL mode, migrations (src/database/)
- Whoop OAuth 2.0: WhoopAuth class, /api/auth/whoop routes (src/clients/whoop_auth.py)
- Whoop API client: WhoopClient with pagination + retry logic (src/clients/whoop_client.py)
- Ingestion pipeline: WhoopPipeline fetch → transform → upsert (src/ingestion/whoop_pipeline.py)
- FastAPI app entry point: src/api/main.py
- Streamlit dashboard: frontend/app.py (Recovery, Sleep, Activities pages)
- Docker: Dockerfile + docker-compose.yml (backend port 8000, frontend port 8501, data/ volume)

## What's Built (Phase 2, so far)
- Garmin auth: GarminAuth class with token persistence via garth (src/clients/garmin_auth.py)
  - Tokens stored at `data/garmin_tokens/` (GARMIN_TOKEN_DIR in .env)
  - Re-auth on 401, clear error messages for 429/403
- Garmin API client: GarminClient with rate limiting (1.5s default) + per-method error handling (src/clients/garmin_client.py)
  - Methods: get_activities, get_activity_detail, get_daily_summary, get_sleep, get_hrv
- Garmin DB schema: GarminActivity, GarminDailySummary, GarminSleep, GarminHRV models
- Migration 002: creates four Garmin tables idempotently (src/database/migrations/002_garmin_tables.py)
- Garmin pipeline: GarminPipeline with batch activity fetch + per-day loop (src/ingestion/garmin_pipeline.py)
- initial_sync.py: runs Whoop (async) then Garmin (sync) in sequence

## Key Decisions
- Whoop = source of truth for recovery, sleep quality, body vitals
- Garmin = source of truth for workout detail, running dynamics
- Deduplication by timestamp + duration only
- Store raw API responses in raw_json column for reprocessing
- Garmin sleep/HRV data will be missing most nights — the watch is not worn during sleep (Whoop is worn instead). `get_sleep` and `get_hrv` returning None is expected and normal, not an error.
- `get_activity_detail` is NOT called during ingestion — running dynamics (ground contact time, stride length, vertical oscillation, vertical ratio, VO2 max, training load) are already present in the activity list response. `avg_ground_contact_balance` is not available in either endpoint and is stored as NULL. Revisit if needed later.

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
- Activity split: strain activities = `strain IS NOT NULL`, recovery activities = `strain IS NULL`
- `respiratory_rate` is on `whoop_sleep`, not `whoop_recovery` — join via `r.sleep_id = s.id`
- `skin_temp_celsius` displayed as Fahrenheit: `°F = °C × 9/5 + 32`

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

## Notes
- **Repo will go public.** Never commit or push: `.env`, credentials, access/refresh tokens, or personal data (user_id, email, health metrics). Confirm nothing sensitive is staged before every commit.