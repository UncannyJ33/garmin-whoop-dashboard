# Fitness Dashboard — Claude Code Context

## Project
Personal Garmin + Whoop fitness dashboard. Single user (SJ), self-hosted. Formerly PulseEngine, a multi-user SaaS (Jan–Apr 2026); that history is in `docs/history/build-log.md`.
- Backend: Python 3.11+ / FastAPI / SQLAlchemy. SQLite locally (default), Postgres supported.
- Frontend: React 18 + TypeScript + Vite + TailwindCSS + Recharts + TanStack Query (`frontend-react/`).

## Status: relaunch in progress (started 2026-11-06)
**Phase 2 done (2026-11-06, branch `feat/garmin-personal-api`): Garmin now comes from the official Personal API.** Phases 3–4 (SaaS cut) are still pending. Goal: a basic private dashboard.
Code that still exists but is **slated for removal. Don't extend it; don't add multi-user features**:
- open registration, waitlist, `Landing`/`Privacy`/`Onboarding`/`Showcase`/`ApiTest`/`Demo` pages, `pulse-demo/`, `/demo` mount
- Whoop allowlist + feature flags, account deletion
- Whoop webhook receiver (`src/api/routes/webhooks.py`)

Roadmap: `plans/2026-11-06-personal-relaunch-roadmap.md` (phases 0–7, decisions D1–D7, questions Q1–Q3). Phase 2 plan (done): `plans/2026-11-06-garmin-personal-api-client.md`.
Decisions agents must respect:
- **D1** Keep JWT login + `user_id` plumbing with exactly one owner user (`scripts/create_owner.py`, planned). Don't rip out `user_id`.
- **D2** Own small `httpx` client for the Garmin Personal API. Don't use Garmin's official package (reference only).
- **D3** Polling only. No webhooks.
- **D4** Strength = `summarizedExerciseSets` (per-exercise, table `garmin_exercise_summaries`), not set-level, for now.
- **D5** Keep SQLite + Postgres support, default SQLite. **D6** Leave `landing/` alone (pulsebuilt.net studio page, Cloudflare Pages). **D7** No frontend major upgrades yet.
- **Q1 answered:** it runs locally (Docker Compose + SQLite); Railway is dead. **Q2 answered:** Supabase was deleted and the old data is gone, so history gets pulled from scratch. Q3 (`landing/` placement) is still open.

## Docs map
- `README.md` — setup/overview
- `docs/research/2026-11-garmin-personal-api.md` — Personal API research (auth, endpoints, shape mapping, Whoop changes)
- `docs/reference/garmin-personal-api-openapi.json` — Garmin's official spec; **check field names here**
- `plans/` — roadmap + per-phase plans
- `docs/history/` — `build-log.md` (old CLAUDE.md phase content), `OPTIMIZATION.md`, `FRONTEND_DESIGN.md`

## Architecture & data flow
Garmin/Whoop API → pipelines → raw tables (with `raw_json`) → normalizer + dedup → unified tables → analytics → API → React.
- Ingestion (`src/ingestion/`): `whoop_pipeline.py`, `garmin_pipeline.py` (both take `(db, user_id)`, tag rows + `SyncLog`, call `normalize_all()` after sync), `scheduler.py` (APScheduler: exactly two jobs, `garmin_incremental_sync` every `GARMIN_POLL_INTERVAL_MINUTES`=30 and `whoop_incremental_sync` every 30, owner only; skips with an error log if >1 user), `csv_import.py`, `garmin_csv_parser.py`. Incremental sync resumes from last successful `sync_log` `sync_end`; window in `sync_log.metadata_json` (`sync_start`/`sync_end`; Garmin uses `date`, not `datetime`).
  - **Garmin failure policy (invariant):** any Garmin failure (key, 429, 5xx/transport, unexpected status, invalid JSON, non-list activities page) ends the run with `sync_log.status="error"` and the window does **not** advance; the next run re-pulls. Incremental runs re-fetch a 2-day overlap (`INCREMENTAL_OVERLAP_DAYS`). Runs are serialized by a non-blocking `_RUN_LOCK` (overlap = skipped). All-null/metric-null responses mean "no data": no row written.
