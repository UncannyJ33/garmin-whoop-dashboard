# Per-Phase Task Breakdowns: Garmin + Whoop Dashboard

---

## How to Use This Document

Each task is a single Claude Code session. They're designed to be completed in order — later tasks depend on earlier ones. For each task you'll find:

- **What you're building** — the deliverable
- **Claude Code prompt** — a starting prompt you can paste directly into CC (adapt as needed)
- **Acceptance criteria** — how you know the task is done
- **Dependencies** — what needs to exist before you start this task
- **Files touched** — where the work lives in the project structure
- **Estimated effort** — rough time including review (not just generation)

After each CC session: read every file created, ask CC to explain anything unclear, run the code, then commit.

---

## Phase 1: Whoop Proof of Concept

**Goal:** See your last 30 days of Whoop data on screen in a Streamlit dashboard.

**Total estimated time:** 1–2 weeks (8–12 sessions)

---

### Task 1.1: Project Scaffolding

**What:** Initialize the repo with folder structure, dependency management, and configuration.

**Dependencies:** None — this is the starting point.

**Claude Code prompt:**
```
Set up a Python project for a fitness dashboard. Use uv for dependency management.
Create the folder structure as defined in our technical design doc:
- src/ with subdirectories: api/, clients/, ingestion/, normalization/, database/, analytics/
- frontend/ with pages/ and components/
- config/, scripts/, tests/
- Each directory needs an __init__.py

Create pyproject.toml with these initial dependencies:
- fastapi, uvicorn
- sqlalchemy
- httpx (for async HTTP requests to Whoop)
- python-dotenv
- apscheduler
- streamlit
- pytest

Create a .env.example with placeholder values for:
- WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, WHOOP_REDIRECT_URI
- DATABASE_URL (default: sqlite:///data/fitness_dashboard.db)
- APP_PORT, STREAMLIT_PORT, LOG_LEVEL

Create a .gitignore that excludes: .env, data/, __pycache__/, .venv/, *.pyc, .garminconnect/

Create config/settings.py that loads all env vars using python-dotenv with sensible defaults.
```

**Acceptance criteria:**
- `uv sync` installs all dependencies without errors
- Every directory exists with `__init__.py`
- `.env.example` has all required variables
- `config/settings.py` loads and validates env vars
- `python -c "from config.settings import settings; print(settings)"` works

**Files touched:**
```
pyproject.toml, .gitignore, .env.example
config/settings.py
src/__init__.py, src/api/__init__.py, src/clients/__init__.py, etc.
```

**Estimated effort:** 30–45 minutes (including review)

---

### Task 1.2: CLAUDE.md and README

**What:** Create the CLAUDE.md project context file and a basic README.

**Dependencies:** Task 1.1 (project structure exists)

**This is partially manual.** Start from the template in the technical design doc (Section 10), then customize it with your own context. CC can help draft the README.

**Claude Code prompt:**
```
Create a README.md for this project. It should cover:
- Project description (personal fitness dashboard integrating Garmin + Whoop)
- Tech stack summary
- Setup instructions (clone, create .env, uv sync, run)
- Project structure overview (brief, not exhaustive)
- Current status (Phase 1 in progress)

Keep it concise — this will evolve as the project grows.
```

**Acceptance criteria:**
- CLAUDE.md exists with accurate project context, current phase, and conventions
- README.md has enough info for you to set the project up from scratch if you forget
- Both files committed

**Files touched:** `CLAUDE.md`, `README.md`

**Estimated effort:** 20–30 minutes

---

### Task 1.3: SQLite Database Setup

**What:** Create the database connection layer and initial schema migration for Whoop tables.

**Dependencies:** Task 1.1 (settings.py exists with DATABASE_URL)

**Claude Code prompt:**
```
Create the database layer for our fitness dashboard.

In src/database/connection.py:
- Create a function that initializes a SQLite connection using SQLAlchemy
- Use WAL mode for better concurrent read/write performance
- The database path should come from config/settings.py DATABASE_URL
- Create the data/ directory if it doesn't exist

In src/database/models.py:
- Define SQLAlchemy models for the Phase 1 Whoop tables only:
  - whoop_cycles (id, user_id, start_time, end_time, timezone_offset, score_state, strain, kilojoules, avg_heart_rate, max_heart_rate, fetched_at, raw_json)
  - whoop_recovery (id, cycle_id FK, sleep_id, score_state, recovery_score, resting_heart_rate, hrv_rmssd, spo2_pct, skin_temp_celsius, fetched_at, raw_json)
  - whoop_sleep (id, cycle_id FK, start_time, end_time, timezone_offset, nap, score_state, total_in_bed_ms, total_awake_ms, total_light_ms, total_sws_ms, total_rem_ms, total_no_data_ms, sleep_performance, sleep_consistency, sleep_efficiency, respiratory_rate, fetched_at, raw_json)
  - whoop_workouts (id, cycle_id FK, start_time, end_time, timezone_offset, sport_id, sport_name, score_state, strain, avg_heart_rate, max_heart_rate, kilojoules, distance_meter, altitude_gain_meter, altitude_change_meter, zone_durations_json, fetched_at, raw_json)
  - sync_log (id autoincrement, source, sync_type, started_at, completed_at, records_fetched, records_stored, status, error_message, metadata_json)
  - token_store (service PK, access_token, refresh_token, expires_at, token_data_json, updated_at)

In src/database/migrations/001_initial.py:
- Create a script that creates all tables if they don't exist
- Use SQLAlchemy's create_all

Add a simple test in tests/test_database.py that:
- Creates an in-memory SQLite database
- Runs the migration
- Inserts and retrieves a test record from each table
```

