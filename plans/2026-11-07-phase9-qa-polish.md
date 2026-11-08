# Phase 9: QA and Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last two known defects, then run a real-browser QA pass over every page before SJ uses the app for the first time. The pass uses a throwaway DB filled with live Garmin data. Fix what it finds.

**Spec:**
- `CLAUDE.md` "Open items"
- parked ruling R22, the normalizer's reverse-direction duplicate
- the cleanup review finding on Virtuoso `useWindowScroll` (Training workout log may render blank)

## Global Constraints

- Branch `feat/phase9-qa` from `main`, after the Phase 8 merge.
- Baseline is **1033 passed**. Run tests serially with `.venv/bin/pytest -q`; xdist is broken.
- `make lint`, `npm run typecheck` and `npm run build` must stay clean.
- **Never touch `data/fitness_dashboard.db`.** All QA runs use a throwaway DB under `/private/tmp/claude-501/-Volumes-Dock-Storage-Projects-garmin-whoop-dashboard/26b4f8fc-46fc-434b-bfa6-ea5ddc08c3fd/scratchpad/`.
- QA serves on a port other than 8000 or 8001: use **8002**.
- The QA owner account is a throwaway test account on localhost:
  - email `qa@example.com`
  - a generated password written only to `scratchpad/qa-credentials.txt`
  - never printed in reports
- Live Garmin data in the throwaway DB is SJ's own data and stays local. Reports contain counts and observations, not health values.
- The settled decisions and invariants in `CLAUDE.md` still bind. Code-quality rules: surgical changes, never swallow errors, type hints and docstrings.

## Review Focus

1. **A matched Whoop workout that stops qualifying** (re-scored to strain=null, or re-labelled driving). After normalizing, exactly one unified row remains for that Garmin activity (`g_<aid>`), and no stale `w_<id>` row. That holds even when the activity is outside the normalize window. The QA dataset is Garmin-only, so only the tests verify this.
2. **The Training "All workouts" log with more than 20 workouts** renders rows and keeps rendering them while you scroll the main content area.
3. **Every page loads with no console errors** using a Garmin-only dataset, with Whoop not connected. Empty states for Whoop-dependent cards are sensible, not crashes and not infinite spinners.

---

### Task 1: Stale Whoop rows in `unified_workouts` (R22)

**Problem:** Whoop workout X was matched to Garmin activity A, so `w_X` carries A's fields. Later, X stops qualifying: it's re-scored to `strain IS NULL` (it becomes a recovery activity) or it's deleted. The normalizer then writes `g_A` as an unmatched Garmin row, but `w_X` stays. Activity A is now counted twice.

**Fix:** in `Normalizer.normalize_workouts` (`src/normalization/normalizer.py`), after both upsert loops and before the commit:

1. **One shared selection predicate.** The window query selects Whoop workouts with `strain IS NOT NULL` **and** `sport_name != 'driving'` (normalizer.py:185-192), not just strain. Factor those two SQLAlchemy expressions (plus the `user_id` filter) into one helper used by both the window query and this cleanup, so they can't drift. Reusing the same expressions also keeps SQL NULL semantics identical: `sport_name != 'driving'` excludes NULL `sport_name` too. A "missing or strain NULL" criterion would keep a stale row for a workout re-labelled `driving`.
2. **Select the stale rows** (no date window, which avoids the UTC/local boundary problem behind parking R22):
   - `UnifiedWorkout.whoop_workout_id IS NOT NULL`. Every `w_` row sets it (`map_whoop_workout`) and every `g_` row has NULL. Don't use `LIKE 'w_%'`, where `_` is a wildcard, and don't use a substring of `id`.
   - **and** `NOT EXISTS (SELECT 1 FROM whoop_workouts WHERE id = unified_workouts.whoop_workout_id AND <predicate>)`. A correlated NOT EXISTS works the same on SQLite and Postgres.
   - Scope it to the user on both sides: `UnifiedWorkout.user_id` outside, `WhoopWorkout.user_id` inside. Mirror the existing `if self.user_id is not None` pattern.
   - Use SELECT, then ORM `db.delete(row)`, not a bulk `query.delete()`. Step 3 needs the deleted rows' `garmin_activity_id`, and the session already holds the objects that were just upserted.
3. **Re-home the Garmin activity.** Do this for each deleted row whose `garmin_activity_id` G is not null, after a flush. If no remaining unified row for this user has `garmin_activity_id = G`, and `GarminActivity` G exists for this user, upsert it as `g_G` with `map_garmin_workout` (same `last_updated`/`user_id` as the unmatched loop).
   - **Why:** the cleanup has no window, but the Garmin load does. Without this step, deleting `w_X` loses activity A entirely whenever A falls outside the current window, and incremental windows never revisit it. That happens in three cases:
     - a Garmin-only incremental run
     - the first run after deploy, which reaches every historical stale row
     - X and A straddling the UTC-midnight edge of the window (their starts can be up to 5 min apart)
   - **In-window ordering:** X no longer qualifies, so it isn't loaded. A therefore lands in `unmatched_garmin`, and `g_A` is upserted earlier in the same pass. Re-homing then finds `g_A` and skips.