- Clients (`src/clients/`): `whoop_auth.py`, `whoop_client.py` (pagination + retry), `garmin_personal_auth.py` (key → 24 h JWT cached in memory via one process-wide `get_default_auth()`; errors `GarminKeyError`/`GarminRateLimitError`/`GarminTransientError`; `last_error` = latest rejection), `garmin_client.py` (httpx against `https://personal.connectapi.garmin.com`, 1 s between calls; `get_activities` (paged, 100/page), `get_daily_summary`, `get_sleep`, `get_hrv`, `get_user_settings`).
- Owner (`src/database/owner.py`): `get_owner_user_id(engine)` → None for 0 users, the id for 1, `RuntimeError` for >1. `POST /api/sync/trigger/garmin` returns 403 unless a key is set and the caller is the owner. `GET /api/auth/garmin/status` → `{connected, configured, error}` (10-min probe cache); Settings/Connect-devices cards show Connected / Key not set / Key rejected / Can't reach Garmin.
- Normalization (`src/normalization/`): `whoop_mapper.py`, `garmin_mapper.py`, `deduplication.py`, `normalizer.py`; field decisions in `config/field_mappings.yaml`; `comparison_tool.py` + `scripts/schema_review.py` for schema review (CSVs to gitignored `data/review/`). Unified tables: `unified_daily`, `unified_sleep`, `unified_workouts`.
- Analytics (`src/analytics/`, all take `user_id`):
  - `readiness_score.py` — 5 components: whoop_recovery 30%, hrv_trend 25%, body_battery 20%, sleep_quality 15%, training_load 10%; HRV z-score; weights redistribute when a source is missing
  - `workout_analysis.py` (Whoop+Garmin enrichment: strain/min, efficiency, recovery impact), `sleep_analysis.py` (strain↔sleep Pearson r, consistency), `trends.py` (rolling avgs, z-score anomalies, weekly/monthly rollups), `training_load.py` (ACWR), `limiting_factors.py`, `weekly_digest.py`, `anomaly_store.py` (anomaly_cache, filled after each sync), `cache.py` (in-memory TTL)
- Auth (`src/auth/`): JWT (HS256, `JWT_SECRET`), bcrypt; `get_current_user` on protected routes.
- API (`src/api/routes/`): readiness, workouts, sleep, recovery, training, trends, insights, sync, auth, account, garmin_upload (`POST /api/garmin/upload`, export import), garmin_csv. Models in `src/api/models.py`; docs at `/docs`.
- DB: `src/database/` (models, `connection.py`, `migrations/`; run at startup).
- React (`frontend-react/src/`): pages Today `/`, Training, Recovery, Insights, Settings (+ Login, GarminHelp); legacy redirects `/readiness`→`/`, `/workouts`→`/training`, `/sleep`→`/recovery`, `/trends`→`/insights`, `/recovery-activities`→`/recovery`. Hooks in `src/hooks/useApi.ts`, client `src/api/client.ts`, auth token held in memory (`AuthContext`), `DateRangeContext`, routes lazy-loaded.

## Key decisions & alignment rules
- **Source of truth**: Whoop = recovery, sleep quality, body vitals. Garmin = workout detail, running dynamics.
- Store raw API responses in `raw_json` for reprocessing.
- **Workout dedup** by timestamp + duration only: Whoop strain workouts (strain IS NOT NULL) matched to Garmin if start diff ≤5 min (`MATCH_START_THRESHOLD_MIN`) and duration diff ≤20% (`MATCH_DURATION_THRESHOLD_PCT`). End-time fallback for Whoop early detection (strength): `MATCH_END_THRESHOLD_MIN=5`, `MATCH_END_DURATION_THRESHOLD_PCT=0.25`, `_END_MATCH_CONFIDENCE_PENALTY=0.8` (`deduplication.py`). Whoop non-strain activities (walks, stretches) stay out of the match.
- **Daily alignment**: key Whoop recovery by `DATE(whoop_cycles.start_time)` (cycle starts at wake) = Garmin `garmin_daily_summary.date`. Alternative (`DATE(whoop_sleep.end_time)` via join) rejected as extra join/edge cases; revisit on off-by-one errors.
- **Sleep alignment**: Whoop is truth, keyed by `DATE(whoop_sleep.end_time)` (morning you woke). Garmin sleep `date` is already the wake date. Keying by bedtime date would be off-by-one.
- Garmin sleep/HRV rows are mostly missing (watch not worn at night; Whoop is). On no-watch nights sleep returns an all-null DTO and HRV returns 204, so `garmin_sleep`/`garmin_hrv` normally get no rows. That is normal.
- No per-activity detail call: running dynamics, training load/effect and HR zones are in the activity list. `avg_ground_contact_balance` is unavailable and stored NULL.
- **Known bug:** the normalizer leaves a stale `g_<garmin_activity_id>` `unified_workouts` row when a later Whoop match creates `w_<id>` for the same activity (duplicate workouts, double-counted strength volume). Roadmap Phase 3.
- **Field equivalencies**: Whoop `total_sws_ms` ≡ Garmin `deep_sleep_seconds`; Whoop `sleep_performance` ≠ Garmin `sleep_score` (not comparable); resting HR and SpO2 (`spo2_pct` ≡ `avg_spo2`) comparable.
- Display: `whoop_skin_temp` °C shown as °F. Sleep metrics in minutes are converted to hours for display (`/60`). Whoop counts walks etc. as workouts (128 in a 30-day sample).