**Acceptance criteria:**
- Running `python -m src.database.migrations.001_initial` creates the database file in `data/`
- All six tables exist with correct columns
- Tests pass: `pytest tests/test_database.py`
- You can open the database with a SQLite browser and see empty tables

**Files touched:**
```
src/database/connection.py
src/database/models.py
src/database/migrations/001_initial.py
tests/test_database.py
```

**Estimated effort:** 45–60 minutes

---

### Task 1.4: Whoop OAuth Module

**What:** Build the OAuth 2.0 authorization flow for Whoop, including token storage and refresh.

**Dependencies:** Task 1.3 (database with token_store table). You must also have your Whoop developer app registered with Client ID and Client Secret ready.

**Before this session:** Register your app at https://developer-dashboard.whoop.com. Set the redirect URI to `http://localhost:8000/api/auth/whoop/callback`. Note your Client ID and Client Secret. Add them to your `.env` file.

**Claude Code prompt:**
```
Build the Whoop OAuth 2.0 module for our fitness dashboard.

In src/clients/whoop_auth.py, create a WhoopAuth class that handles:

1. Authorization URL generation:
   - Build the URL to redirect the user to Whoop's auth page
   - Include scopes: read:recovery, read:cycles, read:workout, read:sleep, read:body_measurement, read:profile, offline
   - Include a random state parameter for CSRF protection

2. Token exchange:
   - Exchange the authorization code for access + refresh tokens
   - POST to https://api.prod.whoop.com/oauth/oauth2/token
   - Store tokens in the token_store database table

3. Token refresh:
   - Check if the access token is expired (they expire in 1 hour)
   - If expired, use the refresh token to get a new access token
   - Update the token_store table with new tokens

4. Token retrieval:
   - Method that returns a valid access token, auto-refreshing if needed
   - This is what the API client will call before every request

In src/api/routes/auth.py, create two FastAPI routes:
   - GET /api/auth/whoop — redirects to Whoop authorization URL
   - GET /api/auth/whoop/callback — handles the OAuth callback, exchanges code for tokens, stores them

Use httpx for HTTP requests (async). Load client_id, client_secret, redirect_uri from settings.

Add tests in tests/test_whoop_auth.py that:
- Test authorization URL generation (correct params, scopes, state)
- Test token refresh logic with mocked HTTP responses
- Test expired token detection
```

**Acceptance criteria:**
- Start the FastAPI server, visit `/api/auth/whoop` in a browser
- Get redirected to Whoop's login page
- After authorizing, get redirected back with tokens stored in the database
- `token_store` table has a row for "whoop" with valid tokens
- Token refresh works when you manually expire the access token
- Tests pass

**Files touched:**
```
src/clients/whoop_auth.py
src/api/routes/auth.py
src/api/main.py (register the auth router)
tests/test_whoop_auth.py
```

**Estimated effort:** 1.5–2 hours (OAuth is fiddly — budget extra time for debugging the redirect flow)

---

### Task 1.5: Whoop API Client

**What:** Build the REST client that fetches data from all Whoop endpoints with pagination and error handling.

**Dependencies:** Task 1.4 (WhoopAuth provides valid access tokens)

**Claude Code prompt:**
```
Build the Whoop API client for our fitness dashboard.

In src/clients/whoop_client.py, create a WhoopClient class that:

1. Uses httpx.AsyncClient for all requests
2. Gets access tokens from WhoopAuth (auto-refreshes if expired)
3. Sets Authorization: Bearer <token> header on every request
4. Base URL: https://api.prod.whoop.com/developer/v2

Implement these methods, all with pagination support:

- get_cycles(start_date, end_date) -> list of cycle dicts
- get_recovery(start_date, end_date) -> list of recovery dicts
- get_sleep(start_date, end_date) -> list of sleep dicts
- get_workouts(start_date, end_date) -> list of workout dicts
- get_body_measurements() -> single dict
- get_profile() -> single dict

Pagination pattern for collection endpoints:
- Pass start/end as ISO 8601 query params
- Response has "records" (list) and "next_token" (string or null)
- If next_token exists, make another request with nextToken=<value>
- Collect all pages into a single list and return

Error handling:
- 429 (rate limited): exponential backoff starting at 1s, max 60s, max 5 retries
- 401 (unauthorized): trigger token refresh and retry once
- 500 (server error): retry up to 3 times with backoff
- Log all errors with the endpoint, status code, and response body

Add tests in tests/test_whoop_client.py that:
- Mock HTTP responses and verify correct pagination assembly
- Test rate limit retry logic
- Test token refresh on 401
- Test that all methods return the expected data structure
```