4. Log how many rows were deleted and re-homed.

**Tests** (in `tests/test_integration.py`; build on `test_matched_workout_removes_garmin_only_row`):
- `test_rescored_whoop_workout_removes_stale_w_row`: match X↔A, then normalize again. Parametrize the change over `strain=None` and `sport_name="driving"`. Afterwards, the rows with `garmin_activity_id = A` are exactly `[g_A]`.
- `test_stale_w_row_outside_window_rehomes_garmin`: match X↔A on day D, set `X.strain=None`, then normalize a window that excludes D. `w_X` is gone and `g_A` exists.
- `test_deleted_whoop_workout_removes_stale_w_row`: cheap, since NOT EXISTS covers it. Nothing in `src/` deletes `whoop_workouts` today, and on Postgres the `whoop_workout_id` FK would block it anyway.
- `test_qualifying_w_rows_untouched`: one matched and one unmatched qualifying `w_` row, both outside the window, survive. With `Normalizer(db, user_id="u1")`, a stale-looking `w_` row owned by `u2` survives too.

Commit: `fix: drop unified rows for Whoop workouts that no longer qualify (no double count)`.

### Task 2: Training workout log scroll container

**Problem:** `frontend-react/src/pages/Training.tsx:929` uses react-virtuoso with `useWindowScroll`. `components/layout/Layout.tsx:140-155` makes `<main>` the scroll container (`flex-1 overflow-y-auto`) inside an `h-screen overflow-hidden` wrapper. The window never scrolls, so Virtuoso may render nothing, or only the first rows. This is the only virtualized list in the app.

**Fix:**
- In `Layout.tsx`, hold the element in state, not a ref: `const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null)` with `<main ref={setScrollEl}>`. Provide it through a small `ScrollContainerContext` (preferred over `document.querySelector`).
  - **Why state:** a RefObject's `.current` is still null while children render on first mount, and setting it doesn't re-render consumers. Virtuoso could mount with `undefined` and never pick up the element.
- In `Training.tsx`, replace `useWindowScroll` with `customScrollParent={scrollEl}`. They are alternatives, so don't pass both. Render the Virtuoso only once `scrollEl` is non-null.
  - The installed react-virtuoso is 4.18.20 (per the lock file); its `VirtuosoProps` has `customScrollParent?: HTMLElement`.
- `computeItemKey={(_, w) => w.id}` is **already present** (`Training.tsx:931`). Nothing to do there.
- Verify typecheck and build. Browser verification happens in Task 3.

Commit: `fix(frontend): workout log virtualizes against the main scroll container`.

### Task 3: Browser QA pass (throwaway DB, live Garmin data)

**Setup.** No commits in this step. `SP` below is the scratchpad path from Global Constraints.
1. **Env vars don't persist between Bash calls**, so a one-off `export` won't last. Write `SP/qa-env.sh`, which exports two variables:
   - `DATABASE_URL=sqlite:///` followed by the absolute path `SP/qa.db` (four slashes in total)
   - `PORT=8002`

   Start **every** QA Bash command with `source SP/qa-env.sh &&`; a command without it hits `data/fitness_dashboard.db`. Before anything writes, run `.venv/bin/python -c "from config.settings import settings; print(settings.database_url, settings.app_port)"` and confirm it prints the qa.db URL and 8002. `load_dotenv()` doesn't override env vars that are already set, so these beat `.env`.
2. Create the owner with a wrapper script in `SP`. It calls `scripts/create_owner.py` in-process, since that script has no password flag and calls `getpass` twice:
   - generate the password with `secrets.token_urlsafe(15)` (20 characters)
   - write it to `SP/qa-credentials.txt` and `chmod 600` it
   - patch `scripts.create_owner.getpass.getpass` with `side_effect=[pw, pw]`
   - call `create_owner.main(["--email", "qa@example.com"])` and exit with its code
   - **print nothing except the exit code**
   - imports from `SP` work because the venv's `.pth` file puts the repo root on `sys.path`
   - `qa@example.com` passes the `EmailStr` check (verified)
   - `create_owner` runs the migrations, which creates `qa.db`
3. Run `.venv/bin/python scripts/backfill.py --source garmin --start <today−90>` from the repo root, in the background.
   - Use `PORT=8002` from `qa-env.sh` and **no `--force`**. The API-running probe hits `settings.app_port`, so it checks the QA port, which is still empty, and keeps its guard.
   - With the default port it would probe 8001 and exit 3 if SJ's own instance is up. `--force` skips the probe entirely.
   - The real key is in `.env`.
   - Record the exit code (expect 0), the chunk statuses, and the row counts.
4. Start the app with `make run PORT=8002` from the repo root, in the background (after sourcing `qa-env.sh`). Wait until `curl -s localhost:8002/api/health` answers.
   - `make run` rebuilds `dist/` when any file under `frontend-react/src` is newer than `dist/index.html`, so it serves the Task 2 build. Confirm the log shows a build, or that `dist/index.html` is newer than the Task 2 commit.
   - The scheduler runs its 30-minute live Garmin sync against `qa.db` while QA is in progress. That is harmless.

