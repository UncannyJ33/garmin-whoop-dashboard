# PulseEngine build log (Jan–Apr 2026)

> **Historical record.** Build log for the multi-user PulseEngine SaaS, Jan–Apr 2026, moved out of CLAUDE.md on 2026-11-06. Not current — see CLAUDE.md, README.md, plans/.

Sections below are near-verbatim from the old CLAUDE.md. Paths like `OPTIMIZATION.md` now live at `docs/history/OPTIMIZATION.md`. The `opus_plan_src_files/` directory referenced under Reference Docs does not exist in the repo.

## Original project description
Production fitness dashboard (PulseEngine) integrating Garmin + Whoop data. Multi-user, production-grade app — not a personal-only tool. Users register accounts, connect their own Whoop via OAuth, and see only their own data.
Python + FastAPI + PostgreSQL (Supabase) + React 18 (TypeScript + Vite + TailwindCSS + Recharts). Deployed on Railway at engine.pulsebuilt.net.

## Reference Docs
Full project planning docs are in opus_plan_src_files/. Read these when you need:
- Architecture and data flow → Technical_Design_Doc.md
- Database schema (exact table definitions) → Technical_Design_Doc.md Section 3
- Task details and acceptance criteria → Phase_Task_Breakdowns.md
- Overall roadmap and priorities → Garmin_Whoop_Dashboard_Roadmap_v2.md

## Current Phase
**Phase 6 COMPLETE (Mar 21, 2026)** — All tasks 6.4–6.8 complete including manual end-to-end testing.

### Phase 6 completions (Tasks 6.4–6.8):
- **Task 6.4** Data isolation: all queries scoped by user_id; cross-user access verified in tests
- **Task 6.5** Multi-user scheduler: per-user Garmin credentials (Fernet-encrypted in DB), CSV upload endpoint, per-user sync jobs
- **Task 6.6** Account settings: Whoop disconnect, data export (ZIP with 4 CSVs), change password, account deletion (cascade 16 tables)
- **Task 6.7** Landing page + waitlist: `Landing.tsx` at `/` for unauthenticated users, `POST /api/waitlist` (rate-limited, idempotent), `GET /api/waitlist/admin` (Bearer token auth), migration 011
- **Task 6.8** Manual end-to-end testing: all flows verified in production — onboarding, Garmin auto-sync, credential delete, data export, password change, account deletion, mobile onboarding
- **Tests**: 946 passing (42 new for Phase 6)
- **Deployed**: commit `ae37a17` → Railway → engine.pulsebuilt.net

