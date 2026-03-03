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
# Fill in WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET
```

**3. Create the virtual environment and install dependencies**
```bash
uv venv --seed
source .venv/bin/activate
uv sync
```

**4. Run the initial Whoop sync** (requires completing the OAuth flow at `http://localhost:8000/api/auth/whoop` first)
```bash
make run-api        # starts FastAPI, then visit the auth URL in your browser
make run-sync       # once authenticated, pull 30 days of Whoop data
```

**5. Run the dashboard**
```bash
make run-frontend
```

Common commands: `make test`, `make lint`, `make fmt`

## Docker Setup

**1. Create your `.env`**
```bash
cp .env.example .env
# Fill in WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET
```

**2. Build and start both services**
```bash
docker compose up --build
```

- FastAPI backend: http://localhost:8000
- Streamlit frontend: http://localhost:8501

**3. Authenticate with Whoop** (first run only)

Visit `http://localhost:8000/api/auth/whoop` in your browser to complete the OAuth flow.

**4. Run the initial sync**
```bash
docker compose exec backend python scripts/initial_sync.py
```

**Volumes:** `data/` is mounted into both containers so the SQLite database persists across restarts. `config/` is mounted into the backend container to allow live config edits without rebuilding.

**Stopping:**
```bash
docker compose down        # stop containers (data persists)
docker compose down -v     # stop and remove volumes (deletes database)
```

## Project Structure

```
src/
  api/            # FastAPI routes
  clients/        # Garmin and Whoop API clients
  ingestion/      # Fetch → transform → store pipelines
  normalization/  # Unified data models across sources
  database/       # SQLAlchemy models and session management
  analytics/      # Computed metrics and trend logic
frontend/
  views/          # Streamlit page modules (readiness, sleep, activities)
  components/     # Reusable Streamlit components
config/
  settings.py     # All env vars loaded via python-dotenv
tests/            # pytest
```

## Status

**Phase 1 complete — Whoop Proof of Concept**

30 days of Whoop recovery, sleep, and activity data visible in the Streamlit dashboard.
Phase 2 adds Garmin integration.
