# Fitness Dashboard — Claude Code Context

## Project
Personal training dashboard integrating Garmin + Whoop data into a single view.
Python + FastAPI + SQLite + React 18 (TypeScript + Vite + TailwindCSS + Recharts).

## Reference Docs
Full project planning docs are in opus_plan_src_files/. Read these when you need:
- Architecture and data flow → Technical_Design_Doc.md
- Database schema (exact table definitions) → Technical_Design_Doc.md Section 3
- Task details and acceptance criteria → Phase_Task_Breakdowns.md
- Overall roadmap and priorities → Garmin_Whoop_Dashboard_Roadmap_v2.md

## Current Phase
**Phase 4 COMPLETE** — React frontend. All pages migrated: Readiness, Workouts (+ running/strength sections), Sleep, Trends, Settings, Recovery Activities.

## What's Built (Phase 1)
- Database layer: SQLAlchemy models, WAL mode, migrations (src/database/)
- Whoop OAuth 2.0: WhoopAuth class, /api/auth/whoop routes (src/clients/whoop_auth.py)
- Whoop API client: WhoopClient with pagination + retry logic (src/clients/whoop_client.py)
- Ingestion pipeline: WhoopPipeline fetch → transform → upsert (src/ingestion/whoop_pipeline.py)
- FastAPI app entry point: src/api/main.py
- Streamlit dashboard: frontend/app.py (Recovery, Sleep, Activities, Data Sources pages)
- Docker: multi-stage Dockerfile + docker-compose.yml (single container, port 8000, data/ volume)

## What's Built (Phase 2 — COMPLETE)
- Garmin auth: GarminAuth class with token persistence via garth (src/clients/garmin_auth.py)
  - Tokens stored at `data/garmin_tokens/` (GARMIN_TOKEN_DIR in .env)
  - Re-auth on 401, clear error messages for 429/403
- Garmin API client: GarminClient with rate limiting (1.5s default) + per-method error handling (src/clients/garmin_client.py)
  - Methods: get_activities, get_activity_detail, get_daily_summary, get_sleep, get_hrv, get_exercise_sets
- Garmin DB schema: GarminActivity, GarminDailySummary, GarminSleep, GarminHRV models
- Migration 002: creates four Garmin tables idempotently (src/database/migrations/002_garmin_tables.py)
- Garmin pipeline: GarminPipeline with batch activity fetch + per-day loop (src/ingestion/garmin_pipeline.py)
- initial_sync.py: runs Whoop (async) then Garmin (sync) in sequence
- Schema comparison tool: src/normalization/comparison_tool.py + scripts/schema_review.py (Task 2.6)
- Schema unification review: config/field_mappings.yaml fully populated with all source/primary/transformation decisions (Task 2.7)
- Normalization layer: migration 003, whoop_mapper.py, garmin_mapper.py, deduplication.py, normalizer.py; both pipelines call normalize_all() after sync (Task 2.8)
- Frontend migrated to unified tables: all views read from unified_daily/unified_sleep/unified_workouts; new Data Sources page (frontend/views/data_sources.py)

## What's Built (Phase 3 — COMPLETE)
- **Task 3.1** `src/analytics/readiness_score.py` — 5-component composite training readiness score
  - Components with weights: whoop_recovery (30%), hrv_trend (25%), body_battery (20%), sleep_quality (15%), training_load (10%)
  - HRV z-score normalization; training load ratio normalization; weights redistributed when source missing
  - `compute_readiness(target_date, engine) → ReadinessResult`, `get_readiness_history(start, end, engine) → list[dict]`
  - 53 tests
- **Task 3.2** `src/analytics/workout_analysis.py` — enriched workouts combining Whoop + Garmin
  - LEFT JOINs unified_workouts with garmin_activities for fields not in unified schema
  - Computed: strain_per_minute, efficiency_score (distance_m/strain), recovery_impact (next_day - 7d_avg)
  - `get_enriched_workout`, `get_enriched_workouts`, `get_workout_type_summary`; 52 tests