### Post-Phase 6 production fixes (Mar 21, 2026):
- **Migration 009 timeout**: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` was timing out on every deploy for already-protected tables. Fixed by querying `pg_class.relrowsecurity` first and skipping tables where RLS is already enabled.
- **Garmin rate limit cascade**: scheduler was calling `authenticate_user_garmin` (full password login) on every 15-min sync run = 96 logins/day. Fixed: only authenticate when no session tokens exist. Also: `_login_with_tokens` now raises `GarminAuthError` on 429 instead of returning None (preventing cascade to password fallback). `GarminClient._call` now re-raises rate limit errors so the pipeline aborts on first failure instead of making N more failed OAuth calls.
- **garminconnect exception types**: `GarminConnectTooManyRequestsError` and friends are plain Exception subclasses, not GarthHTTPError. Added broad catch in `authenticate_user_garmin` and mapped them to `GarminAuthError`.
- **PostgreSQL BOOLEAN**: `auto_sync_enabled` column in `garmin_credentials` is BOOLEAN; SQL with `= 1`/`= 0` causes DatatypeMismatch on Supabase. Fixed all SQL to use `true`/`false` literals; fixed migration 010 column definition.
- **ConnectDevicesPanel opacity**: `bg-surface-card` Tailwind token was undefined. Added `card: 'var(--color-surface-raised)'` to surface tokens in tailwind.config.js.
- **Garmin credential endpoint**: ConnectDevicesPanel was posting to wrong endpoint (`/api/auth/garmin/connect` → `/api/garmin/credentials`). Fixed and added security disclosure panel matching Settings modal.

### Pre-Phase 6 completions:
- Privacy contact: `privacy@pulsebuilt.net` active, Privacy.tsx updated
- Sync UX: `/api/sync/status` serves from in-memory cache while running; frontend polls every 3s via `refetchInterval`
- Supabase RLS: migration 009 enables RLS on all 15 public tables (blocks PostgREST, FastAPI unaffected)
- Domain split: `pulsebuilt.net` → Pulse Built landing page (Cloudflare Pages); `engine.pulsebuilt.net` → PulseEngine (Railway)
- Landing page: `landing/index.html` — GeistPixel-Square font, dark theme, links to engine.pulsebuilt.net
- Railway env vars updated: `WHOOP_REDIRECT_URI` + `CORS_ORIGINS` → engine.pulsebuilt.net
- Cloudflare proxy: disabled for `engine` CNAME (DNS only); enabled for `pulsebuilt.net` (Cloudflare Pages)

**Phase 5.5 COMPLETE** — Dashboard restructure (4-page consumer UX) + post-launch polish.

### Phase 5.5 changes (frontend-react only):
- **Page structure**: 6 pages → 4 pages + Settings
  - Today (`/`) — quick glance: readiness arc gauge, ACWR headline, limiting factors, weekly digest
  - Training (`/training`) — deep training view: ACWR gauge + stats, running analytics, strength PRs, activity breakdown, workout log
  - Recovery (`/recovery`) — merged sleep + recovery activities: sleep hero, debt banner, variability, correlations, with/without comparison
  - Insights (`/insights`) — deep analytics: weekly digest, metric explorer (9 metrics), correlations with scatter, anomaly feed
  - Settings (`/settings`) — unchanged
- **Page section order** (Training): Training Load → Running Analytics → Strength → Activity Breakdown → Workout Log (charts-first)
- **Page section order** (Insights): Weekly Digest → Metric Explorer → Correlations → Anomaly Feed (log at bottom)
- **Routing**: clean URLs with legacy redirects (`/workouts`→`/training`, `/sleep`→`/recovery`, `/trends`→`/insights`, `/readiness`→`/`, `/recovery-activities`→`/recovery`)
- **Deleted old pages**: Readiness.tsx, Workouts.tsx, Sleep.tsx, Trends.tsx, RecoveryActivities.tsx
- **New hooks**: `useWeeklyDigest()` (`/api/insights/weekly-digest` — live on backend), `useEnrichedAnomalies()` (`/api/trends/anomalies/enriched` — live, returns [] when no enriched data), `useTrainingLoadRatio()`, `useLimitingFactors()`
- **New components**: `ACWRGauge.tsx`, `ReadinessArcGauge.tsx` (SVG semicircle, sweep-flag=1), `LimitingFactorCard.tsx`
- **Bug fixes**: Sleep/deep-sleep anomaly context converts minutes→hours before display (`value/60`); Body Battery low-direction copy corrected; `formatValue` in metric explorer also divides by 60 for sleep metrics
- **Build**: `npm run build` passes clean; TypeScript strict check passes; deployed to engine.pulsebuilt.net

### Performance optimization pass (Mar 26, 2026):
Full audit and implementation documented in `OPTIMIZATION.md`. Key changes:
- **Database**: Composite (user_id, date) indexes on all major tables (migration 012); replaced SUBSTR() with range comparisons for index-friendly timestamp filtering
- **Normalizer**: Batch-prefetch (210→7 queries per sync); anomaly_cache table (migration 013) stores pre-computed anomalies after each sync
- **API**: Batch anomaly detection (7 queries→1 UNION ALL); in-memory TTL cache for readiness/weekly-summary; HTTP Cache-Control middleware; server-side pagination on workouts endpoint
- **Frontend**: Route-based code splitting (React.lazy); Vite vendor chunk splitting (react/query/charts); virtual scrolling (react-virtuoso) for workout log; React.memo on WorkoutRow/DayButton/tooltips; deferred Insights correlation queries; standardized staleTime constants; ErrorBoundary for lazy routes; PWA skipWaiting; font preloading
- **Infra**: Streamlit + pytest moved to dev deps; Dockerfile layer optimization; connection pool bumped to 10+15; pytest-xdist added
- **Tests**: 904 passing

### Phase 5 milestones:
- Task 5.7 (custom domain): engine.pulsebuilt.net is live on Railway (migrated from pulsebuilt.net)
- Multi-tenancy: complete — all data tables have user_id; all queries scoped to current user; migration 007 adds whoop_cycles.user_id
- Task 5.11 (smoke test): all 6 checklist items verified in production (auth, Whoop OAuth, data display, background sync, mobile PWA, error handling)
- Task 5.10 (Whoop app submission): pending Whoop developer portal approval — no code changes needed

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
  - **Production**: tokens stored in `token_store` DB table (key: `garmin_{user_id}`) — restored to filesystem on each container start; survives Railway deploys
  - **Local dev**: tokens also cached in `data/garmin_tokens/` (GARMIN_TOKEN_DIR in .env) as fallback
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

## What's Built (Phase 5 — Production Infrastructure, Tasks 5.1–5.9+)
- **Database**: PostgreSQL on Supabase (connection pooler); `DATABASE_URL` env var selects SQLite (local) or PostgreSQL (prod)
  - Engine creation in `src/database/connection.py` — pool_size=5, max_overflow=10, pool_recycle=300 for PostgreSQL; WAL mode + check_same_thread for SQLite
  - Migration 005: idempotency check; Migration 006: users table; Migration 007: user_id on whoop_cycles
  - Boolean columns (`nap`, `matched`) — use Python `True`/`False` and `.is_(False)` ORM filter; never compare with integer 0/1 on PostgreSQL
  - Supabase connection: use direct connection **port 5432** (`db.[ref].supabase.co`) — bypasses PgBouncer, avoids SSL connection drop issues. Do NOT use port 6543 (Transaction mode pooler) — PgBouncer drops connections after sustained use. Do NOT use the pooler host port 5432 (Session mode).
- **Auth + Multi-tenancy**: JWT-based (`src/auth/` module), full user_id data scoping
  - `src/auth/security.py` — bcrypt password hashing, HS256 JWT (24h access / 30d refresh), secret from `JWT_SECRET` env var
  - `src/auth/dependencies.py` — `get_current_user` FastAPI dependency added to every protected route
  - Routes at `/api/auth/`: `POST /register`, `POST /login`, `POST /refresh`, `GET /me`
  - React: `AuthContext` manages token in memory (not localStorage); `Login.tsx` has login/register toggle; 401 → auto-redirect to `/login`
  - **All data tables have `user_id` column**; all analytics and API queries filter by `user_id = current_user.id`
  - Analytics functions: `compute_readiness`, `get_readiness_history`, `get_enriched_workout/s`, `get_workout_type_summary`, `get_sleep_insights`, `get_strain_sleep_correlation`, `get_sleep_consistency`, `get_metric_series/trend`, `get_weekly_summary`, `get_weekly/monthly_rollup` — all accept `user_id: str | None` param
  - Pipelines: `WhoopPipeline(db, user_id)` and `GarminPipeline(db, user_id)` — tag every record and SyncLog with user_id
  - Normalizer: `Normalizer(db, user_id)` — scopes source queries and output rows
  - Scheduler: `_get_owner_user_id()` queries first registered user for background syncs
  - Registration: open — any number of accounts can be created
- **Railway deployment**: `https://engine.pulsebuilt.net` (custom domain)
  - Single container: FastAPI serves React `dist/` at `/` + all `/api/*` routes
  - Auto-deploys on push to `main` branch
  - PORT env var set by Railway dynamically
  - Startup: single Python process creates one DB connection (pool_size=1) for migrations + sequence reset, then disposes before uvicorn starts
