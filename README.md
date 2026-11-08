# Garmin + Whoop Dashboard (PulseEngine)

A personal dashboard that merges Garmin and Whoop data into one view: a composite
**readiness** score, **training load** (ACWR), **sleep and recovery** breakdowns, and
**insights** (metric explorer, correlations, anomalies, weekly digest). Single user,
self-hosted. Stack: FastAPI + SQLAlchemy (SQLite by default) + React 18 / TypeScript / Vite /
Tailwind / Recharts.

This README is internal documentation for the owner (SJ) and Claude agents.

> **Status: relaunch complete (2026-11-07).** Garmin comes from the official Personal API, the
> SaaS surface is gone, and it runs locally with SQLite. Plan:
> [`plans/2026-11-06-personal-relaunch-roadmap.md`](plans/2026-11-06-personal-relaunch-roadmap.md).
> Research: [`docs/research/2026-11-garmin-personal-api.md`](docs/research/2026-11-garmin-personal-api.md).

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
scripts/          create_owner.py, backfill.py, initial_sync.py, import_data.py, schema_review.py, start.sh, ...
landing/          pulsebuilt.net studio page (not part of the dashboard; leave alone)
tests/            pytest suite
```

## Getting started

1. Install tools: `brew install uv`, plus Node 20+.
2. `uv sync`, then `cp .env.example .env` and fill in `JWT_SECRET`
   (`python -c "import secrets; print(secrets.token_hex(32))"`), `WHOOP_CLIENT_ID`,
   `WHOOP_CLIENT_SECRET` and `GARMIN_PERSONAL_API_KEY` (see Garmin data and Whoop below).
3. Create the single owner account: `make owner EMAIL=you@example.com` (prompts for a password;
   registration is closed).
4. `make run`, then open <http://localhost:8000> and log in. It builds the frontend only when
   sources changed, and binds to `127.0.0.1`. Use `localhost` consistently: the Whoop callback
   lands there, and the login lives in per-origin `localStorage`, so `127.0.0.1` is a separate,
   logged-out session.
5. Settings -> Connect Whoop. `http://localhost:8000/api/auth/whoop/callback` must be registered in
   the Whoop developer dashboard and match `WHOOP_REDIRECT_URI`.
6. **Stop the server (Ctrl-C)**, then backfill history: `make backfill START=2024-11-01`
   (optional `SOURCE=garmin|whoop`, default `all`; `CHUNK_DAYS=`).
   - Chunks run oldest first and end today (no `--end`). It refuses (exit 3) while this
     dashboard's API is running, and uses `caffeinate` on macOS.
   - Garmin daily data reaches only about 180-365 days back; activities about 690 days. Older
     Garmin data comes from an account export via `scripts/import_data.py` (see below).
   - Expect about 40 min for 2 years. If it stops, run the printed resume command
     (`make backfill SOURCE=x START=y`) **before** restarting the server.
   - Exit codes: 0 done, 1 error, 2 usage, 3 API running, 130 interrupted.
7. `make run` again. The scheduler then keeps both sources current.

**Ports.** If 8000 is taken (`make run` refuses with a hint), use `make run PORT=8001`, and set
`WHOOP_REDIRECT_URI=http://localhost:8001/api/auth/whoop/callback` in `.env` and in the Whoop
developer dashboard. Pass the same `PORT=` to `make backfill`.

**Development.** `make dev` (API on :8000 with reload) plus `cd frontend-react && npm run dev`
(Vite on :5173, proxies `/api`); open <http://localhost:5173>.

**Optional: Docker Compose.** `make up` / `make down` run the container, published on
`127.0.0.1:8000` only, using `.env` and `./data`. The Docker build is not verified yet.

**Optional: remote access.** `tailscale serve 8000` keeps the localhost bind. `make run
BIND_HOST=0.0.0.0` exposes it to the LAN (opt-in; use `BIND_HOST`, not `HOST`, because zsh sets
`HOST` to the hostname).

Troubleshooting: "Port in use" -> `PORT=` above. Whoop "needs reconnect" -> Settings -> Connect
Whoop. Backfill exit 3 -> stop the server first. Garmin "Key rejected" -> create a new key.

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
2. Redirect URI: `http://localhost:8000/api/auth/whoop/callback` (must match `WHOOP_REDIRECT_URI`; change both if you use another port).
3. Scopes requested by the code: `read:recovery`, `read:cycles`, `read:workout`, `read:sleep`,
   `read:body_measurement`, `read:profile`, `offline` (needed for refresh tokens).
4. Data is polled every 30 min. Refresh tokens rotate; a known bug can force re-auth (fix planned
   in roadmap Phase 3).

Whoop data is polling only (no webhooks); do not set up ngrok.

## Common commands

| Command | Does |
|---|---|
| `make run` | build frontend if changed, serve on `BIND_HOST:PORT` (127.0.0.1:8000) |
| `make dev` (alias `run-api`) | FastAPI with reload, for `npm run dev` |
| `make build-frontend` | production React build to `dist/` |
| `make owner EMAIL=...` | create the single owner |
| `make backfill START=YYYY-MM-DD` | chunked history backfill (server stopped) |
| `make run-sync` | `scripts/initial_sync.py` (Whoop, then Garmin, 30 days) |
| `make up` / `make down` | Docker Compose |
| `make test` | `pytest -q` (972 pass, serial; xdist is broken) |
| `make lint` / `make fmt` | `ruff check .` / `ruff format .` |
| `cd frontend-react && npm run typecheck` | `tsc --noEmit` |
| `.venv/bin/python scripts/schema_review.py --days 14` | side-by-side Whoop/Garmin review; CSVs to `data/review/` |

## Deployment

It runs locally only. The old Railway + Supabase deployment is gone, and its data was deleted.
`Dockerfile` is multi-stage (Node builds React, Python runs FastAPI and serves `dist/`);
`docker-compose.yml` is the optional way to run it (see Getting started).

## Docs map

- `CLAUDE.md`: agent context (architecture, decisions, open items)
- `plans/`: relaunch roadmap and per-phase plans
- `docs/research/`: Garmin Personal API and Whoop research
- `docs/reference/garmin-personal-api-openapi.json`: vendored Garmin Personal API spec
- `docs/history/`: archived SaaS-era docs (optimization audit, frontend design review, build log)

## Data and secrets

This is personal health data. Never commit `.env`, tokens, API keys, DB files, or Garmin/Whoop
exports. `data/` is gitignored (database, review CSVs, token cache); so are Garmin CSV exports.
Check `git status` before every commit.