**Acceptance criteria:**
- With valid tokens in the database, each method successfully fetches real data from Whoop
- Pagination works: fetching 60 days of data (more than 25 records) returns all pages
- Rate limit handling works (can test by inspecting retry logs)
- All tests pass

**Files touched:**
```
src/clients/whoop_client.py
tests/test_whoop_client.py
```

**Estimated effort:** 1–1.5 hours

---

### Task 1.6: Whoop Ingestion Pipeline

**What:** Build the ETL pipeline that fetches Whoop data, transforms it, and stores it in the database.

**Dependencies:** Task 1.5 (WhoopClient can fetch data), Task 1.3 (database tables exist)

**Claude Code prompt:**
```
Build the Whoop data ingestion pipeline.

In src/ingestion/whoop_pipeline.py, create a WhoopPipeline class that orchestrates:

1. Determine sync window:
   - Check sync_log for the last successful whoop sync
   - If no previous sync, default to 30 days ago
   - Sync from last_sync_end to now

2. Fetch data:
   - Use WhoopClient to fetch cycles, recovery, sleep, and workouts for the sync window
   - Log the fetch: create a sync_log entry with status "running"

3. Transform data:
   - Flatten the API response dicts into our database column format
   - Store the complete original response in raw_json
   - Set fetched_at to current UTC timestamp
   - Handle missing/null fields gracefully (some cycles may not be scored yet)

4. Store data:
   - Upsert into the appropriate whoop_* tables (insert or update on conflict by primary key)
   - Track records_fetched and records_stored counts

5. Complete sync:
   - Update sync_log entry with completed_at, record counts, and status "success"
   - If any step fails, update status to "error" with the error message

Also create a simple run script at scripts/initial_sync.py that:
- Initializes the database if needed
- Runs the WhoopPipeline for the last 30 days
- Prints a summary of what was synced

Add tests in tests/test_whoop_pipeline.py that:
- Test the transform step with sample API response data
- Test upsert behavior (running twice doesn't duplicate records)
- Test sync_log tracking
```

**Acceptance criteria:**
- Run `python scripts/initial_sync.py` and see 30 days of data land in the database
- Check each whoop_* table — rows exist with real data
- Run it again — record count stays the same (upserts, not duplicates)
- sync_log has entries showing successful syncs
- Tests pass

**Files touched:**
```
src/ingestion/whoop_pipeline.py
scripts/initial_sync.py
tests/test_whoop_pipeline.py
```

**Estimated effort:** 1–1.5 hours

**This is a big milestone — after this task, you have real data in your database.**

---

### Task 1.7: Streamlit Dashboard (Basic)

**What:** Build a basic Streamlit frontend that visualizes the Whoop data you've ingested.

**Dependencies:** Task 1.6 (database has real Whoop data)

**Claude Code prompt:**
```
Build a basic Streamlit dashboard for our fitness data.

In frontend/app.py:
- Create the main Streamlit app with a sidebar for navigation
- Page options: Recovery, Sleep, Workouts
- Add a date range selector (default: last 30 days)

In frontend/pages/readiness.py (start simple, this becomes the full readiness view in Phase 3):
- Query whoop_recovery for the selected date range
- Show a line chart of recovery score over time
- Show a line chart of HRV (hrv_rmssd) over time
- Show current day's recovery score as a big number
- Show resting heart rate trend

In frontend/pages/sleep.py:
- Query whoop_sleep for the selected date range
- Show total sleep time per night as a bar chart
- Show sleep stage breakdown (light, SWS, REM, awake) as a stacked bar chart
- Show sleep performance trend as a line chart

In frontend/pages/workouts.py:
- Query whoop_workouts for the selected date range
- Show a table of recent workouts (date, sport_name, strain, avg HR, duration)
- Show strain over time as a line chart

Read directly from the SQLite database using SQLAlchemy. We'll move to FastAPI endpoints later.
Keep it functional, not pretty — we're validating the data pipeline, not building the final UI.
```

**Acceptance criteria:**
- `streamlit run frontend/app.py` launches without errors
- All three pages render with real data from your database
- Charts are readable and show expected patterns (recovery varies, sleep stages look reasonable)
- Date range filter works across all pages
- You can look at this dashboard and learn something about your training

**Files touched:**
```
frontend/app.py
frontend/pages/readiness.py
frontend/pages/sleep.py
frontend/pages/workouts.py
```

**Estimated effort:** 1–1.5 hours

**This is the Phase 1 milestone — your data is visible on screen.**

---

### Task 1.8: Unit Tests and Cleanup

**What:** Fill in test coverage gaps, clean up code quality, and make sure everything is solid before moving on.

**Dependencies:** All prior Phase 1 tasks