- **Background sync** (Task 5.9):
  - Garmin: APScheduler interval job every 15 min (`src/ingestion/scheduler.py`)
  - Whoop: scheduled every 30 min (supplements webhooks)
  - Both syncs: incremental from last `sync_log` entry; uses owner user_id from `_get_owner_user_id()`; manual trigger via `POST /api/sync/trigger/{source}`
- **Whoop OAuth in production**: redirect URI configurable via `WHOOP_REDIRECT_URI` env var; production URL registered in Whoop Developer Dashboard
- **CORS**: `CORS_ORIGINS` env var (comma-separated); defaults to `*` if unset
- **Key env vars for production** (set in Railway dashboard):
  - `DATABASE_URL` — Supabase PostgreSQL **Transaction mode** pooler string (port 6543)
  - `JWT_SECRET` — long random string for HS256 signing
  - `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI`
  - `GARMIN_EMAIL`, `GARMIN_PASSWORD`
  - `CORS_ORIGINS` — comma-separated allowed origins
  - `PORT` — set automatically by Railway


## Domain structure and production deployment (Railway, retiring)

- **pulsebuilt.net** — Pulse Built studio landing page (`landing/index.html`); deployed via Cloudflare Pages
- **engine.pulsebuilt.net** — PulseEngine app; deployed via Railway (see below)
- Both domains managed via Cloudflare DNS

