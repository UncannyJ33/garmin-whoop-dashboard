# Phases 5–6: Local Run, Dependency Refresh, Backfill Tooling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Make the dashboard easy to run on SJ's Mac. `make run` builds the frontend and serves everything on `http://127.0.0.1:8000`. Docker Compose stays available as an option.
- Refresh dependencies within their current major versions.
- Ship `make backfill` to pull history from scratch.
- Do the final docs pass.

**Architecture:**
- **Default path, no Docker:** uv/venv plus `npm run build`, served by uvicorn with `--host 127.0.0.1`.
- **Optional path:** `docker compose up`, with the port published on `127.0.0.1` only.
- **Backfill:** a new `scripts/backfill.py` that runs the existing pipelines over explicit date ranges in chunks, oldest first. It then refreshes the anomaly cache over the full range.

**Tech Stack:** Python 3.12 (uv), FastAPI, SQLAlchemy, APScheduler, React 18 + Vite 5, Docker (optional; **not installed on the dev machine**, so Docker changes are statically checked only).

**Spec:**
- [`plans/2026-11-06-personal-relaunch-roadmap.md`](2026-11-06-personal-relaunch-roadmap.md), Phases 5, 6 and 7. Q1 = local only; Q2 = start from scratch.
- Live API limits from `docs/research/2026-11-garmin-personal-api.md` §9:
  - Garmin daily summaries were populated at 180 days and empty (200, all null) at 365 days, so depth is somewhere in 180–365 days and may be account-specific. Activities go back at least ~690 days. Sleep returns the all-null DTO even ~730 days back; HRV returns 204.
  - Garmin sleep, HRV and body-battery **range** endpoints are capped at 31 days (§3). The pipeline doesn't use them today (it calls the per-day `dailySleep?date=` and `hrv/{date}`), so the ≤31-day chunk clamp is roadmap hygiene, not a live constraint.
  - Garmin rate limits are undocumented. The spike made only ~70 calls at 1 call/s; a 2-year backfill is ~2,200 calls, so a 429 mid-run is plausible and the resume path matters.
  - Whoop allows 100 requests/min.

## Global Constraints

- Branch `feat/phase5-6-local-run` from `main` (b45acac). Baseline: **952 passed** (serial `.venv/bin/pytest -q`; xdist is broken). `make lint` must stay clean. Frontend `npm run typecheck && npm run build` must stay clean.
- **Bind to localhost by default** (controller ruling). The app holds health data and OAuth tokens. LAN exposure has to be an explicit opt-in (`make run BIND_HOST=0.0.0.0`). The variable is `BIND_HOST`, not `HOST`: zsh sets a `HOST` parameter to the machine's hostname, and a dotfile that exports it would silently make `HOST ?= 127.0.0.1` bind to the LAN-resolvable hostname. For remote access, document `tailscale serve 8000` (roadmap 5.7), which proxies to the localhost bind.
- Don't change the runtime behaviour of the API, pipelines or analytics, except where a task says so.
- Dependency upgrades stay within current major versions:
  - No React 19, Vite 6/7, Tailwind 4, Recharts 3 or react-router 7 (D7).
  - No FastAPI, SQLAlchemy or Pydantic major bumps.
  - Use `npm audit fix` without `--force`.
- Settled decisions still bind:
  - single owner (D1)
  - polling only (D3)
  - the Garmin failure policy
  - `_RUN_LOCK`
  - the incremental overlaps
  - the owner-only scheduler
- No secrets or personal data in git. The backfill must never print tokens or keys.
- Repo code-quality rules: surgical changes, never swallow errors, type hints and docstrings, `datetime.UTC`.

## Review Focus

