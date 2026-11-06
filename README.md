# Garmin + Whoop Dashboard (PulseEngine)

A personal dashboard that merges Garmin and Whoop data into one view: a composite
**readiness** score, **training load** (ACWR), **sleep and recovery** breakdowns, and
**insights** (metric explorer, correlations, anomalies, weekly digest). Single user,
self-hosted. Stack: FastAPI + SQLAlchemy (SQLite by default) + React 18 / TypeScript / Vite /
Tailwind / Recharts.

This README is internal documentation for the owner (SJ) and Claude agents.

> **Status: relaunch in progress (Nov 2026).** **Phase 2 is done** (branch
> `feat/garmin-personal-api`, 2026-11-06): Garmin now comes from the official Personal API, and
> the unofficial `garminconnect` password login is gone. **The SaaS cut (roadmap Phases 3-4) is
> still pending**: the landing page and the other SaaS-era frontend pages still exist.
> Plan: [`plans/2026-11-06-personal-relaunch-roadmap.md`](plans/2026-11-06-personal-relaunch-roadmap.md).
> Research: [`docs/research/2026-11-garmin-personal-api.md`](docs/research/2026-11-garmin-personal-api.md).
> Sections below are marked **(current code)** or **(after relaunch)**.

## How it works

```
Whoop REST API (OAuth 2.0) ─┐                                   ┌─► FastAPI /api/* ─► React
                            ├─► ingestion pipelines ─► raw_json │
Garmin (see below) ─────────┘   (raw whoop_* / garmin_* tables) ├─► analytics (readiness, ACWR,
                                         │                      │   sleep, trends, digest)
                                         ▼                      │
                          normalization + dedup ─► unified_daily / unified_sleep / unified_workouts
```

- **Whoop is the source of truth** for recovery, sleep, and body vitals. **Garmin is the source of
  truth** for workout detail and running dynamics. Matching Whoop/Garmin workouts are deduplicated
  by start time (within 5 min) and duration (within 20%).
- Raw API responses are kept in a `raw_json` column for reprocessing.
- A background scheduler (APScheduler) does incremental syncs from the last `sync_log` entry:
  Whoop and Garmin every 30 min (`GARMIN_POLL_INTERVAL_MINUTES`), for the single owner.
- Pages: Today `/`, Training `/training`, Recovery `/recovery`, Insights `/insights`, Settings `/settings`.

```
src/
  analytics/      readiness, training load/ACWR, sleep, trends, weekly digest, anomaly cache
  api/            FastAPI app (main.py) + routes/; serves frontend-react/dist when built
  auth/           JWT auth, password hashing
  clients/        whoop_auth/whoop_client, garmin_personal_auth/garmin_client (Personal API)
  database/       SQLAlchemy models, connection, migrations/ (001-014)
  ingestion/      whoop/garmin pipelines, scheduler, Garmin CSV/ZIP importers
  normalization/  mappers, deduplication, normalizer
config/           settings.py (env vars), field_mappings.yaml
frontend-react/   React app (src/pages, components, hooks/useApi.ts)
scripts/          initial_sync.py, import_data.py, schema_review.py, start.sh, ...
landing/          pulsebuilt.net studio page (not part of the dashboard; leave alone)
tests/            pytest suite
```

## Running it locally (current code)

Prerequisites: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node 20+. A fresh checkout has
no `.venv` or `node_modules`; the Makefile expects `.venv/`.

```bash
uv sync                          # creates .venv, installs deps (incl. dev group)
cd frontend-react && npm ci && cd ..
cp .env.example .env
```

Edit `.env`; these matter locally:

| Var | Value |
|---|---|
| `DATABASE_URL` | `sqlite:///data/fitness_dashboard.db` (default) |
| `JWT_SECRET` | required, even locally: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET` | from your Whoop app (see Whoop below) |
| `WHOOP_REDIRECT_URI` | `http://localhost:8000/api/auth/whoop/callback` |
| `GARMIN_PERSONAL_API_KEY` | Garmin Personal API key (see Garmin data below); optional `GARMIN_PERSONAL_API_BASE_URL` |
| `GARMIN_POLL_INTERVAL_MINUTES` | optional, default 30 |

Without a Garmin key the app still runs; Garmin data then comes only from the export import.

Two terminals (migrations run automatically on API startup):

```bash
make run-api                      # FastAPI on :8000 (docs at /docs)
cd frontend-react && npm run dev  # Vite on :5173 (proxies /api to :8000)
```

Open http://localhost:5173. **Register an account at `/login`** (open registration still exists;
Phase 3 replaces it with `scripts/create_owner.py`). Register exactly one account: with a second
user, background syncs stop and the Garmin owner check fails, then **Settings -> connect Whoop**
(OAuth). To serve the built app from FastAPI instead: `cd frontend-react && npm run build`, then
`make run-api` and open http://localhost:8000.