**Claude Code prompt:**
```
Review the current codebase and improve test coverage and code quality.

1. Run all existing tests and fix any failures
2. Add any missing tests — target the transform/mapping functions in the pipeline, edge cases in OAuth token expiry, and database upsert behavior
3. Add type hints to any functions missing them
4. Add docstrings to all public functions
5. Create a simple Makefile or scripts entry with common commands:
   - run-api: starts FastAPI
   - run-frontend: starts Streamlit
   - run-sync: triggers a data sync
   - test: runs pytest
   - lint: runs ruff or similar
6. Review and update CLAUDE.md with anything that's changed during Phase 1
```

**Acceptance criteria:**
- `pytest` passes with no failures
- All public functions have type hints and docstrings
- Common commands work from the Makefile
- CLAUDE.md reflects the current state of the project

**Files touched:** Various — test files, existing source files, Makefile, CLAUDE.md

**Estimated effort:** 1 hour

---

### Task 1.9: Dockerize

**What:** Add Docker and docker-compose to containerize the application.

**Dependencies:** Task 1.8 (everything works locally and tests pass)

**Claude Code prompt:**
```
Add Docker support to the fitness dashboard project.

Create a Dockerfile that:
- Uses python:3.11-slim as base image
- Installs uv and project dependencies
- Copies the source code
- Does NOT copy .env (that's mounted at runtime)
- Exposes ports 8000 (FastAPI) and 8501 (Streamlit)

Create a docker-compose.yml with two services:
- backend: runs uvicorn, exposes port 8000, mounts data/ and config/ as volumes
- frontend: runs streamlit, exposes port 8501, depends on backend

Both services should:
- Use the same Dockerfile
- Load env vars from .env via env_file
- Mount the data/ directory so the SQLite database persists

Add a section to README.md with Docker setup instructions.
Test that docker-compose up builds and runs both services successfully.
```

**Acceptance criteria:**
- `docker-compose up --build` starts both services without errors
- Streamlit dashboard is accessible at localhost:8501 with data from the mounted database
- Stopping and restarting preserves the database
- README has clear Docker instructions

**Files touched:** `Dockerfile`, `docker-compose.yml`, `README.md`

**Estimated effort:** 45–60 minutes

---

### Phase 1 Checklist

Before moving to Phase 2, confirm all of these:

- [ ] Whoop OAuth flow works end-to-end (auth → token → refresh)
- [ ] 30 days of Whoop data lives in SQLite across all four tables
- [ ] Streamlit dashboard renders recovery, sleep, and workout views
- [ ] Running the sync twice doesn't duplicate data
- [ ] All tests pass
- [ ] Docker setup works
- [ ] CLAUDE.md is current
- [ ] Everything is committed to GitHub

---

## Phase 2: Add Garmin Integration

**Goal:** Garmin data flowing alongside Whoop, with a unified schema you've personally reviewed and approved.

**Total estimated time:** 1.5–2.5 weeks (9–12 sessions)

---

### Task 2.1: Garmin Auth Module

**What:** Build authentication for the garminconnect library with session persistence and error recovery.

**Dependencies:** Phase 1 complete. `pip install garminconnect` added to dependencies.

**Claude Code prompt:**
```
Build the Garmin authentication module for our fitness dashboard.

In src/clients/garmin_auth.py, create a GarminAuth class that:

1. Initializes the Garmin() client from the garminconnect library
2. Loads credentials from settings (GARMIN_EMAIL, GARMIN_PASSWORD)
3. Handles token persistence:
   - garminconnect stores tokens in ~/.garminconnect/ by default
   - On first login, authenticate with email/password
   - On subsequent starts, load existing tokens (no password needed)
   - Store the token directory path in settings so Docker can mount it

4. Session recovery:
   - Wrap authentication in try/except
   - If token loading fails, fall back to email/password login
   - If login fails, raise a clear error with instructions

5. Provides a get_client() method that returns a ready-to-use Garmin() instance
   - Checks if the session is still valid before returning
   - Re-authenticates if needed

Add error handling for common garminconnect exceptions:
- GarthHTTPError with 401: re-authenticate
- GarthHTTPError with 429: rate limited, raise with message about waiting
- GarthHTTPError with 403: account locked, raise with clear message

Add tests in tests/test_garmin_auth.py that:
- Test token loading from existing directory (mock the filesystem)
- Test fallback to password login when tokens are missing
- Test re-auth flow on 401 errors
```

**Acceptance criteria:**
- First run: authenticates with email/password, stores tokens
- Second run: loads tokens without needing password
- After manual token deletion: falls back to password login
- Clear error messages for auth failures
- Tests pass

**Files touched:**
```
src/clients/garmin_auth.py
config/settings.py (add GARMIN_EMAIL, GARMIN_PASSWORD, GARMIN_TOKEN_DIR)
.env.example (add Garmin vars)
tests/test_garmin_auth.py
```

**Estimated effort:** 45–60 minutes

---

### Task 2.2: Garmin API Client

**What:** Build a data client that wraps the garminconnect methods you need, with rate limiting and error handling.

**Dependencies:** Task 2.1 (GarminAuth provides a working Garmin client)

