# Garmin + Whoop Training Dashboard

Personal fitness dashboard that pulls data from Garmin and Whoop into a single unified view — workouts, recovery, sleep, and training readiness in one place.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI |
| Database | PostgreSQL (Supabase) — SQLite for local dev |
| Auth | JWT (HS256, bcrypt passwords) |
| Scheduler | APScheduler (Garmin every 15 min, Whoop every 30 min) |
| Garmin API | python-garminconnect |
| Whoop API | Official REST API + OAuth 2.0 |
| Frontend | React 18 + TypeScript + Vite + TailwindCSS + Recharts |
| Hosting | Railway (backend + React) |
| Package manager (Python) | uv |
| Package manager (JS) | npm |

## Setup

**1. Clone and enter the repo**
```bash
git clone <repo-url>
cd garmin-whoop-dashboard
```

**2. Create your `.env`**
```bash
cp .env.example .env
# Required: WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, GARMIN_EMAIL, GARMIN_PASSWORD, JWT_SECRET
# Optional: DATABASE_URL (defaults to SQLite; set to PostgreSQL URL for prod-parity)
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

Two options:

*Option A — React dev server (hot reload, recommended for development):*
```bash
# Terminal 1
make run-api                      # FastAPI on port 8000

# Terminal 2
cd frontend-react && npm run dev  # Vite dev server on port 5173
# Open http://localhost:5173
```

*Option B — Serve built React from FastAPI (production-like):*
```bash
cd frontend-react && npm run build
make run-api
# Open http://localhost:8000
```

Common commands: `make test`, `make lint`, `make fmt`

```bash
# Frontend-specific
cd frontend-react
npm run dev        # start dev server
npm run build      # production build → dist/
npm run typecheck  # TypeScript check only
```

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

**2. Build and start**

The multi-stage Docker build compiles the React frontend and serves it from FastAPI — single container, single port.

```bash
docker compose up --build
```

- Dashboard + API: http://localhost:8000
- API docs: http://localhost:8000/docs

**3. Authenticate with Whoop** (first run only)

Visit `http://localhost:8000/api/auth/whoop` to complete the OAuth flow.

**4. Run the initial sync**
```bash
docker compose exec backend python scripts/initial_sync.py
```

For Garmin 2FA, run the above interactively — the prompt will appear in your terminal.

**Garmin token persistence in Docker**: Garmin tokens are stored in `GARMIN_TOKEN_DIR`
(default `data/garmin_tokens/`). Since `./data` is mounted as a volume, tokens persist
across restarts with no extra configuration.

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
  api/            # FastAPI routes + SPA static file serving
  auth/           # JWT auth: models, schemas, security, dependencies
  clients/        # Garmin and Whoop API clients
  ingestion/      # Fetch → transform → store pipelines + CSV importer
  normalization/  # Unified data models (normalizer, mappers, deduplication)
  database/       # SQLAlchemy models and migrations (001–006)
  analytics/      # readiness_score, workout_analysis, sleep_analysis, trends
frontend-react/   # React 18 + TypeScript + Vite frontend
  src/
    pages/        # Readiness, Workouts, Sleep, Trends, Settings, RecoveryActivities
    components/   # MetricCard, WorkoutRow, SleepStageBar, TrendChart, …
    hooks/        # TanStack Query hooks (useApi.ts)
    api/          # Typed fetch wrapper (client.ts)
  dist/           # Production build output (served by FastAPI at /)
frontend/
  app.py          # Legacy Streamlit dashboard (kept for reference)
config/
  settings.py     # All env vars loaded via python-dotenv
  field_mappings.yaml  # Whoop↔Garmin field alignment decisions
scripts/
  initial_sync.py      # Full sync: Whoop (async) then Garmin (sync)
  import_data.py       # Bulk CSV/ZIP import with auto-format detection
  schema_review.py     # Side-by-side data comparison tool
tests/            # pytest (503 tests, unit + integration)
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

**Phase 3 complete** — Analytics engine + full dashboard:
- Composite readiness score (5 components, weight redistribution for missing sources)
- Enriched workout analysis (Whoop + Garmin merged, strain/efficiency/recovery metrics)
- Sleep impact analysis (stage breakdown, consistency, training↔sleep correlations)
- Trends view (rolling averages, anomaly detection, week-over-week comparison, Pearson heatmap)
- REST API: 16 endpoints, Pydantic models, auto-docs at `/docs`
- Whoop webhook receiver (`POST /api/webhooks/whoop`) with BackgroundTask processing
- Structured logging via `LOG_LEVEL` env var; sidebar sync-age indicator; per-view error handling

**Phase 4 complete** — React frontend:
- React 18 + TypeScript + Vite + TailwindCSS + TanStack Query + Recharts
- Pages: Readiness, Workouts (running + strength sections), Sleep, Trends, Settings, Recovery Activities
- PWA: installable on iOS/Android, offline banner, service worker caching
- Mobile-optimised: thumb-friendly nav, responsive charts, no horizontal scroll
- Production build served directly from FastAPI (single container, single port)
- Multi-stage Docker build: Node.js compiles React, Python image copies `dist/`

**Phase 5 in progress** — Production infrastructure (tasks 5.1–5.9 complete):
- PostgreSQL on Supabase; SQLite retained for local dev
- JWT authentication (bcrypt + HS256); all routes protected; user-scoped data
- Deployed to Railway — auto-deploys on push to `main`; always-on 24/7
- Background sync: Garmin every 15 min, Whoop every 30 min via APScheduler
- Whoop OAuth redirect URI updated for production URL
- Custom domain: **https://pulsebuilt.net** (Cloudflare Registrar + DNS, Railway TLS)

