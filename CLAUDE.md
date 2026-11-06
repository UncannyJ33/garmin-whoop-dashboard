# Fitness Dashboard — Claude Code Context

## Project
Personal Garmin + Whoop fitness dashboard. Single user (SJ), self-hosted. Formerly PulseEngine, a multi-user SaaS (Jan–Apr 2026); that history is in `docs/history/build-log.md`.
- Backend: Python 3.11+ / FastAPI / SQLAlchemy. SQLite locally (default), Postgres supported.
- Frontend: React 18 + TypeScript + Vite + TailwindCSS + Recharts + TanStack Query (`frontend-react/`).

## Status: relaunch in progress (started 2026-11-06)
`main` is still the old SaaS build. Goal: a basic private dashboard, Garmin via Garmin's official Personal API.
Code that still exists but is **slated for removal. Don't extend it; don't add multi-user features**:
- open registration, waitlist, `Landing`/`Privacy`/`Onboarding`/`Showcase`/`ApiTest`/`Demo` pages, `pulse-demo/`, `/demo` mount
- Whoop allowlist + feature flags, account deletion
- `garminconnect` password login, Fernet-encrypted `garmin_credentials`, per-user scheduler with 429 backoff/auto-disable
- Whoop webhook receiver (`src/api/routes/webhooks.py`)
- legacy Streamlit app (`frontend/`)

Roadmap: `plans/2026-11-06-personal-relaunch-roadmap.md` (phases 0–7, decisions D1–D7, questions Q1–Q3). Phase 2 plan: `plans/2026-11-06-garmin-personal-api-client.md`.
Decisions agents must respect:
- **D1** Keep JWT login + `user_id` plumbing with exactly one owner user (`scripts/create_owner.py`, planned). Don't rip out `user_id`.
- **D2** Own small `httpx` client for the Garmin Personal API. Don't use Garmin's official package (reference only).
- **D3** Polling only. No webhooks.
- **D4** Strength = `summarizedExerciseSets` (per-exercise), not set-level, for now.
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
- Ingestion (`src/ingestion/`): `whoop_pipeline.py`, `garmin_pipeline.py` (both take `(db, user_id)`, tag rows + `SyncLog`, call `normalize_all()` after sync), `scheduler.py` (APScheduler: Garmin every 15 min, Whoop every 30), `csv_import.py`, `garmin_csv_parser.py`. Incremental sync resumes from last successful `sync_log` `sync_end`; window in `sync_log.metadata_json` (`sync_start`/`sync_end`; Garmin uses `date`, not `datetime`).
- Clients (`src/clients/`): `whoop_auth.py`, `whoop_client.py` (pagination + retry), `garmin_auth.py`, `garmin_client.py` (garminconnect-era, being replaced).
- Normalization (`src/normalization/`): `whoop_mapper.py`, `garmin_mapper.py`, `deduplication.py`, `normalizer.py`; field decisions in `config/field_mappings.yaml`; `comparison_tool.py` + `scripts/schema_review.py` for schema review (CSVs to gitignored `data/review/`). Unified tables: `unified_daily`, `unified_sleep`, `unified_workouts`.
- Analytics (`src/analytics/`, all take `user_id`):
  - `readiness_score.py` — 5 components: whoop_recovery 30%, hrv_trend 25%, body_battery 20%, sleep_quality 15%, training_load 10%; HRV z-score; weights redistribute when a source is missing
  - `workout_analysis.py` (Whoop+Garmin enrichment: strain/min, efficiency, recovery impact), `sleep_analysis.py` (strain↔sleep Pearson r, consistency), `trends.py` (rolling avgs, z-score anomalies, weekly/monthly rollups), `training_load.py` (ACWR), `limiting_factors.py`, `weekly_digest.py`, `anomaly_store.py` (anomaly_cache, filled after each sync), `cache.py` (in-memory TTL)
- Auth (`src/auth/`): JWT (HS256, `JWT_SECRET`), bcrypt; `get_current_user` on protected routes.
- API (`src/api/routes/`): readiness, workouts, sleep, recovery, training, trends, insights, sync, auth, account, garmin_upload, garmin_csv, garmin_credentials, waitlist, webhooks. Models in `src/api/models.py`; docs at `/docs`.
- DB: `src/database/` (models, `connection.py`, `migrations/`; run at startup).
- React (`frontend-react/src/`): pages Today `/`, Training, Recovery, Insights, Settings (+ Login, GarminHelp); legacy redirects `/readiness`→`/`, `/workouts`→`/training`, `/sleep`→`/recovery`, `/trends`→`/insights`, `/recovery-activities`→`/recovery`. Hooks in `src/hooks/useApi.ts`, client `src/api/client.ts`, auth token held in memory (`AuthContext`), `DateRangeContext`, routes lazy-loaded.