**Claude Code prompt:**
```
Build the Garmin data client for our fitness dashboard.

In src/clients/garmin_client.py, create a GarminClient class that:

1. Gets the Garmin() instance from GarminAuth
2. Wraps each API method with consistent error handling and rate limiting

Implement these methods (each takes a date or date range):

- get_activities(start_date, end_date) -> list of activity dicts
  Uses: garmin.get_activities_by_date()

- get_activity_detail(activity_id) -> dict with full activity data
  Uses: garmin.get_activity(activity_id)
  Only call this for activities where you need running dynamics

- get_daily_summary(date) -> dict
  Combines: garmin.get_stats(date), get_heart_rates(date), get_body_battery(date), get_stress_data(date)
  Merges into a single dict

- get_sleep(date) -> dict
  Uses: garmin.get_sleep_data(date)

- get_hrv(date) -> dict
  Uses: garmin.get_hrv_data(date)

Rate limiting:
- Add a configurable delay between requests (default: 1.5 seconds)
- This keeps us well under the ~50 req/min unofficial limit
- Use a simple time.sleep() between calls

Error handling for EACH method:
- GarthHTTPError 400/404: log warning, return None (endpoint may not be available)
- GarthHTTPError 401: trigger re-auth via GarminAuth, retry once
- GarthHTTPError 429: log error, sleep 60 seconds, retry once
- Any other exception: log error, return None, don't crash the pipeline

IMPORTANT: Some garminconnect methods are known to break when Garmin updates their web app.
Every method should be independently resilient — one broken endpoint should not prevent the others from working.

Add tests in tests/test_garmin_client.py that:
- Test rate limiting delay between calls
- Test error handling returns None on 400/404
- Test retry logic on 401 and 429
```

**Acceptance criteria:**
- Each method returns real data for today's date
- If one endpoint fails (e.g., get_spo2_data), the others still work
- Rate limiting is visible in logs (you can see the delay between requests)
- Tests pass

**Files touched:**
```
src/clients/garmin_client.py
tests/test_garmin_client.py
```

**Estimated effort:** 1–1.5 hours

---

### Task 2.3: Garmin Database Tables

**What:** Add the Garmin raw tables and system table updates to the schema.

**Dependencies:** Task 2.2 (you know what data Garmin actually returns)

**Claude Code prompt:**
```
Add Garmin tables to our database schema.

In src/database/models.py, add SQLAlchemy models for:
- garmin_activities (activity_id PK, activity_type, activity_name, start_time, start_time_gmt, duration_seconds, elapsed_seconds, distance_meters, avg_heart_rate, max_heart_rate, avg_running_cadence, max_running_cadence, calories, avg_speed, max_speed, elevation_gain, elevation_loss, avg_stride_length, vo2_max, training_effect_aerobic, training_effect_anaerobic, training_load, avg_ground_contact_time, avg_vertical_oscillation, avg_vertical_ratio, avg_ground_contact_balance, fetched_at, raw_json)
- garmin_daily_summary (date PK, total_steps, total_distance_m, active_calories, total_calories, resting_heart_rate, min_heart_rate, max_heart_rate, avg_stress_level, max_stress_level, body_battery_high, body_battery_low, avg_spo2, lowest_spo2, fetched_at, raw_json)
- garmin_sleep (date PK, start_time, end_time, total_sleep_seconds, deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds, awake_seconds, sleep_score, avg_spo2_sleep, avg_respiration, lowest_respiration, avg_stress_sleep, fetched_at, raw_json)
- garmin_hrv (date PK, weekly_avg_ms, last_night_avg_ms, last_night_5min_high, baseline_low_ms, baseline_balanced_low, baseline_balanced_up, status, fetched_at, raw_json)

Create src/database/migrations/002_garmin_tables.py:
- Creates the new tables without affecting existing Whoop tables
- Idempotent: safe to run multiple times

Update tests/test_database.py to cover the new tables.
```

**Acceptance criteria:**
- Running migration creates four new Garmin tables alongside existing Whoop tables
- Existing Whoop data is untouched
- Tests pass for both old and new tables

**Files touched:**
```
src/database/models.py
src/database/migrations/002_garmin_tables.py
tests/test_database.py
```

**Estimated effort:** 30–45 minutes

---

### Task 2.4: Garmin Ingestion Pipeline

**What:** Build the ETL pipeline for Garmin, mirroring the Whoop pipeline pattern.

**Dependencies:** Task 2.2 (GarminClient works), Task 2.3 (Garmin tables exist)

**Claude Code prompt:**
```
Build the Garmin data ingestion pipeline, following the same pattern as the Whoop pipeline.

In src/ingestion/garmin_pipeline.py, create a GarminPipeline class that:

1. Determine sync window:
   - Check sync_log for last successful garmin sync
   - Default to 30 days ago if no previous sync
   - For daily data (summary, sleep, HRV): sync each date in the window
   - For activities: use get_activities(start_date, end_date) for the whole range

2. Fetch data:
   - Use GarminClient for each data type
   - If a method returns None (endpoint failure), log it and skip that data type
   - Don't let one failed endpoint stop the whole sync

3. Transform data:
   - Flatten Garmin's inconsistent JSON into our column format
   - Note: Garmin returns different structures for different endpoints
   - Store complete response in raw_json
   - Handle missing fields with None (not all activities have running dynamics)

4. Store data:
   - Upsert into garmin_* tables
   - For activities: upsert by activity_id
   - For daily data: upsert by date

5. For activities that are runs, also fetch detailed activity data:
   - Call get_activity_detail(activity_id) for running activities
   - This gets the running dynamics fields
   - Respect rate limiting (this adds extra API calls)

6. Log to sync_log with source="garmin"

Update scripts/initial_sync.py to also run the Garmin pipeline after Whoop.

Add tests in tests/test_garmin_pipeline.py that:
- Test transform with sample Garmin API response data
- Test handling of None returns from broken endpoints
- Test upsert behavior
```