Initial Whoop backfill: Settings -> Sync Now, or `make run-sync` (runs `scripts/initial_sync.py`).

## Garmin data

Garmin data comes from Garmin's official **Personal API** (implemented, Phase 2). Create a key at
<https://connect.garmin.com/app/settings/personalApiToken> (pick 365 days; shown once) and put it
in `.env` as `GARMIN_PERSONAL_API_KEY`. The app exchanges it for a 24 h token itself
(`src/clients/garmin_personal_auth.py`) and polls through `src/clients/garmin_client.py`
(`https://personal.connectapi.garmin.com`, 1 s between calls). Settings shows the key status:
Connected / Key not set / Key rejected / Can't reach Garmin. Manual sync
(`POST /api/sync/trigger/garmin`) is owner-only.

- Any Garmin failure (bad key, 429, 5xx, bad response) ends the run as `error` without advancing
  the sync window; the next run re-pulls, with a 2-day overlap.
- **History depth:** daily summaries reach about 180 days back, activities about 690 days. VO2 max
  is not provided by the API, so that chart gets no new points. Training load, training effect,
  HR zones and running dynamics are present.
- Sleep and HRV come back empty on nights the watch isn't worn, so those tables are normally empty.
- Strength: no per-set endpoint. Per-exercise summaries land in `garmin_exercise_summaries`;
  older set-level rows from an export still win when present.

**Backfill past ~180 days: Garmin export import.** Garmin Connect -> Settings -> Data Management ->
Export Your Data (ZIP), or Activities -> Export CSV.

```bash
.venv/bin/python scripts/import_data.py ~/Downloads/garmin_export.zip   # ZIP, dir, .csv or .json
.venv/bin/python scripts/import_data.py export.zip --dry-run            # detect format only
.venv/bin/python scripts/import_data.py export.zip --no-normalize       # raw tables only
```

Or upload in the UI (Settings / Connect Devices panel -> `POST /api/garmin/upload`, CSV/JSON/ZIP,
50 MB limit, `units` = miles|km for CSVs). Re-imports are idempotent. Normalization runs after
import and fills the unified tables.

## Whoop

1. Create an app at <https://developer.whoop.com>. New apps start on the Sandbox tier (10 members),
   which is enough for one person.
2. Redirect URI: `http://localhost:8000/api/auth/whoop/callback` (must match `WHOOP_REDIRECT_URI`).
3. Scopes requested by the code: `read:recovery`, `read:cycles`, `read:workout`, `read:sleep`,
   `read:body_measurement`, `read:profile`, `offline` (needed for refresh tokens).
4. Data is polled every 30 min. Refresh tokens rotate; a known bug can force re-auth (fix planned
   in roadmap Phase 3).

Whoop data is polling only (no webhooks); do not set up ngrok.

## Common commands

| Command | Does |
|---|---|
| `make run-api` | FastAPI on :8000 with reload |
| `make run-sync` | `scripts/initial_sync.py` (Whoop, then Garmin) |
| `make test` | `pytest tests/ -v` |
| `make lint` / `make fmt` | `ruff check .` / `ruff format .` |
| `cd frontend-react && npm run dev` | Vite dev server, :5173 |
| `cd frontend-react && npm run typecheck` | `tsc --noEmit` |
| `cd frontend-react && npm run build` | typecheck + production build to `dist/` |
| `.venv/bin/python scripts/schema_review.py --days 14` | side-by-side Whoop/Garmin review; CSVs to `data/review/` |

## Deployment

`Dockerfile` is multi-stage (Node builds React, Python 3.11 runs FastAPI and serves `dist/`),
single container on port 8000. `docker-compose.yml` runs it with `.env` and mounts `./data` (SQLite)
and `./config`:

```bash
docker compose up --build        # http://localhost:8000
```

**It runs locally only.** The old Railway + Supabase deployment (engine.pulsebuilt.net) is gone:
Railway is shut down, and the Supabase project and its data were deleted. History gets
re-pulled from the APIs (roadmap Phase 6). `railway.toml` and `frontend-react/vercel.json` are
leftovers that Phase 5 deletes.

## Docs map

- `CLAUDE.md`: agent context (some SaaS-era content is stale until the Phase 7 docs pass)
- `plans/`: relaunch roadmap and per-phase plans
- `docs/research/`: Garmin Personal API and Whoop research
- `docs/reference/garmin-personal-api-openapi.json`: vendored Garmin Personal API spec
- `docs/history/`: archived SaaS-era docs (optimization audit, frontend design review, build log)

## Data and secrets

This is personal health data. Never commit `.env`, tokens, API keys, DB files, or Garmin/Whoop
exports. `data/` is gitignored (database, review CSVs, token cache); so are Garmin CSV exports.
Check `git status` before every commit.