1. **Backfill while the API is running.** Running `make backfill` with the server up must not run concurrently with scheduler syncs. `_RUN_LOCK` is a `threading.Lock`, so it does not serialise across processes. Detect that the server is up and refuse unless `--force` is passed (Task 5, `test_backfill_refuses_when_api_up`). The probe can't catch the reverse case (starting the server mid-backfill: the catchup fires Whoop after 10 s and Garmin after 180 s), so the backfill prints "don't start the server until this finishes" at start.
2. **The incremental window after a backfill.** Both pipelines' `_get_sync_window` take the newest `status="success"` SyncLog **by `SyncLog.id`** (not by `sync_end` or `started_at`). Its `sync_end` must be today, so the scheduler resumes correctly and doesn't re-walk history. Chunks run oldest first and the final chunk ends today (`test_backfill_chunks_oldest_first_and_end_today`). For that reason there is **no `--end` flag**: a backfill ending before today would leave the highest-id success log on an old `sync_end`, and the next scheduler run would walk from there to today in one unchunked window.
3. **A failed chunk mid-backfill** (429 or 5xx). Stop that source, report which chunk failed and how to resume, and leave the earlier chunks committed. The window must not move past the gap: chunks are oldest first, and a failed chunk writes an `error` log (`test_backfill_stops_source_on_failed_chunk`). The consequence: until the backfill is resumed, the next scheduler run walks `[last good sync_end − 2, today]` in **one** unchunked window, which can be hundreds of days, and on another 429 it retries every 30 min. So the hint says to resume **before** starting the server, in make form: `make backfill SOURCE=garmin START=<failed chunk start>`.
4. **No owner, or Whoop not connected.** Give a clear message, and still backfill whichever source is available (`test_backfill_without_whoop_still_runs_garmin`).
5. **A fresh clone following the README exactly.** `uv sync` → `make owner` → `make run` works with no Docker and no Node globally beyond Node 20+ (Task 1 manual check, recorded in the report).

---

## File map

| Task | Files |
|---|---|
| 1 Local run path | `Makefile` only (no `config/settings.py` change: nothing in Python would read a `host` setting; uvicorn takes `--host` from the Makefile), README "Running it" |
| 2 Docker path | `Dockerfile` (python:3.12-slim, node:22-slim), `docker-compose.yml` (`127.0.0.1:8000:8000`), `scripts/start.sh` (add `garmin_exercise_summaries` to the Postgres sequence reset, roadmap 5.3), `Makefile` `up`/`down`, delete `railway.toml`, `.dockerignore` check |
| 3 Python deps | `pyproject.toml` (`requires-python >=3.12`, drop unused `passlib`, add `bcrypt` directly, `[tool.uv] constraint-dependencies`, ruff `target-version = "py312"`), `.python-version` (`3.12`), `uv.lock`, `src/normalization/normalizer.py` (UP047) |
| 4 Frontend deps | `frontend-react/package.json`, `package-lock.json` |
| 5 Backfill | Create `scripts/backfill.py` and `tests/test_backfill.py`. `Makefile` `backfill` target |
| 6 Docs (Phase 7) | `README.md`, `CLAUDE.md`, `.env.example`, roadmap check-offs |

Order: 1 → 2 → 3 → 4 → 5 → 6.

---

### Task 1: Local run path