## Key decisions & alignment rules
- **Source of truth**: Whoop = recovery, sleep quality, body vitals. Garmin = workout detail, running dynamics.
- Store raw API responses in `raw_json` for reprocessing.
- **Workout dedup** by timestamp + duration only: Whoop strain workouts (strain IS NOT NULL) matched to Garmin if start diff ≤5 min (`MATCH_START_THRESHOLD_MIN`) and duration diff ≤20% (`MATCH_DURATION_THRESHOLD_PCT`). End-time fallback for Whoop early detection (strength): `MATCH_END_THRESHOLD_MIN=5`, `MATCH_END_DURATION_THRESHOLD_PCT=0.25`, `_END_MATCH_CONFIDENCE_PENALTY=0.8` (`deduplication.py`). Whoop non-strain activities (walks, stretches) stay out of the match.
- **Daily alignment**: key Whoop recovery by `DATE(whoop_cycles.start_time)` (cycle starts at wake) = Garmin `garmin_daily_summary.date`. Alternative (`DATE(whoop_sleep.end_time)` via join) rejected as extra join/edge cases; revisit on off-by-one errors.
- **Sleep alignment**: Whoop is truth, keyed by `DATE(whoop_sleep.end_time)` (morning you woke). Garmin sleep `date` is already the wake date. Keying by bedtime date would be off-by-one.
- Garmin sleep/HRV rows are mostly missing (watch not worn at night; Whoop is). `get_sleep`/`get_hrv` returning None is normal.
- `get_activity_detail` is NOT called during ingestion: running dynamics, VO2 max, training load are already in the activity list. `avg_ground_contact_balance` is unavailable and stored NULL.
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
**garminconnect-era (current code)**, confirmed against live responses:
- `activityId` → `activity_id` (`str()`, large int); `activityType.typeKey` → `activity_type`; `startTimeLocal`/`startTimeGMT` → `start_time`/`start_time_gmt`
- `averageHR`/`maxHR` → `avg_heart_rate`/`max_heart_rate` (cast to int); `averageRunningCadenceInStepsPerMinute` → `avg_running_cadence`; `vO2MaxValue` → `vo2_max`
- `aerobicTrainingEffect`/`anaerobicTrainingEffect` → `training_effect_aerobic`/`_anaerobic`; `activityTrainingLoad` → `training_load`; `avgGroundContactTime`/`avgVerticalOscillation`/`avgVerticalRatio` → same pattern
- Daily summary: `totalSteps`, `totalDistanceMeters`, `activeKilocalories`, `bodyBatteryHighestValue`/`LowestValue`, `averageSpo2`/`lowestSpo2`, `averageStressLevel`/`maxStressLevel`; `get_body_battery()` returns a list, take `[0]`
- Sleep: nested under `dailySleepDTO`; timestamps Unix ms → ISO 8601 at ingest
- HRV: under `hrvSummary` + `baseline`; `weeklyAvg`, `lastNight`, `lastNight5MinHigh`
- Exercise sets (garminconnect `get_activity_exercise_sets`): weight in **grams** (÷1000 → kg); exercise field is `name` (not `exerciseName`); order is `messageIndex`; `startTime` is an ISO string; exercises sorted by probability descending. Table `garmin_exercise_sets`, migration 004.

**Personal API (planned; research doc §4)**: same shapes for activities, daily summary (one call: `/usersummary-service/usersummary/daily`) and HRV, except:
- Sleep is a flat `DailySleepDTO` (no wrapper): `sleepScores.overall.value` (key unverified), `avgSleepStress`.
- HRV field is `lastNightAvg`; the current transform reads `lastNight` (`garmin_pipeline.py:258`), likely a bug that leaves `last_night_avg_ms` NULL. 204 = no data.
- No exercise-sets endpoint; use `summarizedExerciseSets` on activity records. The spec says `maxWeight`/`volume` are in grams and `duration` is in ms; confirm in the Phase 1 spike.
- The spec declares sleep timestamps as `string/date-time`, while garminconnect returned Unix ms; the transform must accept both.
- Not in the API: training readiness/status, acute load, VO2max endpoints. `vO2MaxValue`/`activityTrainingLoad` may come back empty; verify.