- **Task 3.3** `src/analytics/sleep_analysis.py` — sleep impact analysis
  - SleepInsight per night: links previous_day_strain/training_load + next_day_recovery/body_battery + sleep_debt
  - Pearson r: strain vs total/deep sleep and next-day recovery (requires ≥7 paired samples)
  - Consistency: bedtime/wake std, OLS slope trend direction; midnight-crossing bedtimes handled via +24h offset
  - `get_sleep_insights`, `get_strain_sleep_correlation`, `get_sleep_consistency`; 59 tests
- **Task 3.4** `src/analytics/trends.py` — rolling averages, anomaly detection, period rollups
  - 11 supported metrics from unified_daily + unified_sleep
  - Calendar-day windows (7d, 28d) with None-gap filling; z-score anomaly detection (default threshold=2.0)
  - ISO weekly and calendar monthly rollups: count, avg, min, max, std
  - `get_metric_series`, `detect_anomalies`, `get_weekly_rollup`, `get_monthly_rollup`; 61 tests
- **Tasks 3.5–3.8** Streamlit dashboard views wired to analytics engine:
  - `frontend/views/readiness.py` — Morning Readiness: hero score, 5-factor breakdown, 30d trend, key metrics, weekly comparison; Sync button (7-day) + Backfill expander (custom date range)
  - `frontend/views/sleep.py` — Sleep: last night hero, trends + anomaly chart, stage distribution, consistency, training↔sleep correlations
  - `frontend/views/workouts.py` — Workouts: charts-first layout (strain vs recovery scatter w/ activity filter, running dynamics trends, weekly volume, pace vs cadence, training load, VO2 max, strength training section); workout log expanders with HR zones + exercise sets; all charts use `width='stretch'`
  - `frontend/views/trends.py` — Trends: weekly summary card, metric explorer (7d/30d rolling), anomaly log, Pearson r heatmap
  - `frontend/views/recovery_activities.py` — Recovery Activities (NEW): session breakdown by week, duration over time, with/without-recovery-day next-day recovery comparison, duration vs next-day recovery scatter, next-day recovery + sleep performance by activity type, activity log
- **FastAPI REST API** (Phase 3 completion):
  - 16 endpoints across 5 route files: readiness, workouts, sleep, trends, sync
  - Pydantic response models in `src/api/models.py`; auto-docs at `/docs`
  - `src/api/routes/webhooks.py` — Whoop webhook receiver with BackgroundTask processing
- **Error handling + logging** (Phase 3 cleanup):
  - `src/logging_config.py` — centralized logging; call `configure_logging(settings.log_level)` at startup
  - Called from `src/api/main.py` (lifespan) and `frontend/app.py` (top-level)
  - All 4 analytics modules + all pipeline modules use `logging.getLogger(__name__)`
  - Every frontend view `render()` wrapped in try/except → shows `st.error()` instead of traceback
  - `frontend/db.py` exports `get_last_sync_info()` + `render_sync_status()` — sync-age + stale warning shown in sidebar
- **Total tests**: 498 passing

## What's Built (Post-Phase 3 Dashboard Enhancements)
- **Garmin Exercise Sets** — strength training set-level data integrated end-to-end:
  - `GarminExerciseSet` model + migration 004 (`src/database/migrations/004_exercise_sets.py`)
  - `GarminClient.get_exercise_sets()` — wraps `get_activity_exercise_sets` with rate limiting/retry
  - Pipeline: `_STRENGTH_TYPES` constant; `_sync_strength_sets` fetches sets for newly-synced strength activities; `_find_strength_activities_without_sets` backfills any existing strength activities missing sets
  - API field notes: weight in **grams** (÷1000 → kg), exercise field is `name` (not `exerciseName`), set order is `messageIndex`, `startTime` is ISO string (not Unix ms), exercises sorted by probability descending
  - `EnrichedWorkout` now includes `garmin_activity_id` field
