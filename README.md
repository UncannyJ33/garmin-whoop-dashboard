# Garmin + Whoop Training Dashboard

Personal fitness dashboard that pulls data from Garmin and Whoop into a single unified view — workouts, recovery, sleep, and training readiness in one place.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI |
| Database | SQLite (PostgreSQL upgrade path) |
| Scheduler | APScheduler (Garmin polling) |
| Garmin API | python-garminconnect |
| Whoop API | Official REST API + OAuth 2.0 |
| Frontend | Streamlit (React in a later phase) |
| Package manager | uv |

## Setup

**1. Clone and enter the repo**
```bash
git clone <repo-url>
cd garmin-whoop-dashboard
```

**2. Create your `.env`**
```bash
cp .env.example .env
# Fill in WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, GARMIN_EMAIL, GARMIN_PASSWORD
```

**3. Create the virtual environment and install dependencies**
```bash
uv venv --seed
source .venv/bin/activate
uv sync
```

**4. Authenticate with Whoop** (first run only)
```bash
make run-api        # starts FastAPI on port 8000
# visit http://localhost:8000/api/auth/whoop in your browser to complete OAuth
```

**5. Run the initial sync** (pulls 30 days of data from both sources)
```bash
make run-sync
```

Garmin credentials are read from `.env`. After the first successful login, tokens are
cached in `data/garmin_tokens/` and re-used on subsequent syncs — your password is not
stored.

**6. Run the dashboard**
```bash
make run-frontend
```

Common commands: `make test`, `make lint`, `make fmt`

---

## Garmin Setup

Garmin authentication uses your Garmin Connect email and password. Set them in `.env`:

```env
GARMIN_EMAIL=your@email.com
GARMIN_PASSWORD=yourpassword
GARMIN_TOKEN_DIR=data/garmin_tokens   # default; tokens cached here after first login
```

**Two-factor authentication**: If your account uses 2FA, the first login will prompt
for a code on the terminal. Run `python scripts/initial_sync.py` interactively (not via
`make`) so you can enter the code. Subsequent syncs use the cached token and do not
need 2FA.

**Rate limits**: The Garmin API rate-limits aggressively. The client enforces a 1.5-second
delay between calls. Initial syncs covering many days may take a few minutes — this is
expected. A 429 response triggers a 60-second back-off and one retry.

---

## Docker Setup

**1. Create your `.env`** (include both Whoop and Garmin credentials)
```bash
cp .env.example .env
```

**2. Build and start both services**
```bash
docker compose up --build
```

- FastAPI backend: http://localhost:8000
- Streamlit frontend: http://localhost:8501

**3. Authenticate with Whoop** (first run only)

Visit `http://localhost:8000/api/auth/whoop` to complete the OAuth flow.

**4. Run the initial sync**
```bash
docker compose exec backend python scripts/initial_sync.py
```

For Garmin 2FA, run the above interactively — the prompt will appear in your terminal.

**Garmin token persistence in Docker**: Garmin tokens are stored in `GARMIN_TOKEN_DIR`
(default `data/garmin_tokens/`). Since `./data` is already mounted into both containers,
tokens persist across restarts with no extra configuration. If you prefer to use tokens
from a host path outside `data/`, edit the volume comment in `docker-compose.yml`.

**Volumes:** `data/` persists the SQLite database and Garmin tokens. `config/` allows
live config edits without rebuilding.

**Stopping:**
```bash
docker compose down        # stop containers (data persists)
docker compose down -v     # stop and remove volumes (deletes database)
```

---

## Importing Garmin Data from Bulk Export (CSV / ZIP)

If the live Garmin API is unavailable or you want to backfill historical data, you can
import from a Garmin Connect bulk export or manually prepared CSV files.

**Download your export**: Garmin Connect → Settings → Data Management → Export Your Data.
This produces a ZIP archive.

**Import**:
```bash
# Auto-detect format and import (updates unified tables automatically)
python scripts/import_data.py ~/Downloads/garmin_export.zip

# Import a single CSV file
python scripts/import_data.py data/manual/garmin_activities.csv

# Import without updating unified tables (faster, raw tables only)
python scripts/import_data.py export.zip --no-normalize

# Dry run: detect format and show what would be imported without writing
python scripts/import_data.py export.zip --dry-run
```

Supported formats detected automatically:
- `.zip` — Garmin Connect full export archive
- Directory with `.json` files — extracted export or API dump
- Directory with CSV files named `garmin_activities.csv`, `garmin_daily_summary.csv`, etc.
- Single `.csv` or `.json` file

After import, the normalization layer runs automatically and populates `unified_daily`,
`unified_sleep`, and `unified_workouts`.

---

## Schema Review Tool

The schema review tool shows side-by-side Whoop and Garmin data for a date range,
helping diagnose alignment issues and verify the normalization output.

```bash
# Review last 14 days (default)
python scripts/schema_review.py

# Review a custom range
python scripts/schema_review.py --days 30
python scripts/schema_review.py --start 2024-01-01 --end 2024-01-31
```

Output includes tabulated DataFrames for daily recovery, sleep, and workout matching.
CSVs are saved to `data/review/` (gitignored — contains personal health data).

---

## Project Structure

```
src/
  api/            # FastAPI routes
  clients/        # Garmin and Whoop API clients
  ingestion/      # Fetch → transform → store pipelines + CSV importer
  normalization/  # Unified data models (normalizer, mappers, deduplication)
  database/       # SQLAlchemy models and migrations (001, 002, 003)
  analytics/      # Computed metrics and trend logic (future)
frontend/
  app.py          # Streamlit entry point (Recovery, Sleep, Activities, Data Sources)
  views/          # Streamlit page modules
config/
  settings.py     # All env vars loaded via python-dotenv
  field_mappings.yaml  # Whoop↔Garmin field alignment decisions
scripts/
  initial_sync.py      # Full sync: Whoop (async) then Garmin (sync)
  import_data.py       # Bulk CSV/ZIP import with auto-format detection
  schema_review.py     # Side-by-side data comparison tool
tests/            # pytest (unit + integration)
```

---

## Status

**Phase 1 complete** — Whoop integration: recovery, sleep, and workout data in Streamlit dashboard.

**Phase 2 complete** — Garmin integration:
- GarminAuth with token caching via garth
- GarminClient with rate limiting and per-method error handling
- Four Garmin raw tables (activities, daily summary, sleep, HRV)
- Normalization layer: unified_daily, unified_sleep, unified_workouts
- Cross-source workout deduplication (time + duration window matching)
- CSV / ZIP bulk import fallback
- Dashboard updated to read from unified tables (Body Battery, Stress, Running Dynamics, Data Sources page)

**Phase 3** — Enhanced dashboard views and analytics.