**Acceptance criteria:**
- Running initial_sync.py pulls both Whoop and Garmin data
- All four Garmin tables have real data
- Activities with running dynamics have those fields populated
- Failed endpoints are logged but don't crash the sync
- sync_log shows entries for both "whoop" and "garmin"
- Tests pass

**Files touched:**
```
src/ingestion/garmin_pipeline.py
scripts/initial_sync.py (add Garmin)
tests/test_garmin_pipeline.py
```

**Estimated effort:** 1.5–2 hours

---

### Task 2.5: Scheduler Setup

**What:** Set up APScheduler to automatically poll Garmin on an interval.

**Dependencies:** Task 2.4 (Garmin pipeline works manually)

**Claude Code prompt:**
```
Add a scheduler to automatically poll Garmin for new data.

In src/ingestion/scheduler.py:
- Create a scheduler using APScheduler's BackgroundScheduler
- Add a job that runs the Garmin pipeline on an interval (default: every 15 minutes, configurable via GARMIN_POLL_INTERVAL_MINUTES)
- The job should:
  - Run an incremental sync (only fetch data since last sync)
  - Log start and completion
  - Handle errors gracefully (log and continue, don't crash the scheduler)
- Add a method to start/stop the scheduler

In src/api/main.py:
- Start the scheduler when the FastAPI app starts (use lifespan events)
- Stop the scheduler on shutdown

Make sure the scheduler doesn't run during tests (check for a TESTING env var).
```

**Acceptance criteria:**
- Start the FastAPI server and watch logs — Garmin sync runs automatically every 15 minutes
- New data appears in the database after each sync
- Stopping the server stops the scheduler cleanly
- Tests don't trigger the scheduler

**Files touched:**
```
src/ingestion/scheduler.py
src/api/main.py
config/settings.py (add GARMIN_POLL_INTERVAL_MINUTES)
```

**Estimated effort:** 45–60 minutes

---

### Task 2.6: Schema Comparison Tool

**What:** Build the side-by-side comparison tool for the Schema Unification Review Gate.

**Dependencies:** Task 2.4 (both Whoop and Garmin data exist in the database)

**Claude Code prompt:**
```
Build the schema comparison tool for manually reviewing how Whoop and Garmin data maps together.

In src/normalization/comparison_tool.py, create a function that:

1. Takes a date range (default: last 14 days)
2. For each date in the range, pulls matching data from both sources:

   Daily comparison:
   - Whoop: recovery_score, hrv_rmssd, resting_heart_rate, strain, spo2
   - Garmin: body_battery_high, body_battery_low, resting_heart_rate, avg_stress_level, avg_spo2
   - Show them side by side with column headers

   Sleep comparison:
   - Whoop: total_in_bed_ms (convert to hours), total_sws_ms, total_light_ms, total_rem_ms, total_awake_ms, sleep_performance
   - Garmin: total_sleep_seconds (convert to hours), deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds, awake_seconds, sleep_score
   - Show them side by side, both converted to minutes

   Workout comparison:
   - Find workouts from both sources on the same dates
   - Show: start_time, duration, sport_type/activity_type, avg_hr, strain, distance
   - Highlight potential matches (similar start time + duration)

3. Output as a formatted table to the terminal (use tabulate or rich library)
4. Also save as CSV files in data/review/ for spreadsheet analysis

Create scripts/schema_review.py that runs the comparison tool and prints the output.
```

**Acceptance criteria:**
- Run `python scripts/schema_review.py` and see formatted side-by-side data
- Daily metrics, sleep stages, and workouts are all compared
- CSV files generated in data/review/ that you can open in a spreadsheet
- Potential workout matches are highlighted
- You can look at this output and make informed decisions about field mappings

**Files touched:**
```
src/normalization/comparison_tool.py
scripts/schema_review.py
```

**Estimated effort:** 1–1.5 hours

---

### Task 2.7: Schema Unification Review Gate (Human Step)

**What:** YOU review the comparison output and make mapping decisions. This is not a Claude Code task — this is you analyzing data.

**Dependencies:** Task 2.6 (comparison tool output exists)

**Process:**

1. Run `python scripts/schema_review.py` and review the output carefully
2. Open the CSV files in a spreadsheet for easier analysis
3. For each metric, decide:
   - Which source is primary? (Follow the strategy: Whoop for recovery/vitals, Garmin for workout detail)
   - How do the values compare? (Are they close? Wildly different?)
   - What transformations are needed? (ms → minutes, different scales, etc.)
   - Are there fields you want to add or drop from the unified schema?