- **Workouts page** — major expansion:
  - Charts-first layout: all charts above workout log
  - Strain vs next-day recovery scatter with activity type multiselect filter
  - Running section: weekly volume (distance + time side-by-side bars), running dynamics trend line (selectbox: cadence/vert ratio/vert osc/ground contact/stride length, cadence has 170–185 spm reference band), pace vs cadence scatter, training load bars, VO2 max trend
  - Strength section: max weight per session by exercise (lbs, tracked exercises only), total volume per session (lbs bar), strain + duration dual-axis chart
  - Exercise sets displayed inside workout expanders for strength activities (grouped by exercise, set table with reps/weight/volume)
- **Readiness page** — Sync button enhanced:
  - `_run_sync(start_date, end_date)` accepts custom range
  - "Backfill historical data" expander with From/To date pickers (default: 6 months back)
- **Recovery Activities page** (`frontend/views/recovery_activities.py`) — new dedicated page in sidebar
- **Deprecation fixes** — `use_container_width=True` → `width='stretch'` across all frontend views (st.button excluded)

## What's Built (Phase 4 — React Frontend, Tasks 4.1–4.6)
- **Stack**: React 18 + TypeScript + Vite + TailwindCSS + TanStack Query + Recharts
- **Working directory**: `frontend-react/` (Vite dev server on port 5175)
- **App shell** (`src/App.tsx`): sidebar nav, dark/light theme toggle, DateRangeProvider context, React Router
- **DateRangeContext** (`src/context/DateRangeContext.tsx`): shared `{days, setDays, start, end}` across all pages
- **API hooks** (`src/hooks/useApi.ts`): `useReadinessToday`, `useReadinessHistory`, `useWorkouts`, `useWorkoutSummary`, `useSleepInsights`, `useSleepCorrelations`, `useSleepConsistency`, `useMetricTrend`, `useWeeklySummary`, `useAnomalies`, `useSyncStatus`, `useTriggerSync`
- **API client** (`src/api/client.ts`): typed `api.get/post` wrapper over fetch with `/api` base URL proxied to FastAPI on port 8000
- **Shared components**:
  - `MetricCard` — value + unit + delta + status badge
  - `StatusBadge` — color-coded recommendation level (Push hard / Train normally / Go easy / Rest day)
  - `TrendChart` — recharts LineChart with 7d/30d rolling avg, anomaly dots, UTC-safe date formatter
  - `SleepStageBar` — stacked horizontal bar with hover legend (Deep/Light/REM/Awake)
  - `DataSourceBadge` — W / W+G / G pill badges
  - `WeekComparison` — week-over-week metric change cards
  - `ErrorState`, `LoadingState` (MetricCardSkeleton, ChartSkeleton, WorkoutRowSkeleton, PageSkeleton)
- **Pages**:
  - `src/pages/Readiness.tsx` — hero score + gradient, 5-factor cards (horizontal scroll on mobile), 30d TrendChart, 4 key metric cards, WeekComparison
  - `src/pages/Workouts.tsx` — 7/14/30/60d buttons, 4 summary MetricCards, activity breakdown table (clickable filter), paginated WorkoutRow list (expand/collapse), strain vs recovery ScatterChart with per-type colors + legend
  - `src/pages/Sleep.tsx` — hero total hours + SleepStageBar + 4 MetricCards + sleep debt banner, ComposedChart (bar + 7d avg line + deep toggle + anomaly dots), stacked AreaChart (sleep stages over time), consistency grid (bedtime/wake/variability/trend), 3 correlation cards with computed group averages + Pearson r
  - `src/pages/Trends.tsx` — weekly summary, metric explorer (9 metrics, 30–180d), anomaly log, Pearson correlations