---

## Production URLs

| Service | URL |
|---|---|
| Dashboard | https://pulsebuilt.net |
| API docs | https://pulsebuilt.net/docs |
| Health check | https://pulsebuilt.net/health |
| Railway (origin) | https://garmin-whoop-dashboard-production.up.railway.app |

### Domain setup

The domain `pulsebuilt.net` is registered on Cloudflare Registrar with DNS managed by Cloudflare.
Railway's one-click DNS setup adds the required CNAME and TXT verification records automatically.
TLS is provisioned by Railway (Let's Encrypt). Cloudflare SSL/TLS mode is set to **Full**.

### Key env vars for production (set in Railway dashboard)

| Variable | Description |
|---|---|
| `DATABASE_URL` | Supabase PostgreSQL pooler connection string |
| `JWT_SECRET` | Long random string for HS256 token signing |
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | Whoop OAuth app credentials |
| `WHOOP_REDIRECT_URI` | `https://pulsebuilt.net/api/auth/whoop/callback` |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Garmin Connect credentials |
| `CORS_ORIGINS` | Comma-separated allowed origins (e.g. `https://pulsebuilt.net`) |
| `PORT` | Set automatically by Railway |

---

## REST API

The FastAPI backend exposes a complete REST API. Visit `http://localhost:8000/docs` for interactive documentation.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Create a user account |
| `POST` | `/api/auth/login` | Login — returns JWT access + refresh tokens |
| `POST` | `/api/auth/refresh` | Exchange refresh token for new access token |
| `GET` | `/api/auth/me` | Current user info (protected) |
| `GET` | `/api/readiness/today` | Today's composite readiness score |
| `GET` | `/api/readiness/history?start&end` | Daily readiness history for a date range |
| `GET` | `/api/workouts?start&end` | Enriched workout list |
| `GET` | `/api/workouts/summary?start&end` | Per-type workout stats |
| `GET` | `/api/workouts/{id}` | Single enriched workout |
| `GET` | `/api/sleep/insights?start&end` | Nightly sleep insights |
| `GET` | `/api/sleep/correlations?days&end` | Strain vs sleep/recovery Pearson r |
| `GET` | `/api/sleep/consistency?days&end` | Bedtime variance and debt trend |
| `GET` | `/api/trends/{metric}?start&end` | Rolling averages + anomalies for a metric |
| `GET` | `/api/trends/weekly-summary?end` | This-week vs last-week comparison |
| `GET` | `/api/trends/anomalies?start&end` | Anomaly log across all metrics |
| `GET` | `/api/sync/status` | Last sync timestamp per source |
| `POST` | `/api/sync/trigger/{source}` | Trigger a 30-day sync (whoop or garmin) |
| `GET` | `/api/webhooks/whoop/test` | Webhook health check (for Whoop verification) |
| `POST` | `/api/webhooks/whoop` | Receive Whoop real-time events |
| `GET` | `/health` | Basic health check |

---

## Whoop Webhooks

Whoop can push real-time updates whenever a cycle, recovery, sleep, or workout record changes. This eliminates the need to poll for fresh data.

### How it works

| Step | Detail |
|---|---|
| Endpoint | `POST /api/webhooks/whoop` |
| Health check | `GET /api/webhooks/whoop/test` → must return `{"status":"ok"}` |
| Supported events | `cycle.updated`, `recovery.updated`, `sleep.updated`, `workout.updated` |
| Response | Always `200 OK` immediately; processing is async (BackgroundTask) |
| Idempotency | Upsert-safe — duplicate webhooks for the same resource are harmless |
| Audit trail | Each event is logged to `sync_log` with `source="whoop_webhook"` |

### Local development with ngrok

Whoop's servers must be able to reach your webhook URL, so localhost won't work directly. Use [ngrok](https://ngrok.com) (or any tunneling tool) to expose your local API:

```bash
# 1. Install ngrok
brew install ngrok   # macOS
# or: https://ngrok.com/download

# 2. Start your API server
make run-api         # FastAPI on http://localhost:8000

# 3. Open a public tunnel in a second terminal
ngrok http 8000
# ngrok prints something like:
#   Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000

# 4. Register the webhook in Whoop Developer Dashboard
#    URL: https://abc123.ngrok-free.app/api/webhooks/whoop
#    Whoop will GET /api/webhooks/whoop/test to verify — it must return 200.
```

### Registering in Whoop Developer Dashboard

1. Go to [developer.whoop.com](https://developer.whoop.com) and log in.
2. Open your application → **Webhooks** tab.
3. Click **Add Webhook URL**.
4. Enter your public URL: `https://<your-domain>/api/webhooks/whoop`
5. Select the event types to subscribe to (all four recommended).
6. Whoop sends a GET to `/api/webhooks/whoop/test` — confirm it returns `200 OK`.
7. Save. Whoop will now push events in real time.

### Production deployment

For a stable always-on webhook URL, deploy the FastAPI backend to any host with a public IP (Fly.io, Railway, a VPS, etc.) and register that URL in the Whoop Dashboard instead of an ngrok tunnel.

> **Security note:** The current implementation does not verify Whoop's HMAC signature on incoming payloads. For a public-facing production deployment, add signature verification using the secret Whoop provides in the Developer Dashboard.