## Whoop API — Actual Field Names (v2)
- `start`/`end` → `start_time`/`end_time` (cycles, sleep, workouts)
- `score.kilojoule` → `kilojoules`; `score.average_heart_rate` → `avg_heart_rate`; `score.hrv_rmssd_milli` → `hrv_rmssd`; `score.spo2_percentage` → `spo2_pct`
- `score.sleep_performance_percentage` → `sleep_performance` (same for consistency/efficiency)
- Sleep stages under `score.stage_summary` (e.g. `total_in_bed_time_milli`)
- Cycle `id` is an integer — `str()` it for our TEXT primary key
- Recovery has no `id` — synthetic key `str(cycle_id)` (one recovery per cycle)
- `score` can be `null` on workouts and pending cycles — always guard with `or {}`

Whoop notes (Nov 2026; research §7):
- v2 only; v1 webhooks are gone. Client already targets `/developer/v2`.
- Refresh tokens rotate; concurrent refresh invalidates them. `_store_tokens` does persist the rotated token (its comment is misleading), but nothing serializes refreshes, and the scheduler deletes the token row on a 401, so a race forces re-auth (roadmap Phase 3.6).
- New apps are Sandbox tier = 10 members (enough). Rate limit 100 req/min, 10k/day.

## Garmin data shapes
**Personal API (current; verified live 2026-11-06; spec in `docs/reference/`, research §9).** Fixtures: `tests/fixtures/garmin_personal/` (sanitized).
- Activity list is a bare array. `activityId` → `activity_id` (`str()`); `activityType.typeKey` → `activity_type`; `startTimeLocal`/`startTimeGMT` → `start_time`/`start_time_gmt`; `averageHR`/`maxHR` → ints; `averageRunningCadenceInStepsPerMinute` → `avg_running_cadence`; `aerobicTrainingEffect`/`anaerobicTrainingEffect`; `activityTrainingLoad` → `training_load`; `avgGroundContactTime`/`avgVerticalOscillation`/`avgVerticalRatio` (runs). Training load, training effect and HR zones are present.
- **`vO2MaxValue` is absent** from the API: `vo2_max` gets no new points.
- Daily summary (`/usersummary-service/usersummary/daily`): `totalSteps`, `totalDistanceMeters`, `activeKilocalories`, `bodyBatteryHighestValue`/`LowestValue`, `averageSpo2`/`lowestSpo2`, `averageStressLevel`/`maxStressLevel`.
- Sleep: flat `DailySleepDTO` (no wrapper); no-watch nights give an all-null DTO. HRV: `hrvSummary` with `lastNightAvg` (not `lastNight`); 204 = no data.
- Strength: no per-set endpoint. `summarizedExerciseSets` → `garmin_exercise_summaries` (migration 014), one row per exercise: `maxWeight`/`volume` grams ÷1000 → kg, `duration` ms ÷1000 → s, `exercise_name` = `subCategory` else `category`. Strength routes prefer set-level rows (legacy `garmin_exercise_sets`) per activity, else summaries; `GET /api/workouts/{id}/exercise-summary`. `TRACKED_EXERCISES` in `Training.tsx` has category-level fallback keys.
- History depth: daily summaries ~180 days back, activities ~690 days. Older daily data needs a Garmin account export via `scripts/import_data.py`.
- Not in the API: training readiness/status, acute load, VO2max endpoints.

**Legacy garminconnect-era rows** (existing `raw_json`): sleep nested under `dailySleepDTO` with Unix-ms timestamps, HRV `lastNight`; set-level `garmin_exercise_sets` (weight in grams, exercise field `name`, order `messageIndex`). The transforms still accept both shapes.