**Interfaces:**
- No `config/settings.py` change. A `host` setting would be dead config: uvicorn gets `--host` from the Makefile, and the backfill probe always targets `127.0.0.1`.
- `Makefile`, which keeps using `.venv/bin/*` (roadmap 5.5 said `uv run`; uv isn't on PATH on the dev machine, so `.venv/bin` stays):
  - `make run`: depends on the file target `frontend-react/dist/index.html`, then runs `$(UVICORN) src.api.main:app --host $(BIND_HOST) --port $(PORT)`. Defaults: `BIND_HOST ?= 127.0.0.1`, `PORT ?= 8000`. Echo `Open http://localhost:$(PORT)` first. Use `localhost`, not `127.0.0.1`, because it matches the default `WHOOP_REDIRECT_URI` and the login token lives in per-origin `localStorage`.
  - `frontend-react/dist/index.html` prerequisites: `$(shell find frontend-react/src frontend-react/public -type f)`, `frontend-react/index.html`, `vite.config.ts`, `tailwind.config.js`, `postcss.config.js`, `tsconfig*.json`, `package.json` and the npm stamp below. Recipe: `cd frontend-react && npm run build`. Don't compare against the `src` directory's mtime: a directory's mtime changes only when entries are added or removed, not when a file is edited.
  - npm stamp: `frontend-react/node_modules/.package-lock.json: frontend-react/package-lock.json` → `cd frontend-react && npm ci --silent`. This way `npm ci`, which wipes `node_modules`, runs only when the lockfile changes, not on every rebuild.
  - Migrations: **confirmed**. `src/api/main.py` imports the route modules, which import `src.api.dependencies`, and that module runs `run_migrations` at import time when the DB is SQLite. The lifespan doesn't migrate. With a Postgres `DATABASE_URL`, only `scripts/start.sh` migrates, so say so in one README line (D5).
  - `make dev`: the current `run-api` target (reload, API only, for use with `npm run dev`). Keep `run-api` as an alias so the docs don't break.
  - `make build-frontend`: an alias for the dist file target.
  - Keep `test`, `lint`, `fmt`, `owner` and `run-sync`. Update `.PHONY`.
  - Make `test` serial and quiet: `$(PYTEST) -q`.
- **Foreground only.** No background mode and no `make stop`: Ctrl-C stops it, which is also how the user clears the way for `make backfill`. PID-file management isn't worth it for one user.
- `scripts/start.sh` is **not** changed for host. In the container it keeps `--host 0.0.0.0`, which Docker port publishing needs, and compose restricts exposure on the host side (Task 2). Reading a bind host from the environment there would let an `.env` value meant for `make run` (compose passes the whole `.env` in) break the container.

- [ ] Make the edits.
- [ ] Check: `make -n run` shows the expected commands. `touch frontend-react/src/main.tsx && make -n run` shows a rebuild without `npm ci`.
- [ ] Check: with a throwaway DB (`DATABASE_URL=sqlite:////private/tmp/claude-501/-Volumes-Dock-Storage-Projects-garmin-whoop-dashboard/26b4f8fc-46fc-434b-bfa6-ea5ddc08c3fd/scratchpad/p5.db make run` in the background), `curl -s 127.0.0.1:8000/api/health` succeeds and `curl -s 127.0.0.1:8000/` returns the SPA HTML. Kill the server and delete the DB.
- [ ] Run the full suite and lint.
- [ ] Commit: `feat: make run (localhost by default), make dev, build-frontend`.

### Task 2: Docker path (statically checked)

- `Dockerfile`:
  - Use `node:22-slim` for the builder.
  - Use `python:3.12-slim` for the runtime.
  - Keep the uv layering.
  - Copy the pulse-demo-free `frontend-react/dist`.
  - The healthcheck stays.
- `docker-compose.yml`:
  - `ports: ["127.0.0.1:8000:8000"]`
  - Remove the `command:` override so `scripts/start.sh` is used (it runs migrations).
  - Keep `env_file: .env`, `./data:/app/data` and `restart: unless-stopped`.
  - Drop the `./config` volume. `config/field_mappings.yaml` is read-only at runtime (loaded by the normalizer and `csv_import`), so a volume mount over the baked-in config is only a footgun.
  - Don't add a compose `healthcheck`. Compose inherits the image's `HEALTHCHECK`, so a second copy would only drift.
- `scripts/start.sh`: add `garmin_exercise_summaries` (autoincrement `id`) to the Postgres sequence-reset list next to `garmin_exercise_sets` (roadmap 5.3). `sslmode=require` is already Postgres-only. No other change.
- `Makefile`: `up` → `docker compose up -d --build`, `down` → `docker compose down` (roadmap 5.5 `make up`). The backfill's API probe catches a running container, because it publishes on `127.0.0.1:8000` and shares `./data`.
- Delete `railway.toml`.
- Check that `.dockerignore` excludes `.env`, `data/`, `.venv/`, `node_modules/`, `.superpowers/` and `tests/`.

- [ ] Make the edits.
- [ ] Static checks: `docker compose config` isn't available, so validate the compose YAML with `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml'))"`. Re-read the Dockerfile to confirm every `COPY` source exists in the repo.
- [ ] Commit: `chore: Docker on Python 3.12/Node 22; compose binds localhost; drop railway.toml`.

### Task 3: Python dependency refresh

- `pyproject.toml`:
  - Set `requires-python = ">=3.12"`, matching the venv (3.12.13), the Dockerfile (Task 2, already done by then) and Garmin's ecosystem. Nothing in the code needs 3.11 specifically.
  - Add `.python-version` containing `3.12`, so `uv sync` on a fresh clone picks 3.12 rather than whatever newer interpreter is installed.
  - Remove `passlib[bcrypt]`. Nothing imports `passlib`; `src/auth/security.py` imports `bcrypt` directly. **`bcrypt` arrives only via passlib**: a reviewer's `uv lock --upgrade --dry-run` showed `Remove bcrypt v5.0.0`. So add `"bcrypt>=5.0,<6"` as a direct dependency in the same edit. It's already 5.0.0 in the current lock, so behaviour doesn't change.
  - Ruff `target-version = "py312"`.