## Production Deployment
- **Platform**: Railway — `https://engine.pulsebuilt.net` (custom domain; Railway origin: `https://garmin-whoop-dashboard-production.up.railway.app`)
- **Deploy**: push to `main` branch → Railway auto-builds Docker image and deploys
- **Container**: multi-stage Dockerfile (node:20-slim builds React → python:3.11-slim runs FastAPI + serves `dist/`)
- **Startup sequence**: migrations → sequence reset → uvicorn on `$PORT`
- **FastAPI serves React**: `src/api/main.py` mounts `/assets` as StaticFiles + `spa_fallback` catch-all; active when `frontend-react/dist/` exists
- **Same-origin**: `VITE_API_URL` not needed — empty string default means `/api/...` goes to same host
- **Railway env vars to update for subdomain migration**:
  - `WHOOP_REDIRECT_URI=https://engine.pulsebuilt.net/api/auth/whoop/callback`
  - `CORS_ORIGINS=https://engine.pulsebuilt.net`
- **Landing page deployment**: Cloudflare Pages → connect GitHub repo, set output directory to `landing/`, assign `pulsebuilt.net` custom domain

## Docker / Local Container Build
- `docker compose up --build` → everything on port 8000
- Requires all env vars in `.env` (copy from `.env.example`)

## Common Commands (see Makefile)
- `make run-api` — start FastAPI on port 8000 with hot-reload
- `make run-frontend` — start Streamlit on port 8501 (legacy)
- `make run-sync` — run a Whoop data sync (30-day default)
- `make test` — run pytest with verbose output
- `make lint` — ruff check (no auto-fix)
- `make fmt` — ruff format + fix in place
- `cd frontend-react && npm run build` — production React build → `dist/`
- `cd frontend-react && npm run typecheck` — TypeScript check only

## Data Notes (from live 30-day sync)
- 128 workouts in 30 days — Whoop counts walks, stretches, etc. as workouts, not just training
- Garmin 30-day sync: 56 activities, 31 daily summaries, 31 sleep rows, 0 HRV rows (watch not worn at night)
- Sync window stored in `sync_log.metadata_json` as `{"sync_start": ..., "sync_end": ...}`
- Incremental syncs pick up from `sync_end` of last successful sync_log entry
- GarminPipeline sync window uses `date` objects (not `datetime`) in metadata_json


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
