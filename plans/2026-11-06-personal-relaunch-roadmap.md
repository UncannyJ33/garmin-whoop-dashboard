# Personal relaunch roadmap

*Written 2026-11-06. Research: [`docs/research/2026-11-garmin-personal-api.md`](../docs/research/2026-11-garmin-personal-api.md).*

**Goal:** turn PulseEngine, a multi-user public SaaS last touched in April 2026, into a basic
dashboard that one person (SJ) hosts privately. Garmin data will come from Garmin's official
Personal API instead of the unofficial `garminconnect` password login.

**Why now:** Garmin opened a free, self-serve Personal API on 2026-10-21. The unofficial path has
been degrading. garth is deprecated, and garminconnect's mobile login returned 429 on every
attempt from April to October. We pin garminconnect 0.3.1, so Garmin sync is probably broken
today.

**Shape of the work:** most of the app survives unchanged: the analytics, normalization, unified
tables, the React pages and the Whoop ingestion. The work is a swap (the Garmin client), a cut
(the SaaS surface), a few bug fixes (Whoop token rotation), and a move off Railway and Supabase.

---

## Decisions already made

| # | Decision | Why |
|---|---|---|
| D1 | **Keep JWT login and the `user_id` plumbing, with exactly one owner user.** Replace open registration with `scripts/create_owner.py`. | Ripping out `user_id` touches about 40 files, about 600 references, the schema and most tests. A fixed owner costs one helper. Login stays useful if the box is reachable over a network. |
| D2 | **Garmin through the Personal API, using our own small `httpx` client.** Don't use Garmin's official package. | The wire protocol is one token POST plus bearer GETs. The official package needs `requests`, Python ≥ 3.12 and an on-disk cache in `~/.config`. Treat it as a reference only. |
| D3 | **Polling only. Remove the Whoop webhook receiver.** | Garmin Personal is pull-only anyway. The webhook has no HMAC check and has been broken since migration 008. Polling every 30 min is enough for one person. |
| D4 | **Strength workouts use `summarizedExerciseSets` (per-exercise summaries) for now.** | The Personal API has no `/exerciseSets` endpoint. Set-level detail can come later by parsing the `.FIT` download. Existing set-level history stays in place. |
| D5 | **Keep the dual SQLite and Postgres support in code. Default to SQLite.** | It already works, and deleting it gains nothing. |
| D6 | **Leave `landing/` untouched.** | It's the pulsebuilt.net studio page, deployed by Cloudflare Pages from this repo, not part of the dashboard. |
| D7 | **Defer frontend major upgrades** (React 19, Vite 7, Tailwind 4, Recharts 3, React Router 7). | That work is separate from the relaunch. Phase 5 only bumps versions within the current majors. |

## Questions for SJ

| # | Question | Answer |
|---|---|---|
| Q1 | Where does it run? | **Answered 2026-11-06: locally.** Railway is dead. Docker Compose + SQLite on disk. Incremental sync catches up after the machine has been off. |
| Q2 | Is the Supabase history still alive? | **Answered 2026-11-06: no.** Supabase was deleted. The old data is gone, and everything gets pulled from scratch (Phase 6). |
| Q3 | Should `landing/` and pulsebuilt.net stay in this repo? | Open. Leave them for now (D6), and move them to their own repo when convenient. Blocks nothing. |

## Phase dependency graph

```
Phase 0 (preconditions) ──► Phase 1 (spike, needs Garmin key)
                                  │
                                  ▼
                           Phase 2 (Garmin swap + single-owner scheduler)
                                  │
                                  ▼
                           Phase 3 (SaaS cut + Whoop fixes)
                                  │
                                  ▼
                           Phase 4 (frontend cleanup)
                                  │
                                  ▼
                           Phase 5 (local hosting + dependency refresh)
                                  │
                                  ▼
                           Phase 6 (backfill from scratch)
                                  │
                                  ▼
                           Phase 7 (docs final pass)
```

**Branching.** Phase 2 merges on its own: its `GET /api/auth/garmin/status` stays a superset of
today's `{connected}` (the only field the frontend reads), and its last task trims the Garmin
settings card so nothing calls the deleted credential routes. Phases 3 and 4 share one branch,
because deleting `/register`, `/feature-flags` and the webhook needs the matching `Login.tsx` and
Settings edits in the same merge. Phase 2 has a detailed plan:
[`2026-11-06-garmin-personal-api-client.md`](2026-11-06-garmin-personal-api-client.md).
Phases 3–7 each get a detailed plan when they're picked up. The task lists below are their scope.

---

## Phase 0: Preconditions

**SJ (only you can do these):**
- [ ] Create a Garmin Personal API key at <https://connect.garmin.com/app/settings/personalApiToken>.
      Pick **365 days**. Save it in your password manager and put it in `.env` as
      `GARMIN_PERSONAL_API_KEY`. Set a calendar reminder for expiry.