4. Document your decisions in `config/field_mappings.yaml`
5. Note any surprises or things you want to investigate further

**Acceptance criteria:**
- `config/field_mappings.yaml` exists with your reviewed mappings
- You understand why each mapping decision was made
- Any unexpected data discrepancies are documented

**Estimated effort:** 1–2 hours (this is thinking time, not coding time)

---

### Task 2.8: Normalization Layer

**What:** Build the normalization engine that reads your field_mappings.yaml and populates the unified tables.

**Dependencies:** Task 2.7 (field_mappings.yaml exists with your decisions)

**Claude Code prompt:**
```
Build the normalization layer that creates unified data from Whoop and Garmin sources.

First, add the unified tables to the database. Create src/database/migrations/003_unified_tables.py:
- unified_daily, unified_sleep, unified_workouts (schemas from our technical design doc)
- These should be created alongside existing tables

In src/normalization/normalizer.py, create a Normalizer class that:
1. Loads field_mappings.yaml at startup
2. Has methods for each unified table:
   - normalize_daily(date) — combines whoop_recovery + whoop_cycles + garmin_daily_summary
   - normalize_sleep(date) — combines whoop_sleep + garmin_sleep
   - normalize_workouts(date_range) — calls the deduplication logic

3. Each method:
   - Queries the raw source tables
   - Applies the mappings from field_mappings.yaml
   - Handles missing data (if only one source has data for a date, use what's available)
   - Upserts into the unified table
   - Records which sources contributed in the data_sources/primary_source field

In src/normalization/whoop_mapper.py and garmin_mapper.py:
- Source-specific transformation functions:
  - ms_to_minutes, seconds_to_minutes
  - Whoop sleep stage mapping (SWS -> deep)
  - HR zone calculation from zone_durations_json
  - Any other transforms identified in field_mappings.yaml

In src/normalization/deduplication.py:
- Implement workout deduplication:
  - Load unmatched Whoop workouts and Garmin activities for the date range
  - Match by start_time within 5-minute window AND duration within 15%
  - Calculate match_confidence based on time/duration closeness
  - Create unified_workout records with fields pulled from each source per field_priorities
  - Unmatched workouts get single-source unified records

Add a normalization step to both pipelines: after ingesting raw data, run the normalizer.

Add tests for:
- Mapping transforms (ms_to_minutes, etc.)
- Deduplication matching logic
- Handling of missing source data
```

**Acceptance criteria:**
- Run a full sync followed by normalization
- unified_daily has rows with data from both sources
- unified_sleep has combined sleep data
- unified_workouts has deduplicated entries with correct source attribution
- Workouts that were tracked by both devices show as matched
- Single-source workouts still appear
- Tests pass

**Files touched:**
```
src/database/migrations/003_unified_tables.py
src/database/models.py (add unified models)
src/normalization/normalizer.py
src/normalization/whoop_mapper.py
src/normalization/garmin_mapper.py
src/normalization/deduplication.py
src/ingestion/whoop_pipeline.py (add normalization call)
src/ingestion/garmin_pipeline.py (add normalization call)
tests/test_normalization.py
tests/test_deduplication.py
```

**Estimated effort:** 2–3 hours (this is the most complex task in the project)

---

### Task 2.9: CSV/JSON Manual Import

**What:** Build the fallback import path for when the garminconnect library breaks.

**Dependencies:** Task 2.8 (normalization layer exists to process imported data)

**Claude Code prompt:**
```
Build a manual CSV/JSON import tool as a fallback for Garmin data.

In src/ingestion/csv_import.py, create an importer that:

1. Accepts a directory path containing exported files
2. Supports two import formats:
   - Garmin Connect bulk export (the ZIP file you can download from Garmin, which contains JSON files)
   - Manual CSV with columns matching our garmin_* table schemas

3. For Garmin bulk export:
   - Unzip the archive
   - Parse the JSON activity files
   - Map fields to our garmin_activities schema
   - Handle the nested/inconsistent Garmin JSON format

4. For CSV import:
   - Read CSV files named like garmin_activities.csv, garmin_sleep.csv, etc.
   - Map columns to our table schemas
   - Validate data types and required fields

5. After import:
   - Upsert into the appropriate garmin_* raw tables
   - Trigger normalization for the imported date range
   - Log to sync_log with source="csv_import"

Create scripts/import_data.py as a CLI entry point:
   - Takes a path argument (file or directory)
   - Auto-detects format (ZIP, JSON directory, or CSV)
   - Prints import summary

Add basic tests for the CSV parsing and field mapping.
```

**Acceptance criteria:**
- Can import a Garmin bulk export ZIP and see data in the database
- Can import CSV files and see data in the database
- Normalization runs on imported data
- Import is logged in sync_log
- Tests pass

**Files touched:**
```
src/ingestion/csv_import.py
scripts/import_data.py
tests/test_csv_import.py
```

**Estimated effort:** 1–1.5 hours

---

### Task 2.10: Update Dashboard for Dual Sources

