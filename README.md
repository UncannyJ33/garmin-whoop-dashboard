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

**4. Run the backend**
```bash
uvicorn src.api.main:app --reload --port 8000
```

**5. Run the dashboard**
```bash
streamlit run frontend/app.py
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
  pages/          # Streamlit pages
  components/     # Reusable Streamlit components
config/
  settings.py     # All env vars loaded via python-dotenv
tests/            # pytest
```

## Status

**Phase 1 in progress — Whoop Proof of Concept**

Goal: display last 30 days of Whoop recovery, sleep, and strain data in Streamlit.
Garmin integration follows in Phase 2.