- `src/pages/Settings.tsx` — data sources + sync status, data overview stats, preferences (theme, sleep target)
- `src/pages/RecoveryActivities.tsx` — summary metrics, weekly stacked bar, duration scatter, with/without comparison, duration vs recovery scatter, bar charts by activity type, activity log
- **WorkoutRow component** (`src/components/WorkoutRow.tsx`): expandable row showing Physiological Load, Performance, Running Dynamics (runs only), HR Zones, Recovery Impact
- **Deduplication bug fix** (`src/normalization/deduplication.py`): added end-time fallback matching for Whoop early-detection pattern (strength training where Whoop movement detection fires 10–15 min before Garmin button press). Constants: `MATCH_END_THRESHOLD_MIN=5`, `MATCH_END_DURATION_THRESHOLD_PCT=0.25`, `_END_MATCH_CONFIDENCE_PENALTY=0.8`. 5 new tests added.
- **UTC date display fix**: `new Date('YYYY-MM-DD')` was parsing as UTC midnight, shifting one day back in US timezones. Fixed in `WorkoutRow.tsx` and `TrendChart.tsx` by appending `'T12:00:00'` for date-only strings.
- **Vite proxy note**: `/api` in `vite.config.ts` is a prefix match — rename any dev-only routes that start with `/api` to avoid accidental forwarding (e.g. `/dev/api-test`).

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

## Local Dev Server Startup (3 terminals)
1. **Backend**: `source .venv/bin/activate && make run-api` (port 8000)
2. **React dev**: `cd frontend-react && npm run dev` (port 5173, hot-reload)
3. **ngrok**: `ngrok http 8000` — static domain, already set as `VITE_API_URL` in Vercel; Vercel frontend uses this for mobile PWA

## Docker / Production Build
- **Multi-stage Dockerfile**: Stage 1 (node:20-slim) builds React → Stage 2 (python:3.11-slim) runs FastAPI + serves `dist/`
- **Single container, single port**: `docker compose up --build` → everything on port 8000
- **FastAPI serves React**: `src/api/main.py` mounts `/assets` as StaticFiles and has a `spa_fallback` catch-all for client-side routing; only active when `frontend-react/dist/` exists
- **Vercel deploy**: `cd frontend-react && vercel --prod` (static hosting); needs `VITE_API_URL` pointing to ngrok/backend
- **Same-origin Docker deploy**: `VITE_API_URL` not needed — empty string default means `/api/...` goes to same host

## Common Commands (see Makefile)
- `make run-api` — start FastAPI on port 8000 with hot-reload
- `make run-frontend` — start Streamlit on port 8501 (legacy)
- `make run-sync` — run a Whoop data sync (30-day default)
- `make test` — run pytest with verbose output
- `make lint` — ruff check (no auto-fix)
- `make fmt` — ruff format + fix in place
- `cd frontend-react && npm run build` — production React build → `dist/`
- `cd frontend-react && npm run typecheck` — TypeScript check only

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

## Whoop Webhook Setup
- Endpoint: `POST /api/webhooks/whoop` — receives real-time Whoop events
- Health check: `GET /api/webhooks/whoop/test` — Whoop pings this to verify the URL
- Handled event types: `cycle.updated`, `recovery.updated`, `sleep.updated`, `workout.updated`
- Processing: returns 200 immediately; fetch+upsert+normalize runs in a `BackgroundTask`
- Logged to `sync_log` with `source="whoop_webhook"` for each event
- **Local dev tunneling** (Whoop must reach a public URL):
  ```bash
  # Install ngrok: brew install ngrok
  ngrok http 8000
  # Copy the https://*.ngrok-free.app URL
  ```
  Register that URL + `/api/webhooks/whoop` in Whoop Developer Dashboard → Webhooks.
  The test endpoint (`/api/webhooks/whoop/test`) must return 200 for Whoop to activate it.
- **Production**: set a stable public URL (e.g. Fly.io, Railway, or a VPS) in Whoop Dashboard.
  No secret/signature verification is currently implemented — add HMAC validation before exposing to the internet if needed.

## Notes
- **Repo will go public.** Never commit or push: `.env`, credentials, access/refresh tokens, or personal data (user_id, email, health metrics). Confirm nothing sensitive is staged before every commit.