- **The specifiers are all `>=`-only, so "within the existing specifiers" doesn't keep majors.** The reviewer's dry-run (2026-11-07, with `>=3.12` and no passlib) showed these transitive major bumps: **starlette 0.52.1 → 1.10.0** (FastAPI 0.162 requires only `starlette>=0.46`), **cryptography 46 → 50** and **websockets 16 → 17**. Within-major but large: fastapi 0.135 → 0.162, sqlalchemy 2.0.48 → 2.1.8 (drops the `greenlet` dependency; nothing uses async SQLAlchemy), uvicorn 0.41 → 0.54, ruff 0.15.4 → 0.17.4. Add the following and report it in the commit body:
  ```toml
  [tool.uv]
  constraint-dependencies = ["starlette<1", "websockets<17"]
  ```
  **Controller ruling R24:** `cryptography` is deliberately **not** capped. It ships a new major version with each security release, so capping it at <47 would block security fixes. It's used only through python-jose for HS256 JWT, and the auth tests cover that. Let it move to the latest version, and report the version in the commit body. If its upgrade breaks a test, pin it to the newest version that passes, and report that pin.
- Run `uv lock --upgrade --dry-run` first and check that no line crosses a major (X.y → X+1, or 0.x → 1.x). Then run `uv lock --upgrade` and `uv sync --frozen`.
  - uv is not on PATH. Use `/private/tmp/claude-501/-Volumes-Dock-Storage-Projects-garmin-whoop-dashboard/26b4f8fc-46fc-434b-bfa6-ea5ddc08c3fd/scratchpad/uvenv/bin/uv` (0.13.7 is there). If it's missing, create it with `python3 -m venv` + `pip install uv`.
  - Pin any package whose upgrade breaks tests back to the previous version range, and report it.
- py312 lint: ruff 0.15.4 and 0.17.4 both flag exactly **one** finding, `UP047` at `src/normalization/normalizer.py:56` (`upsert_row` with a module `TypeVar`). Its fix is unsafe, and **`make fmt` only runs `ruff format`, which doesn't apply lint fixes.** Convert `upsert_row` to PEP 695 syntax (`def upsert_row[M](...)`) by hand, drop the now-unused `TypeVar` if nothing else uses it, and keep that in a separate commit.

- [ ] Run the full suite and lint.
- [ ] Commit: `chore(deps): Python 3.12 floor, uv lock refresh, drop unused passlib`. Include a short summary of the version changes in the body.

### Task 4: Frontend dependency refresh

- `cd frontend-react && npm update` (stays within the semver ranges), then `npm audit fix` (no `--force`).
- Report the before and after `npm audit` counts. Remaining vulnerabilities that need major bumps are listed, not fixed (D7).
- TypeScript minors don't follow semver (`^5.5.3` can reach 5.9 with new errors). If `typecheck` fails only because of the TS bump, pin `typescript` to the previously locked minor (`~5.x.y`) instead of editing app code, and report it.

- [ ] Run `npm run typecheck && npm run build`.
- [ ] Commit: `chore(deps): frontend npm update + audit fix (no majors)`.

### Task 5: `scripts/backfill.py` + `make backfill`

**Verified against the code (b45acac):**
- `GarminPipeline(db, client=None, user_id=None).run(start: date | None, end: date | None) -> SyncLog | None`. It is sync. Explicit `start`/`end` replace the auto window entirely, so the 2-day overlap applies only to incremental runs. `sync_type` is `"manual"`, and `_get_sync_window` ignores `sync_type`. `GarminPersonalApiError` (key, 429, 5xx, network) → returns the log with `status="error"`. **Any other exception is re-raised** after the error log is written. Each successful run calls `normalize_all(start, end)`.
- `WhoopPipeline(db, client=None, user_id=None).run(start: datetime | None, end: datetime | None) -> SyncLog | None`. It is async. **Every failure is raised**: it never returns an `error` log. That includes `WhoopReauthRequired` from a rejected refresh. On success it calls `normalize_all(start.date(), end.date())`.
- `None` from either pipeline means its in-process `_RUN_LOCK` was held. That can't happen in a single-threaded backfill process, but handle it as a failure anyway.
- `normalize_all` **already calls `refresh_anomalies(engine, user_id, start, end)` per chunk**. That swallows its own fetch errors and returns 0. `detect_anomalies` only sees the sliced window (the 29-day lookback feeds the rolling averages only), so the **first 7 days of every chunk are never flagged**. That's why the single full-range pass at the end is still needed. It costs one UNION query over (range + 29 d) × 7 metrics, 3 context queries and one delete/insert: seconds, even for 2 years.
- Whoop auth helpers: `WhoopAuth.has_token(user_id, db) -> bool` (classmethod) and `whoop_auth_error(user_id, db) -> str | None` (module function, in `src/clients/whoop_auth.py`). Don't use the private `_service_key`.
- `get_owner_user_id(engine)` returns `None` when there are no users and **raises `RuntimeError` when there is more than one**.
- A Garmin date beyond the daily depth: `get_daily_summary` returns `{}`, the pipeline logs one `WARNING ... daily summary unavailable` per day and carries on. Sleep and HRV return `None` (debug log). No error. Don't suppress those warnings (never swallow); the pre-run notice says to expect them.