**Browser** (Claude in Chrome tools):
- Open a new tab at `http://localhost:8002` (not 127.0.0.1) and log in.
  - **Password hygiene:** typing it puts the value in that one tool call, which can't be avoided with these tools. Read the file only at the moment of login. Type with `computer` `type`, with an `action_summary` that leaves out the value. Never echo it in Bash output, the report, a commit or a screenshot. It is a throwaway localhost account, and its DB is deleted at teardown.
- Visit Today, Training, Recovery, Insights and Settings.
- On each page:
  - take an inline screenshot, **without `save_to_disk`**: the screenshots show health values, and this leaves nothing to clean up
  - read console errors (`read_console_messages`, pattern `error|Error|warn`)
  - read API failures (`read_network_requests`): any `/api/*` response other than 2xx
  - note visual breakage, endless spinners, NaN or "undefined" text, and empty states
- Specifically check:
  - **Training log:** pick **60d**, the widest range (Training offers 7/14/30/60). Confirm the count is at least 30, enough that the list outruns the viewport plus Virtuoso's 400px overscan. Scroll `<main>` to the bottom and confirm the last rows render.
  - expanding a strength workout shows the per-exercise summary table
  - **Garmin-only states:**
    - Today: the readiness gauge shows a score with redistributed weights, or a clear "not enough data" state. Never NaN or a stuck spinner.
    - Recovery: the sleep and recovery-activity sections show empty states, since there is no Whoop and the watch isn't worn at night.
    - Insights: the anomaly feed shows Garmin metrics with sensible units and copy, and correlations show empty states.
  - **Scroll on navigation:** scroll Training down, then open Insights. It should start at the top. `<main>` persists across routes and nothing resets its `scrollTop`.
  - the Settings Garmin card shows Connected
  - the Whoop card shows "Connect Whoop", not an error
  - the sleep target control loads and saves: change it to 7.5h and back to 8h
  - deep links `/privacy` and `/demo` redirect to `/` (catch-all route)
  - **401 refresh path:** tokens live in `localStorage` key `pd_auth`, not in memory as CLAUDE.md says.
    - With `javascript_tool`, change the last characters of `access_token`. That breaks the signature but keeps `exp`, so the client doesn't refresh proactively. The script returns only `'ok'`, never the token.
    - Reload. Expect one `/api/auth/refresh` 200, retried calls returning 200, and no redirect to `/login`.
  - **Mobile width:** `resize_window` to about 500×900. That is below the `lg` breakpoint of 1024; Chrome may clamp narrower sizes. Check the bottom tab bar, that there is no horizontal scroll, and that the Training log still loads rows as you scroll. Then restore the original window size.
  - **Last:** logout returns to `/login` and clears `pd_auth`.
- Don't trigger browser dialogs; if a page has a confirm dialog, skip it.
- Don't click these:
  - data export (it is a download)
  - change password
  - Whoop connect or disconnect

**Write `docs/reviews/2026-11-07-qa.md`:**
- the environment, without credentials
- page by page: what rendered, console errors (messages only), and issues
- each issue with a severity and a suggested fix
- no health values

**Pause, don't tear down yet:**
- stop the server, and check that `lsof -nP -iTCP:8002 -sTCP:LISTEN` is empty
- close the tab
- **keep** `qa.db`, `qa-credentials.txt` and `qa-env.sh` for Task 4's re-verification, so that task doesn't need a second 90-day live backfill

Commit the report: `docs: Phase 9 browser QA report`.

### Task 4: Fix the QA findings

The controller triages the QA report. Fix the critical, high and medium findings that are behaviour-preserving, or that are clear bugs, each with a test where testable. Anything that needs a product call goes into CLAUDE.md "Open items".

Re-verify the fixed pages in the browser using the kept `qa.db`. Restart `make run PORT=8002` after each fix: it serves a fixed build and reloads no code. A restart picks up backend changes and rebuilds `dist/`.

**Final teardown:**
- stop the server and confirm port 8002 is free
- log out and close the tab
- delete `qa.db` (plus `-wal`/`-shm`), `qa-credentials.txt`, `qa-env.sh` and the wrapper script

Commit per logical fix.

### Task 5: Docs

Update `CLAUDE.md`. Touch `README.md` only if a Task 4 fix changes setup or usage; it has no test count and no Virtuoso note.
- Remove the Virtuoso open item and the "Parked: normalizer reverse-direction duplicate" open item.
- Replace the "**Known bug:**" line. It describes the forward `g_` duplicate, which `normalize_workouts` already handles. Write it as an alignment rule covering both directions:
  - a match deletes `g_<aid>`
  - a `w_` row whose source no longer passes the selection predicate is deleted, and its Garmin activity is re-homed as `g_<aid>`
- Fix the test counts in both places they appear (Status says 1022, Testing patterns says 972).
- Fix "auth token held in memory": it is `localStorage` `pd_auth`.
- Note the QA report under the docs map.

Commit: `docs: Phase 9`.

Order: 1 → 2 → 3 → 4 → 5.