## Conventions
- Python 3.11+; type hints on all functions; docstrings on public functions
- Tests in `tests/` with pytest
- Secrets in `.env`, never hardcoded
- Always use the venv: `source .venv/bin/activate`
- Lint with `ruff`: `make lint`, auto-fix `make fmt`
- `timezone.utc` → `datetime.UTC` (ruff UP017)
- Frontend `sys.path` manipulation (Streamlit) needs `# noqa: E402` on following imports
- UI preference: no zoom on any chart (don't add `selection_interval` / brush; React charts currently have none)
- **Never commit** `.env`, credentials, tokens, DB files, Garmin/Whoop exports, or personal health data. Raw API samples go in gitignored `data/`; test fixtures must be sanitized.

## Local dev
A fresh checkout needs `uv sync --frozen` and `cd frontend-react && npm ci`. As of 2026-11-06 the local `.venv` (Python 3.12) and `node_modules` exist, and `.env` exists (gitignored). `uv` is **not** installed globally (`brew install uv`); the old `/opt/homebrew/bin/uv` note is stale.
- Backend (port 8000): `make run-api`
- Frontend: `cd frontend-react && npm run dev` — Vite port **5173** (per `vite.config.ts`; old docs also said 5175, wrong), proxies `/api` → `VITE_API_URL` or `http://localhost:8000`
- `make test` (pytest), `make lint`, `make fmt`, `make run-sync` (`scripts/initial_sync.py`), `make run-frontend` (legacy Streamlit, port 8501)
- `cd frontend-react && npm run build` (tsc + vite build → `dist/`), `npm run typecheck`
- Container: `docker compose up --build` → port 8000; needs `.env` (copy `.env.example`)
- Local `.env`: `DATABASE_URL=sqlite:///data/fitness_dashboard.db`; `JWT_SECRET` must be set even locally.
- Gotcha: Vite `/api` is a prefix match — dev-only routes must not start with `/api` (e.g. use `/dev/api-test`).

## Testing patterns
- In-memory SQLite: share one engine across fixtures (`sqlite:///:memory:` is per-engine isolated)
- Mock httpx: patch `httpx.AsyncClient` at module level; set `__aenter__`/`__aexit__` on the mock instance
- Mock sleep: `patch("src.clients.whoop_client.asyncio.sleep", new_callable=AsyncMock)`
- Digit-prefixed migrations (`001_initial.py`) can't be imported directly; loaded via `importlib.util` in `migrations/__init__.py`
- Baseline (2026-11-06): **909 passed** with serial `.venv/bin/pytest -q`. xdist (`-n auto`, pytest-xdist is installed) is **broken**: SQLite collection errors in `test_data_isolation.py` and `test_garmin_credentials.py`. Run serially.
- Lint baseline: 25 existing ruff errors, scheduled for cleanup at the start of Phase 2.

## Database gotchas
- Postgres BOOLEAN columns (`nap`, `matched`, `auto_sync_enabled`): use `true`/`false` literals in SQL and `.is_(False)` in ORM; never compare with 0/1 (DatatypeMismatch).
- SQLite: WAL mode + `check_same_thread` set in `src/database/connection.py`. `DATABASE_URL` selects the engine.
- Migration 009 (RLS) checks `pg_class.relrowsecurity` and skips already-protected tables (it timed out otherwise).

### Deployment: local only
- Railway (engine.pulsebuilt.net) is shut down, and the Supabase project and its data were deleted (2026-11-06). Don't try to reach either one.
- FastAPI serves `frontend-react/dist/` (`/assets` StaticFiles + `spa_fallback`, with a `/demo` special case) when `dist/` exists. Same-origin, so `VITE_API_URL` is unneeded.
- Leftovers that Phase 5 removes or simplifies: `railway.toml`, `frontend-react/vercel.json`, and Supabase tuning in `scripts/start.sh` (single-connection migrations, `sslmode=require`, sequence reset). Migration 009 (RLS) is a no-op on SQLite. Old deployment details are in `docs/history/build-log.md`.

## Streamlit (legacy, slated for removal)
- Run: `streamlit run frontend/app.py`. Views live in `frontend/views/`; never use `frontend/pages/` (Streamlit auto-discovers it and breaks manual routing).
- Charts use Altair directly (v6: `alt.SelectionParameter`); views read unified tables, not raw `whoop_*`.

## Environment
- GitHub: https://github.com/UncannyJ33/garmin-whoop-dashboard (private); `gh` authenticated as UncannyJ33

## Future considerations
- **Garmin sleep schema**: assumes the watch isn't worn in bed, so `garmin_sleep`/`garmin_hrv` are near-empty. If both sources are populated, the unified sleep schema must handle two sources (maybe Whoop-primary vs Garmin-primary, or a per-user `sleep_device` setting).
- **FIT parsing** (`download-service` ZIP → `.FIT` `set` messages) for set-level strength data (D4 follow-up).