**Interfaces:**
- CLI: `python scripts/backfill.py --source {garmin,whoop,all} --start YYYY-MM-DD [--chunk-days N] [--force]`.
  - **No `--end`.** The range always ends today (local date). See Review Focus #2.
  - `--start` must be ≤ today.
  - `--chunk-days` defaults to 30 and must be ≥ 1. Garmin is clamped to ≤ 31, per the roadmap; see the Spec note.
  - Usage errors go through `parser.error` → `SystemExit(2)`, the argparse convention.
- `main(argv: list[str] | None = None) -> int` (testable, like `scripts/create_owner.py`). It's sync at the top level, and calls `asyncio.run` once per Whoop chunk. Pure helpers, so they can be tested without I/O:
  - `garmin_chunks(start: date, today: date, chunk_days: int) -> list[tuple[date, date]]`: inclusive, contiguous, oldest first, last `e == today`.
  - `whoop_windows(chunks: list[tuple[date, date]], now: datetime) -> list[tuple[datetime, datetime]]`: aware UTC, `[combine(s, 00:00, UTC), combine(e + 1 d, 00:00, UTC))`. The final window ends at `max(now, combine(today + 1 d))`, so it never stops short of now (the US evening case) and never has start > end (the UTC+ morning case). Naive datetimes would be stored as offset-less `sync_end` strings and reach the Whoop API without an offset.
  - `api_running(port: int) -> bool`: `httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)`. `httpx.ConnectError` → `False`. Any HTTP response → `True`. **A timeout → `True`** (fail closed: the server is up but busy).
- **Preconditions, in this order:**
  1. Parse and validate the args.
  2. Probe `api_running(settings.app_port)`. That reads `PORT`, then `APP_PORT`, then 8000. The probe runs before any DB access, so a running server never sees a concurrent migration. If it's up and `--force` wasn't passed, print "The API server is running on port N; its scheduler would race the backfill. Stop it (Ctrl-C / `make down`) or pass --force." and return **3**.
  3. Run migrations, using the same pattern as `initial_sync.py`.
  4. Resolve the owner. With no owner, print "No owner account. Run `make owner EMAIL=...` first." and return 1. On `RuntimeError` (more than one user), print it and return 1.
- **Pre-run notice, printed once:**
  - The day count and a rough time estimate: Garmin ≈ 3 calls per day at ≥ 1 s each, so 2 years ≈ 40 min.
  - "Don't start the server until this finishes."
  - "Garmin daily summaries stop somewhere between 180 and 365 days back; older days log 'daily summary unavailable' and only activities come through. For older daily data, use a Garmin account export with `scripts/import_data.py`."
- **Per source**, Garmin first and then Whoop, each independent so one failing doesn't stop the other. Garmin goes first so that each Whoop chunk's `normalize_all` sees both sides; the matcher already drops stale `g_` rows. Use one `Session` for the run, as `initial_sync.py` does.
  - **Garmin:**
    - Skip with a message if `settings.garmin_personal_api_key` is empty.
    - Otherwise, for each chunk `[s, e]`, oldest first, call `GarminPipeline(db, user_id=owner).run(start=s, end=e)`.
    - A chunk **fails** on any of these: a `None` return, `log.status == "error"` (print `log.error_message`), or a raised exception (`logger.exception` for the traceback, then print the type and message).
    - A failure stops Garmin and prints the resume hint (format below).
    - Print the per-chunk status and record counts.
  - **Whoop:**
    - Skip with a message if `not WhoopAuth.has_token(owner, db)` ("connect Whoop in Settings first"), or if `whoop_auth_error(owner, db)` returns a message ("needs reconnect").
    - Otherwise, run the same chunk loop over `whoop_windows(...)` with `asyncio.run(WhoopPipeline(db, user_id=owner).run(start=ws, end=we))`.
    - Catch the raised exception per chunk. `WhoopReauthRequired` → "Whoop rejected the token; reconnect in Settings, then resume". Anything else → `logger.exception` plus type and message. Either way, stop Whoop and print the resume hint.
  - **Resume hint**, printed as the make command the user actually runs: `make backfill SOURCE=<that source> START=<failed chunk start>`, followed by "Run it before starting the server."