**What:** Extend the Streamlit dashboard to show both Whoop and Garmin data.

**Dependencies:** Task 2.8 (unified tables have data from both sources)

**Claude Code prompt:**
```
Update the Streamlit dashboard to show unified data from both Whoop and Garmin.

Modify the existing pages to read from unified tables instead of whoop_* tables:

frontend/pages/readiness.py:
- Show Whoop recovery score AND Garmin Body Battery side by side
- Show HRV trend (from Whoop)
- Show stress level trend (from Garmin)
- Add a "data source" indicator showing which sources contributed to each day

frontend/pages/sleep.py:
- Use unified_sleep table
- Show sleep stages from the unified view
- Add a toggle to show raw Whoop vs raw Garmin vs unified view
- Show both Whoop sleep performance and Garmin sleep score

frontend/pages/workouts.py:
- Use unified_workouts table
- Show both Whoop strain and Garmin training effect
- For matched workouts, show combined data (Whoop strain + Garmin distance/pace)
- Show running dynamics when available (Garmin-only fields)
- Add a column showing whether the workout was tracked by both devices

Add a new "Data Sources" page that shows:
- sync_log recent entries
- Last successful sync time for each source
- Any sync errors
```

**Acceptance criteria:**
- Dashboard shows data from both sources
- Unified views combine the best of both
- Source indicators show where data comes from
- Running dynamics appear on Garmin-tracked runs
- Data Sources page shows sync health
- Everything renders without errors

**Files touched:**
```
frontend/pages/readiness.py
frontend/pages/sleep.py
frontend/pages/workouts.py
frontend/pages/data_sources.py (new)
frontend/app.py (add new page to nav)
```

**Estimated effort:** 1.5–2 hours

---

### Task 2.11: Integration Tests and Cleanup

**What:** End-to-end tests, cleanup, and Docker update.

**Dependencies:** All Phase 2 tasks

**Claude Code prompt:**
```
Final cleanup and integration testing for Phase 2.

1. Write integration tests that verify the full pipeline:
   - Whoop fetch -> store -> normalize -> unified table
   - Garmin fetch -> store -> normalize -> unified table
   - Deduplication produces correct results for known test data
   - CSV import -> normalize works end to end

2. Update docker-compose.yml:
   - Mount the Garmin token directory (~/.garminconnect)
   - Add GARMIN env vars
   - Verify both data sources work in Docker

3. Update README with:
   - Garmin setup instructions
   - How to run the schema review tool
   - How to use the CSV import fallback

4. Update CLAUDE.md:
   - Current phase: Phase 2 complete
   - Add notes on normalization decisions
   - Update current focus to Phase 3

5. Run all tests, fix any failures
```

**Acceptance criteria:**
- All tests pass (unit + integration)
- Docker works with both data sources
- README covers full setup
- CLAUDE.md is current
- Everything committed

**Files touched:** Various — tests, Docker files, docs

**Estimated effort:** 1–1.5 hours

---

### Phase 2 Checklist

- [ ] Garmin auth works with token persistence
- [ ] All Garmin data types flow into raw tables
- [ ] Scheduler polls Garmin automatically every 15 minutes
- [ ] Schema comparison tool produces readable output
- [ ] field_mappings.yaml reflects your reviewed decisions
- [ ] Normalization populates all three unified tables
- [ ] Workout deduplication correctly matches dual-tracked workouts
- [ ] CSV import works as a fallback
- [ ] Dashboard shows unified data from both sources
- [ ] All tests pass
- [ ] Docker updated for dual sources
- [ ] Everything committed to GitHub

---

## Phase 3: Unified Dashboard (Lighter Detail)

**Goal:** Build the polished dashboard you'll use daily. Detailed task breakdown deferred until Phase 2 is complete and you have a better sense of the data.

### Planned Tasks (to be refined)

- **3.1: FastAPI endpoints** — Move dashboard data serving from direct DB queries to proper REST endpoints. This decouples frontend from database and prepares for the React migration.
- **3.2: Morning Readiness view** — Composite score algorithm, big-number display, go/no-go recommendation
- **3.3: Workout Analysis view** — HR zone charts, running dynamics display, strain-to-recovery correlation
- **3.4: Sleep Analysis view** — Dual-source comparison, stage trends, correlation with next-day recovery
- **3.5: Trends view** — Rolling averages, anomaly detection, weekly/monthly rollups
- **3.6: Whoop webhooks** — Real-time push notifications instead of polling for Whoop data
- **3.7: Error handling and logging** — Comprehensive logging, graceful degradation when a data source is down
- **3.8: Documentation** — Complete README, architecture diagram, setup guide

---

## Phase 4: Polish and Extend (Outline Only)

Detailed planning deferred until Phase 3 is complete. Potential tasks:

- React frontend scaffold (create-react-app or Vite + TypeScript)
- Rebuild each dashboard view as React components
- Predictive analytics (readiness forecasting, training load modeling)
- Deployment (VPS or Raspberry Pi with Docker)
- PWA setup for mobile access
- Content creation plan (blog posts, LinkedIn content)