- [x] WHOOP app still exists (confirmed 2026-11-06).
- [ ] In the WHOOP developer dashboard, make sure the redirect URIs include
      `http://localhost:8000/api/auth/whoop/callback`. The old one was engine.pulsebuilt.net.
      Copy the client ID and secret into `.env`, and remove the webhook URL (D3).
- [x] Answer Q1 and Q2 (above).
- [x] `.env` created from `.env.example` (gitignored, mode 600, JWT secret generated). Still
      needs the Whoop client ID/secret and the Garmin key.

**Agent:**
- [x] Bootstrap the local env (2026-11-06). `uv sync --frozen` produced `.venv` on Python
      3.12.13, and `npm ci` ran on Node 25.9.0. `uv` is **not installed globally**; the agent used
      a throwaway copy. SJ: `brew install uv`.
- [x] Baseline, recorded 2026-11-06 on `main` code:
  - `pytest -q` (serial): **909 passed**, 0 failed, 1 warning (an un-awaited coroutine in
    `test_scheduler_multiuser.py::TestCatchupOnRestart`). The old "946" was stale.
  - `pytest -n auto` (xdist) is **broken**: 18 collection errors (SQLite `OperationalError` in
    `test_data_isolation.py` and `test_garmin_credentials.py`, plus "different tests collected
    between workers"). Run tests serially until that's fixed. `test_garmin_credentials.py` is
    deleted in Phase 2; check whether `test_data_isolation.py` still fails under xdist afterwards.
  - `make lint`: **25 existing ruff errors** (F401 unused imports, I001 import order, F841 unused
    locals; 23 auto-fixable).
  - `npm run typecheck` and `npm run build`: pass. `npm ci` reports 25 vulnerabilities (3 low,
    11 moderate, 11 high), to be handled in the Phase 5 dependency refresh.
- [x] (done 2026-11-06, Phase 2) Clean lint baseline: `.venv/bin/ruff check --fix .`, fix the 2 non-auto-fixable errors by
      hand, and confirm `pytest -q` still reports 909 passed. Do this first in Phase 2, so "lint
      stays clean" means something.

## Phase 1: Spike (needs the key)

- [x] **Done 2026-11-06.** Live findings are in research §9; sanitized fixtures are in `tests/fixtures/garmin_personal/`.

This is Task 1 of the Phase 2 plan. A probe script exchanges the key, hits each endpoint we use
for a recent date and for a date about 2 years back, and saves raw responses to a gitignored
directory. It then writes **sanitized** fixtures into `tests/fixtures/garmin_personal/`. It
answers the open items in research §8: `sleepScores` key, HRV field names, which activity fields
are populated, `maxWeight` units, history depth and any 429 behavior.

## Phase 2: Garmin Personal API swap + single-owner scheduler

- [x] **Done 2026-11-06** on branch `feat/garmin-personal-api` (about to fast-forward into `main`). 938 tests pass (serial), lint clean, live smoke test OK (30 days: 31 daily summaries, 44 activities, one token exchange, no 429s).

The detailed plan is [`2026-11-06-garmin-personal-api-client.md`](2026-11-06-garmin-personal-api-client.md). Summary:
- New `GarminPersonalAuth` (key → 24 h JWT, one process-wide instance, re-exchanged when < 1 h
  remains) and a rewritten `GarminClient` with the **same method names**, so `GarminPipeline`
  barely changes. A 429, 5xx or network error ends the run as `error` without advancing the
  window; the next interval re-pulls it.
- Pipeline transforms handle the flat `DailySleepDTO` (timestamps as Unix ms or ISO strings),
  `sleepScores`, HRV `lastNightAvg`, and the new `garmin_exercise_summaries` table
  (migration 014). Incremental runs re-fetch a 2-day overlap, because the activity filter is on
  local start date and the container clock is UTC.
- Strength API routes read the summaries and still show existing set-level history.
- `get_owner_user_id()`. The scheduler collapses to one Garmin job and one Whoop job for the owner.
- Delete `garminconnect`, `garmin_auth.py`, `encryption.py`, the credential routes and the
  settings fields that went with them.
- Frontend: the Garmin card in Settings and the Connect-devices panel reads the key status
  (moved here from Phase 4 so this phase merges clean).

## Phase 3: SaaS cut + Whoop fixes (backend)

Scope for its detailed plan:
1. **Owner bootstrap.** Add `scripts/create_owner.py --email you@x` (password via `getpass`) and
   delete `POST /api/auth/register`. Keep login, refresh and change-password. Refuse to create a
   second user. Also make `get_current_user` (`src/auth/dependencies.py`) reject a token whose
   `sub` is not `get_owner_user_id()` with a 401. Today it builds `User(id=sub)` with no DB
   check, so after the DB is wiped and rebuilt, a stale 30-day refresh token would log you into
   an empty dashboard instead of bouncing you to login. Cache the owner id in-process.
2. **Remove the waitlist**: `src/api/routes/waitlist.py`, its `main.py` registration and
   `_NO_CACHE_PREFIXES` entry, `ADMIN_EMAIL`, and `tests/test_waitlist.py`. **Leave migration
   files in place**, because existing DBs have run them. Don't delete tables.
3. **Remove the Whoop allowlist and feature flags**: `WHOOP_PUBLIC_OAUTH_ENABLED`,
   `WHOOP_ALLOWED_USER_IDS`, the check at `auth.py:~224` and `GET /api/auth/feature-flags`.
4. **Account routes**: keep `GET /api/account/export`, which doubles as a personal backup. Delete
   `DELETE /api/account` and its cascade. Drop the now-unused `GarminCredentials` model
   references, but keep the table.
5. **Remove the Whoop webhook**: `src/api/routes/webhooks.py` and its registration (D3).
6. **Whoop token-rotation fixes** (see research §7):
   - `_store_tokens` (`whoop_auth.py:194`) already persists a returned `refresh_token`; only its
     comment is wrong. Fix the comment, and add a test that a refresh response's `refresh_token`
     replaces the stored one.
   - Serialize refreshes with a process-wide lock, and re-read the token row after acquiring it.
     It must be a `threading.Lock`, not an `asyncio.Lock`: the scheduler runs the Whoop pipeline
     with `asyncio.run()` on the APScheduler thread (`scheduler.py:~383`) while the manual
     trigger runs it on the FastAPI loop (`sync.py:155`), so there are two event loops. Acquire
     it with `await asyncio.to_thread(lock.acquire)` and release in `finally`.
   - The scheduler must **not** delete the token row on a 401 (`scheduler.py:~395–415`). It
     records a "needs re-auth" status that the Settings page can show.
   - Tests: two concurrent `get_valid_token()` calls (`asyncio.gather` with an expired row)
     produce exactly one refresh POST, and both callers get the new token.
7. **One Garmin import route**: keep `POST /api/garmin/upload` (CSV, JSON and ZIP) and delete
   `POST /api/garmin/csv-import` and its duplicated helpers. The Garmin export import stays,
   because it's the backfill path if Personal API history turns out to be shallow.
8. **Delete the legacy Streamlit app**: `frontend/`, the `streamlit` dev dependency and the
   `make run-frontend` target.
9. **CORS**: add no middleware unless `CORS_ORIGINS` is set. Same-origin is the default.

10. **Follow-ups found during Phase 2:**
    - The normalizer leaves a stale `g_<garmin_activity_id>` `unified_workouts` row when a later
      Whoop match creates `w_<id>` for the same activity. That duplicates workouts and
      double-counts strength volume. Fix: delete or skip `g_<aid>` once matched.
    - `scripts/initial_sync.py` runs the pipelines with `user_id=None` when no owner exists. It
      should print "register first" and exit.
    - While `/register` is open, a second account makes the owner check fail: background syncs
      stop, and that account sees the owner's key status. Item 1 closes this.

**Done when:** `make test` and `make lint` are green, there are no references to waitlist,
register, feature-flags or webhooks under `src/`, and the concurrent-refresh test passes.

## Phase 4: Frontend cleanup

Scope for its detailed plan:
1. Delete `Landing.tsx`, `Privacy.tsx`, `Onboarding.tsx`, `Showcase.tsx`, `ApiTest.tsx`, the
   unrouted `Demo.tsx`, and their routes in `App.tsx`. `/` goes to Today when authenticated and to
   `/login` otherwise.
2. `Login.tsx` becomes login only, with no register toggle.
3. Settings: the Garmin card already reads key status (Phase 2, Task 9). Remove the
   feature-flag hook, the delete-account UI and their hooks in `useApi.ts`. Show "needs re-auth"
   for Whoop (from Phase 3.6).
4. `ConnectDevicesPanel.tsx`: done in Phase 2 Task 9; nothing left here.
5. Strength: `WorkoutRow.tsx` shows the per-exercise summary
   (`GET /api/workouts/{id}/exercise-summary`, from Phase 2) when an activity has no set rows.
   The Training charts keep their current endpoints.
6. Delete `pulse-demo/`, its Dockerfile stage and copy line, and the `/demo` special-case in
   `main.py`'s `spa_fallback`.
7. PWA: remove `vite-plugin-pwa`, `InstallPrompt`, `useOnlineStatus` (if nothing else uses it)
   and `manifest.json`. The app runs locally (Q1), and a service worker on localhost only causes
   stale-cache confusion. Re-add it if remote access via Tailscale (Phase 5.7) gets used on a
   phone.

**Done when:** `npm run typecheck` and `npm run build` are clean, and no frontend code calls a
backend route deleted in Phases 2–3 (grep `useApi.ts` against `src/api/routes`).

## Phase 5: Local hosting + dependency refresh

1. **Dockerfile**: drop the pulse-demo stage, and move to `python:3.12-slim` and `node:22-slim`.
   Update ruff's `target-version` and `requires-python` to match.
2. **docker-compose.yml** becomes the primary way to run the app: one service, `env_file: .env`,
   `./data:/app/data` for SQLite, `restart: unless-stopped`, and a healthcheck on `/api/health`.
3. **`scripts/start.sh`**: only pass the Supabase-specific `sslmode=require` when `DATABASE_URL`
   is Postgres. Add `garmin_exercise_summaries` to its Postgres sequence-reset list next to
   `garmin_exercise_sets`.
4. Delete `railway.toml` and `frontend-react/vercel.json` (Q1: local; Railway is dead).
5. **Makefile**: switch to `uv run`, and add `make up` (compose), `make owner`
   (`create_owner.py`) and `make backfill START=… END=…`. The backfill target needs a script
   that takes `--start/--end/--source`; `scripts/initial_sync.py` has no arguments today (fixed
   30 days, no `user_id`). Extend it or add `scripts/backfill.py`. It must run the Garmin range
   in ≤31-day chunks **oldest first** (so a 429 or outage loses one chunk, and the last
   successful `sync_end` is the newest date, which is what the scheduler's next incremental
   window keys off), and it should refuse to start while the API process is running, or at
   least say so, because a scheduled run can overlap it.
6. **Dependencies**: `uv lock --upgrade`, and drop the unused `passlib`. Run `npm update` within
   the current majors. Then re-run the full test suite and the build.
7. Remote access (optional): document `tailscale serve 8000`.

## Phase 6: Backfill from scratch

Supabase was deleted (Q2), so there's nothing to migrate. The DB is a fresh SQLite file at
`data/fitness_dashboard.db`, created by migrations on first start.

1. `make owner` (Phase 3.1 / 5.5) creates the single user, then connect Whoop via Settings
   (OAuth).
2. **Whoop**: backfill through the existing pipeline with an explicit date range. The Whoop API
   serves full history. Pick a start date (for example 2 years back), and at 100 req/min the
   default rate limit is not a concern.
3. **Garmin**: backfill through the Personal API as deep as the Phase 1 spike showed, with
   `make backfill` (Phase 5.5: ≤31-day chunks, oldest first, API stopped). At 1 call/s and three
   calls per day, two years is about 40 minutes. For anything older, request a Garmin account
   data export and load it with `scripts/import_data.py`. Old strength sessions from the export
   come in with set-level rows, which Phase 2's "sets win over summaries" rule already handles.
   Phase 2 finding: daily-summary history reaches only ~180 days back (activities ~690), so
   older daily data must come from the export. VO2 max is absent from the API and won't backfill.
4. Re-run `normalize_all` and recompute the anomaly cache. Backfill Whoop and Garmin before
   normalizing, so dedup sees both sides.

## Phase 7: Docs final pass

Update `README.md` (setup: key → `.env` → `make owner` → `make up`), `CLAUDE.md` (move the
Garmin field-name section to the Personal API shapes, and remove the "relaunch in progress"
banner) and `.env.example`. Fold any spike findings into the research doc.

---

## Risks

| Risk | Mitigation |
|---|---|
| Personal API returns empty `vO2MaxValue` or `activityTrainingLoad` | **Confirmed live (2026-11-06):** `vO2MaxValue` is absent (the VO2 max chart gets no new points); `activityTrainingLoad` is present. The readiness score redistributes weights when a component is missing. |
| History depth is shallow | Fall back to the Garmin data export plus the existing importer (Phase 6.3). |
| Key expires silently | The status endpoint and Settings card surface "key rejected/expired". Pick the 365-day expiry, and Garmin emails about a week before. |
| Undocumented rate limits | 1 s between calls, abort the run on the first 429, poll every 30 min, and backfill in chunks so an abort loses little. Range endpoints are a later optimization, not part of the client: `dailySleepSummariesByDate` (31 d) and `hrv/daily` (same `hrvSummary` shape) would be drop-ins, but the daily-summary range (`v2/dailysummaries`) is a different nested shape and needs its own transform. |
| A 5xx or outage mid-run | The run ends as `error` and the window doesn't advance, so nothing is skipped; the next interval re-pulls. Incremental runs also overlap the previous `sync_end` by 2 days. |
| Old history lost with Supabase (confirmed) | Backfill from the Whoop API, the Garmin Personal API and the Garmin export (Phase 6). Derived data (unified tables, anomaly cache) gets recomputed. |