- **After both sources:** if any chunk succeeded with `records_stored > 0`, call `refresh_anomalies(engine, owner, start, today)` once and print the count it returns. It also runs after a partial failure: it's idempotent over what's stored.
- **Ctrl-C:** catch `KeyboardInterrupt` around the chunk loop, print the resume hint for the current chunk, and return 130. The interrupted chunk's SyncLog stays `running`, which is harmless: only `success` rows move the window.
- **Exit codes:**
  - 0: every attempted source completed, and at least one source ran.
  - 1: any source failed, no owner or more than one user, or **nothing ran**. Nothing ran means both sources were skipped, or an explicit `--source X` was skipped. With `--source all`, a skipped source isn't a failure when the other one ran.
  - 2: a usage error (argparse).
  - 3: the API is up and `--force` wasn't passed.
  - 130: interrupted.
- **Makefile** (`START` is required; `PORT` is passed so the probe checks the same port as `make run`; `caffeinate -i` keeps a Mac from idle-sleeping mid-run when it's available):
  ```
  backfill:
  	$(if $(START),,$(error START=YYYY-MM-DD is required))
  	PORT=$(PORT) $(shell command -v caffeinate >/dev/null && echo caffeinate -i) $(PYTHON) scripts/backfill.py --source $(or $(SOURCE),all) --start $(START) $(if $(CHUNK_DAYS),--chunk-days $(CHUNK_DAYS),)
  ```
- **The machine sleeping mid-run** without caffeinate (lid closed): on wake, the in-flight request fails. For Garmin that's a `GarminTransientError` → an `error` log. For Whoop it's an `httpx` error, which is raised. The source stops with the resume hint, the earlier chunks stay committed, and the 24 h Garmin bearer is re-fetched on 401.

- [ ] **Step 1: failing tests** (`tests/test_backfill.py`; follow `tests/test_initial_sync.py` / `tests/test_create_owner.py`; patch the pipelines, `api_running`, the owner lookup, the Whoop auth helpers, `refresh_anomalies`, settings and "today"/"now"; use one shared in-memory engine):
  - `test_backfill_requires_owner` → no owner → returns 1, no pipeline constructed. `get_owner_user_id` raising `RuntimeError` → returns 1.
  - `test_backfill_refuses_when_api_up` → the probe returns True, no `--force` → returns 3, **no migration and no pipeline** constructed. With `--force`, it runs.
  - `test_api_running_probe` → `ConnectError` → False; a 200 → True; `TimeoutException` → True.
  - `test_backfill_chunks_oldest_first_and_end_today` → start = today−65, chunk 30 → Garmin is called with exactly three `(s, e)` pairs in ascending order. The last `e == today`. Chunks are contiguous and non-overlapping.
  - `test_garmin_chunk_clamped_to_31_days` → `--chunk-days 60` → each Garmin chunk spans ≤ 31 days.
  - `test_whoop_windows_aware_contiguous_final_reaches_now` → every bound has `tzinfo == UTC`. `window[i].end == window[i+1].start`. The final end is ≥ the patched `now`, both when `now` is after `combine(today + 1 d)` and when it's before. The final start is < the final end.
  - `test_backfill_stops_source_on_failed_chunk` → the second Garmin chunk returns `status="error"` → no third Garmin call. Whoop still runs. Exit 1. The output contains `make backfill SOURCE=garmin START=<second chunk start>`.
  - `test_backfill_stops_source_on_raised_exception` → the second Garmin chunk raises `RuntimeError` → no third call, Whoop still runs, exit 1, resume hint printed. Separately, a Whoop chunk raising `WhoopReauthRequired` → Whoop stops with the reconnect message and the hint, exit 1.
  - `test_backfill_without_whoop_still_runs_garmin` → `--source all`, no Whoop token → Whoop skipped with a message, Garmin runs, exit 0.
  - `test_backfill_skips_whoop_when_needs_reauth` → `whoop_auth_error` returns a message → no `WhoopPipeline` constructed, "needs reconnect" printed.
  - `test_backfill_nothing_to_run_returns_1` → no Garmin key and no Whoop token → exit 1. Also `--source whoop` without a token → exit 1.
  - `test_backfill_refreshes_anomalies_once_over_full_range` → called exactly once with `(engine, owner, start, today)` after both sources. Not called when nothing was stored.
  - `test_invalid_args_rejected` → a future `--start` or `--chunk-days 0` → `SystemExit` with code 2.
- [ ] Step 2: run the tests and confirm they FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: run the full suite and lint.
- [ ] Step 5: smoke test against a throwaway DB with the real Garmin key. Use a short range, for example the last 10 days with `--chunk-days 5`: create a throwaway owner (`create_owner` with a generated test password via the patched getpass, or seed the users row directly), run `scripts/backfill.py --source garmin --start <today-9>`, and record the chunk statuses and row counts. Then delete the throwaway DB. **Never touch `data/fitness_dashboard.db`.** Set `DATABASE_URL` in the process environment (`load_dotenv` doesn't override it). If SJ's server is up on 8000, the probe refuses, so pass `--force`: the DB is different, and only the Garmin call rate doubles for ~30 calls. Print no tokens and no real health values; report counts only. Then check that the newest `success` Garmin SyncLog by `id` has `sync_end == today`.
- [ ] Step 6: commit: `feat: make backfill (chunked, oldest-first, API-running guard)`.

### Task 6: Docs pass (roadmap Phase 7)

- `README.md`: a single "Getting started" flow:
  1. `brew install uv`, plus Node 20+.
  2. `uv sync`, `cp .env.example .env`, then fill in `JWT_SECRET`, the Whoop client ID/secret and `GARMIN_PERSONAL_API_KEY`.
  3. `make owner EMAIL=…`.
  4. `make run` → `http://localhost:8000`, then log in. Use `localhost` consistently: the Whoop callback lands there, and the login lives in per-origin `localStorage`, so `127.0.0.1` would be a separate, logged-out session.
  5. Settings → Connect Whoop. `http://localhost:8000/api/auth/whoop/callback` must be registered in the Whoop developer dashboard and match `WHOOP_REDIRECT_URI`.
  6. **Stop the server (Ctrl-C)**, then `make backfill START=<date>` (optionally `SOURCE=garmin|whoop`). Include the history-depth notes: Garmin daily data reaches 180–365 days back and activities ~690. Older Garmin data comes from an account export via `scripts/import_data.py`. Expect ~40 min for 2 years. If it stops, run the printed resume command before restarting the server.
  7. `make run` again.

  Docker Compose (`make up` / `make down`) goes under "optional". Remote access: one line, `tailscale serve 8000` (keeps the localhost bind; `BIND_HOST=0.0.0.0` is the LAN opt-in). Keep the troubleshooting notes short.
- `.env.example` (roadmap Phase 7):
  - Drop the Supabase "Production" line, keeping a generic Postgres example comment (D5).
  - Replace `APP_PORT` with a note that the port is set by `make run PORT=…` and `make backfill PORT=…`. Make doesn't read `.env`, so an `APP_PORT` there would only move the backfill probe.
- `CLAUDE.md`:
  - Local dev commands: `make run`, `make dev`, `make backfill`.
  - Python 3.12.
  - Localhost binding (`BIND_HOST`).
  - Fix the stale `make fmt` line: it only runs `ruff format`, not lint fixes.
  - Phases 5–6 done.
  - The test count.
  - Remove the "relaunch in progress" framing if nothing material remains, apart from SJ-owned steps and the open product decisions. List those under a short "Open items" heading.
- Roadmap: check off Phases 5, 6 (tooling) and 7, with "done 2026-11-07". Note that the actual backfill run waits on SJ (`make owner`, Whoop connect).

- [ ] Make the edits. Verify every command mentioned exists.
- [ ] Commit: `docs: getting-started flow; Phases 5–7 done`.

---

**Done when:**
- The suite, lint, typecheck and build are green.
- `make -n run`, `make -n up` and `make -n backfill START=2026-01-01` are correct, and `make backfill` without `START` fails with the message.
- The backfill smoke test is recorded.
- The Docker files are statically valid.