## Conventions
- Python 3.11+; type hints on all functions; docstrings on public functions
- Tests in `tests/` with pytest
- Secrets in `.env`, never hardcoded
- Always use the venv: `source .venv/bin/activate`
- Lint with `ruff`: `make lint`, auto-fix `make fmt`
- `timezone.utc` → `datetime.UTC` (ruff UP017)
- UI preference: no zoom on any chart (don't add `selection_interval` / brush; React charts currently have none)
- **Never commit** `.env`, credentials, tokens, DB files, Garmin/Whoop exports, or personal health data. Raw API samples go in gitignored `data/`; test fixtures must be sanitized.

## Local dev
A fresh checkout needs `uv sync --frozen` and `cd frontend-react && npm ci`. As of 2026-11-06 the local `.venv` (Python 3.12) and `node_modules` exist, and `.env` exists (gitignored). Garmin sync needs `GARMIN_PERSONAL_API_KEY` in `.env` (optional `GARMIN_PERSONAL_API_BASE_URL`). `uv` is **not** installed globally (`brew install uv`); the old `/opt/homebrew/bin/uv` note is stale.
- Backend (port 8000): `make run-api`
- Frontend: `cd frontend-react && npm run dev` — Vite port **5173** (per `vite.config.ts`; old docs also said 5175, wrong), proxies `/api` → `VITE_API_URL` or `http://localhost:8000`
- `make test` (pytest), `make lint`, `make fmt`, `make run-sync` (`scripts/initial_sync.py`; runs with `user_id=None` if no owner exists, Phase 3 fix)
- `cd frontend-react && npm run build` (tsc + vite build → `dist/`), `npm run typecheck`
- Container: `docker compose up --build` → port 8000; needs `.env` (copy `.env.example`)
- Local `.env`: `DATABASE_URL=sqlite:///data/fitness_dashboard.db`; `JWT_SECRET` must be set even locally.
- Gotcha: Vite `/api` is a prefix match — dev-only routes must not start with `/api` (e.g. use `/dev/api-test`).

## Testing patterns
- In-memory SQLite: share one engine across fixtures (`sqlite:///:memory:` is per-engine isolated)
- Mock httpx: patch `httpx.AsyncClient` at module level; set `__aenter__`/`__aexit__` on the mock instance
- Mock sleep: `patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock)`
- Digit-prefixed migrations (`001_initial.py`) can't be imported directly; loaded via `importlib.util` in `migrations/__init__.py`
- **938 passed** with serial `.venv/bin/pytest -q`. xdist (`-n auto`) is still **broken**; run serially. `make lint` is clean.
- `tests/conftest.py` has an autouse fixture that blanks `GARMIN_PERSONAL_API_KEY` and points the base URL at `https://garmin.invalid`, so tests never reach Garmin with the real key.
- Garmin fixtures: `tests/fixtures/garmin_personal/` (sanitized live shapes; `sleep.json` and `hrv.json` are synthetic, `"_synthetic": true`). Never commit real values. `scripts/garmin_personal_probe.py` is the spike probe; raw samples go to gitignored `data/garmin_personal_samples/`.

## Database gotchas
- Postgres BOOLEAN columns (`nap`, `matched`, `auto_sync_enabled`): use `true`/`false` literals in SQL and `.is_(False)` in ORM; never compare with 0/1 (DatatypeMismatch).
- SQLite: WAL mode + `check_same_thread` set in `src/database/connection.py`. `DATABASE_URL` selects the engine.
- Migration 009 (RLS) checks `pg_class.relrowsecurity` and skips already-protected tables (it timed out otherwise).

### Deployment: local only
- Railway (engine.pulsebuilt.net) is shut down, and the Supabase project and its data were deleted (2026-11-06). Don't try to reach either one.
- FastAPI serves `frontend-react/dist/` (`/assets` StaticFiles + `spa_fallback`, with a `/demo` special case) when `dist/` exists. Same-origin, so `VITE_API_URL` is unneeded.
- Leftovers that Phase 5 removes or simplifies: `railway.toml`, `frontend-react/vercel.json`, and Supabase tuning in `scripts/start.sh` (single-connection migrations, `sslmode=require`, sequence reset). Migration 009 (RLS) is a no-op on SQLite. Old deployment details are in `docs/history/build-log.md`.

## Environment
- GitHub: https://github.com/UncannyJ33/garmin-whoop-dashboard (private); `gh` authenticated as UncannyJ33

## Future considerations
- **Garmin sleep schema**: assumes the watch isn't worn in bed, so `garmin_sleep`/`garmin_hrv` are near-empty. If both sources are populated, the unified sleep schema must handle two sources (maybe Whoop-primary vs Garmin-primary, or a per-user `sleep_device` setting).
- **FIT parsing** (`download-service` ZIP → `.FIT` `set` messages) for set-level strength data (D4 follow-up).
