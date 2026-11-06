# Phase 3: SaaS Cut + Whoop Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the backend's multi-user and SaaS-only surface, bootstrap the single owner from a script, and fix the Whoop token, lock and window bugs. Afterwards the backend is a private, single-user API.

**Architecture:**
- Keep JWT login and the `user_id` plumbing (roadmap D1).
- Registration becomes `scripts/create_owner.py`.
- `get_current_user` accepts only the owner.
- Delete the routes, settings and tests for the waitlist, allowlist/feature-flags, account deletion, the Whoop webhook and the duplicate CSV route.
- Make the Whoop pipeline match Garmin: a non-blocking run lock, an incremental overlap, and serialized token refresh. A 401 no longer deletes the token; it records a "needs re-auth" state.

**Tech Stack:** Python 3.12 venv, FastAPI, SQLAlchemy 2, APScheduler 3, httpx, pytest (serial).

**Spec:** [`plans/2026-11-06-personal-relaunch-roadmap.md`](2026-11-06-personal-relaunch-roadmap.md) Phase 3, items 1–10. Supporting docs: research doc §7 (Whoop OAuth rotation), and `docs/reviews/2026-11-06-cleanup.md` (the decisions marked "with Phase 3.6": the Whoop overlap and run lock).

## Global Constraints

- Branch `feat/phase3-saas-cut` (cut from `main` after PR #1). **Phase 4 (frontend cleanup) lands on the same branch.** Until then the frontend may call deleted backend routes, so don't merge this branch on its own. The breakage is exactly this (verified by grep of `frontend-react/src`), and Phase 4 fixes it:
  - `pages/Login.tsx:31` register mode posts to `/api/auth/register` (Task 1).
  - `pages/Landing.tsx:147` posts to `/api/waitlist` (Task 2).
  - `useFeatureFlags` (`hooks/useApi.ts:331`), read by `Settings.tsx:121` and `ConnectDevicesPanel.tsx:119`, which default Whoop OAuth to **disabled** when the flag is missing, so the Whoop connect button is unavailable until Phase 4 (Task 3).
  - `useDeleteAccount` (`useApi.ts:448`) from `Settings.tsx:127` (Task 4).
  - `useCsvImport` (`useApi.ts:364`) posts to `/api/garmin/csv-import` (Task 7).
  - Nothing calls `/api/webhooks`. `useWhoopStatus` reads only `.connected`, which Task 6 keeps. `npm run typecheck` and `npm run build` stay green throughout, since nothing here changes TS types.
- No test registers through `POST /api/auth/register` (grep confirmed: zero hits). Every test mints tokens with `create_access_token(user_id)` directly, in per-module helpers (`_auth`, `_auth_header`); `tests/conftest.py` has no auth, engine or app fixture. Task 1's test work is therefore about **seeding a `users` row for the token's `sub`**, not about replacing registration calls.
- Never delete migration files or drop tables. Existing DBs have run them.
- Settled decisions (CLAUDE.md, roadmap) still bind:
  - single owner (D1)
  - polling only (D3)
  - the Garmin failure policy
  - `_RUN_LOCK`
  - `INCREMENTAL_OVERLAP_DAYS = 2` for Garmin
  - the Garmin export upload `POST /api/garmin/upload` stays
  - `transform_exercise_sets` stays
- Tests run serially (`.venv/bin/pytest -q`). xdist is broken. Baseline: **942 passed**. `make lint` must stay clean. `tests/conftest.py` blanks the Garmin key and sets a test `JWT_SECRET`.
- No secrets or personal data in git. Never log tokens, keys or passwords.
- Repo code-quality rules apply:
  - surgical changes
  - never swallow errors
  - type hints and docstrings
  - `datetime.UTC`

## Review Focus

1. **Stale token after a DB reset.** A valid JWT whose `sub` is not the owner must get 401, not an empty dashboard (Task 1 `test_non_owner_token_rejected`).
2. **Two concurrent Whoop syncs** (scheduled plus manual). Exactly one runs, one refresh POST happens, and no IntegrityError occurs (Task 6 `test_concurrent_run_skipped`, `test_concurrent_refresh_single_post`).
3. **A Whoop 401 or invalid refresh token.** The token row is kept, status shows "needs re-auth", and there is no tight retry loop (Task 6 `test_auth_failure_keeps_token_sets_needs_reauth`).
4. **Running `create_owner.py` twice, or with a user already present.** It refuses with a clear message and creates no second user (Task 1 `test_create_owner_refuses_second_user`).
5. **A Garmin-first, then Whoop, match.** The stale `g_<aid>` unified row is removed, so a workout is counted once (Task 9 `test_matched_workout_removes_garmin_only_row`).

---

## File map

| Task | Files |
|---|---|
| 1 Owner bootstrap | Create `scripts/create_owner.py`, `tests/test_create_owner.py`. Modify `src/api/routes/auth.py` (delete `POST /register`), `src/api/models.py` (delete the now-unused `UserCreate`), `src/auth/dependencies.py` (owner check), `src/database/owner.py` (cached lookup), `src/api/routes/sync.py` (delete the now-unreachable 403 owner check in `trigger_sync`, `:238–249`), `Makefile` (`owner` target + `.PHONY`), `tests/conftest.py` (autouse `clear_owner_cache()`), and the fixtures in `tests/test_data_isolation.py`, `tests/test_strength_routes.py`, `tests/test_sync_routes.py`, `tests/test_account_settings.py` (see Task 1) |
| 2 Waitlist | Delete `src/api/routes/waitlist.py`, `tests/test_waitlist.py` (move its two SPA-fallback tests, `test_root_path_is_publicly_accessible` `:267` and `test_login_page_is_publicly_accessible` `:276`, to a new `tests/test_spa_routes.py`). Modify `src/api/main.py` (router + `_NO_CACHE_PREFIXES`), `config/settings.py` (`admin_email`), `.env.example:32–33`, `README.md:14,78` |
| 3 Allowlist + flags | Modify `config/settings.py` (`whoop_public_oauth_enabled`, `whoop_allowed_user_ids`), `src/api/routes/auth.py` (allowlist gate `:225–234`, `GET /feature-flags` `:251–277`). No test covers either today; `.env.example` has no `WHOOP_*` flag lines to remove |
| 4 Account routes | Modify `src/api/routes/account.py` (delete `DELETE /api/account` `:120–182`; export adds `garmin_exercise_summaries`), `src/database/models.py` (delete the `GarminCredentials` model, `:355`; keep migration 010 and the table), `tests/test_account_settings.py` |
| 5 Webhook | Delete `src/api/routes/webhooks.py` (no tests exist). Modify `src/api/main.py:25,67,113`, `README.md:15,138–139`, CLAUDE.md "Whoop Webhook Setup" section |
| 6 Whoop hardening | Modify `src/clients/whoop_auth.py`, `src/clients/whoop_client.py` (persistent-401 path `:87–92`), `src/ingestion/whoop_pipeline.py`, `src/ingestion/scheduler.py`, `src/api/routes/auth.py` (`GET /whoop/status`), `src/api/routes/sync.py` (lock-skipped message), `scripts/initial_sync.py` (`run()` may now return `None`). Tests: `tests/test_whoop_auth.py`, `tests/test_whoop_pipeline.py`, `tests/test_scheduler.py`, `tests/test_sync_routes.py` or `tests/test_account_settings.py` (whichever already has a Whoop status client) |
| 7 CSV route | Delete `src/api/routes/garmin_csv.py`, `tests/test_garmin_csv_import.py`. Modify `src/api/main.py:15,111`, docstring mentions in `garmin_upload.py:4,19`. **Keep** `src/ingestion/garmin_csv_parser.py` (used by `garmin_upload.py:41` and `tests/test_garmin_csv_parser.py`) |
| 8 Streamlit + CORS | Delete `frontend/`. Modify `Dockerfile:38` (drop `COPY frontend/ ./frontend/`, or the image build breaks), `pyproject.toml:36` + `uv.lock` (drop `streamlit`), `Makefile` (`STREAMLIT` var `:3`, `run-frontend` `:7,12–13`), `src/api/main.py:92–99` (CORS only when configured), `config/settings.py` (`cors_origins` default `[]`, drop `streamlit_port` `:21,56`), `.env.example:22` (+ a new documented `CORS_ORIGINS=` line; none exists today), `README.md:50,149`, CLAUDE.md "Frontend — Streamlit Dashboard" section |
| 9 Follow-ups | Modify `src/normalization/normalizer.py` (stale `g_<aid>`), `scripts/initial_sync.py` (no owner → exit). Tests: `tests/test_integration.py` (the only file that exercises `normalize_workouts`; `tests/test_normalization.py` has no workout tests) and `tests/test_initial_sync.py` |

Order: **0 → 7 → 1** → 2 → 3 → 4 → 5 → 6 → 8 → 9.
- Task 0 is a security fix and goes first.
- Task 7 comes next because it deletes `tests/test_garmin_csv_import.py`, whose fixture mints a token with no `users` row. Doing it before Task 1 saves Task 1 a throwaway fixture edit in a file that's about to be deleted.

Each task leaves the suite green.

---

### Task 0: Harden `spa_fallback` (security; moved here from Phase 4 Task 5 by controller ruling)

The Phase 4 plan review reproduced a path traversal against a copy of the function. `GET /..%2F..%2Fdata%2Ffitness_dashboard.db` is served from outside `frontend-react/dist/`, because uvicorn unquotes `%2F` and doesn't strip dot segments. `docker-compose.yml` publishes `0.0.0.0:8000`, so anyone on the LAN can read the SQLite DB, Whoop tokens included.

The same catch-all also answers unknown `GET /api/*` with `index.html` and a 200. This task fixes that too, which lets the later `*_route_gone` tests assert 404s on GET routes.

**Interfaces:**
- In `src/api/main.py`, add a pure helper `_spa_file(dist: Path, full_path: str) -> Path | None`. It decides what the catch-all serves:
  - `full_path` under `api/` → `None`, and the route raises `HTTPException(404)`.
  - Otherwise, resolve the candidate path. Serve it only if it is a file **and** `resolved.is_relative_to(dist.resolve())`.
  - Anything else → `dist / "index.html"`.
  - Drop the sub-directory `index.html` case. `/demo` and `pulse-demo` are deleted in Phase 4 on this same branch.
- `spa_fallback` uses `_spa_file` and sends `index.html` (and `sw.js`, when present) with `Cache-Control: no-cache`. Hashed `/assets/*` files keep their defaults.

- [ ] **Step 1: Failing tests.** Create `tests/test_spa_routes.py` with unit tests for `_spa_file` against a `tmp_path` dist, so no built `dist/` is needed. Expected mappings:
  - `assets/x.js` → that file
  - `training` → `index.html`
  - `../secret.txt` (a sibling of dist) → `index.html`, never the secret
  - `..%2Fsecret.txt` already unquoted to `../secret.txt` → `index.html`
  - `demo`, a directory with its own `index.html` → the root `index.html`
  - `api/nope` → `None`
- [ ] **Step 2:** Run them and confirm they FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the full suite serially, then `make lint`.
- [ ] **Step 5:** Commit: `fix(security): confine spa_fallback to dist; 404 unknown /api/*`.

### Task 1: Owner bootstrap and closing registration

**Interfaces:**
- Produces:
  - `scripts/create_owner.py`: CLI `python scripts/create_owner.py --email you@example.com`. It reads the password with `getpass` (prompted twice, must match, ≥ 12 chars), hashes it with the existing `src/auth/security.py` helper, and inserts one `users` row the same way `/register` does today (`User(email=..., hashed_password=hash_password(pw))` via the ORM, so `id`, `created_at` and `is_active` get their model defaults).
    - `main(argv: list[str] | None = None) -> int` returns the exit code; `if __name__ == "__main__": sys.exit(main())`. Tests call `main([...])` and assert on the return value, not on `SystemExit`.
    - 0 on success. 2 with "an owner already exists" when any user row exists (check `get_owner_user_id(engine) is not None`, and treat its `RuntimeError` the same way). Non-zero with a message on mismatch or a short password; no row is created.
    - It runs migrations first the way `scripts/initial_sync.py:36–37` does: `engine = get_engine(); run_migrations(engine=engine)`. (The API's own startup path is `scripts/start.sh` for Postgres and import-time in `src/api/dependencies.py:16` for SQLite; neither is reusable from a script.)
    - It never prints the password. It calls `clear_owner_cache()` after the insert, which only matters when it runs in-process (tests); see the cache TTL below for the separate-process case.
    - `scripts/` is already a package (`scripts/__init__.py`), so tests import `from scripts.create_owner import main` and patch `scripts.create_owner.get_engine` to return an in-memory engine, plus `getpass.getpass`.
  - `src/database/owner.py`:
    - `get_owner_user_id` is unchanged (it still raises `RuntimeError` on > 1 users).
    - Add `get_owner_user_id_cached(engine: Engine) -> str | None`: a module-level `(owner_id, expires_at)` cache with a **60 s TTL** that caches **only a non-`None` result**. `None` (no users yet) is re-queried on every call, so `create_owner.py` running in a *separate process* is picked up at the next request without a restart. The TTL also bounds how long a stale id survives a DB wipe under a running API. One SELECT per minute keeps the "no DB round-trip per request" property that the current `get_current_user` docstring protects.
    - Add `clear_owner_cache() -> None`.
  - `src/auth/dependencies.py`: `get_current_user(credentials=Depends(_bearer), engine: Engine = Depends(get_engine_dep)) -> User`. It imports `get_engine_dep` from `src.api.dependencies` (no cycle: that module imports only `config` and `src.database`). Tests already override `get_engine_dep`, so the owner lookup hits the test engine. After the existing checks it rejects `sub != get_owner_user_id_cached(engine)` with 401 "Not the owner account". A `RuntimeError` from the lookup (> 1 users) is logged at ERROR and also mapped to that 401; nothing can authenticate against a misconfigured `users` table. With 0 users, every token gets 401 (correct: no user can hold a legitimate token).
  - `POST /api/auth/register` is deleted, with `UserCreate` in `src/api/models.py` (its only consumer). Keep `/login`, `/refresh`, `/me` and `/change-password`.
  - `src/api/routes/sync.py:238–249`: delete the 403 "owner only" check in `trigger_sync`. It is unreachable once `get_current_user` guarantees `current_user.id` is the owner.
  - `Makefile`: `owner:` target runs `$(PYTHON) scripts/create_owner.py --email $(EMAIL)`; add `owner` to `.PHONY`.
  - `tests/conftest.py`: an autouse fixture that calls `clear_owner_cache()` before each test. Without it the first module's owner id leaks into every later module (each test module builds its own engine and user ids).

- **Test fixtures affected by the owner check** (the rule: the token's `sub` must be the **only** `users` row; other users may own data rows but never a `users` row):
  - `tests/test_data_isolation.py`: `iso_engine` seeds data rows for A and B but **no `users` row**. Add one `users` row for `USER_A_ID`. All ten tests then pass unchanged, and they stay valuable: they guard the analytics `user_id` filters that D1 keeps.
  - `tests/test_strength_routes.py`: same — seed `USER_A` in `users`; `USER_B` keeps data rows only.
  - `tests/test_sync_routes.py`: `sync_client` seeds A **and** B in `users` → `RuntimeError` → every request 401s. Seed only A; B keeps its `sync_log` row (`test_status_scoped_to_requesting_user` still holds). Delete `test_trigger_for_user_a_does_not_block_user_b` (`:144`; no second user can authenticate), `test_manual_garmin_sync_rejected_for_non_owner` (`:213`) and `test_manual_garmin_sync_rejected_for_non_owner_single_other` (`:236`); the deleted 403 block was their subject, and `test_non_owner_token_rejected` covers the behaviour at the auth layer.
  - `tests/test_account_settings.py`: `test_disconnect_does_not_affect_other_user` (`:282`), `test_export_excludes_other_user_data` (`:337`) and `test_export_isolation` (`:548+`) must seed B's token/data rows without a B `users` row. The `TestDeleteAccount` class is Task 4's.
  - `tests/test_scheduler.py` multi-user tests call the scheduler directly, not the API; they are unaffected.

- [ ] **Step 1: Failing tests**
  - `test_create_owner_creates_user`: `main(["--email","a@b.test"])` with `getpass` patched returns 0. Exactly 1 user row exists afterwards, and `verify_password` succeeds against its `hashed_password`.
  - `test_create_owner_refuses_second_user`: run it twice. The second call returns 2, and the user count stays 1.
  - `test_create_owner_password_mismatch_or_short`: returns non-zero, and no row is created.
  - `test_register_route_gone`: `POST /api/auth/register` returns 404 or 405 (405 when `frontend-react/dist/` exists, because the GET-only `spa_fallback` catch-all matches the path).
  - `test_non_owner_token_rejected`: seed owner A and a JWT for `sub=B`. `GET /api/auth/me` returns 401.
  - `test_owner_token_accepted`: `/me` returns 200 for A.
  - `test_no_users_rejects_every_token`: empty `users` table, valid JWT → 401.
  - `test_owner_cache_sees_owner_created_after_first_request`: first request with no users → 401; insert the user row; the next request (same process, no `clear_owner_cache`) → 200. This pins the "don't cache `None`" rule.
  - Apply the fixture changes listed above.
- [ ] **Step 2:** Run them and confirm they FAIL.
- [ ] **Step 3:** Implement the changes.
- [ ] **Step 4:** Run the full suite and `make lint`.
- [ ] **Step 5:** Commit: `feat: owner bootstrap script; close registration; owner-only auth`.

### Task 2: Remove the waitlist

- [ ] Delete `src/api/routes/waitlist.py` and `tests/test_waitlist.py`. First move its two SPA-fallback tests (`test_root_path_is_publicly_accessible`, `test_login_page_is_publicly_accessible`) into `tests/test_spa_routes.py`, which Task 0 created. They test `main.py`, not the waitlist.
- [ ] Remove the router import and registration from `src/api/main.py` (`:24`, `:114`), and the `/api/waitlist` entry in `_NO_CACHE_PREFIXES` (`:67`).
- [ ] Remove `admin_email` from settings (`:45,69`), `ADMIN_EMAIL` from `.env.example` (`:32–33`) and the README line (`:78`). Keep migration 011 and the `waitlist` table.
- [ ] Test `test_waitlist_route_gone`: `POST /api/waitlist` returns 404 or 405.
- [ ] Run the full suite and lint, then commit: `chore: remove waitlist`.

### Task 3: Remove the Whoop allowlist and feature flags

- [ ] In `src/api/routes/auth.py`, delete the allowlist gate on `GET /whoop/url` (`:225–234`, including the local `settings` import) and the `GET /feature-flags` endpoint (`:251–277`; it had no auth dependency). Delete `whoop_public_oauth_enabled` and `whoop_allowed_user_ids` from settings (`:39–42`, `:65–68`). `.env.example` has no lines for them. `decode_token` stays imported (used by `/refresh`).
- [ ] Tests (there are no existing allowlist or feature-flag tests to delete):
  - `test_whoop_url_available_to_owner`: with `whoop_client_id` set, the owner gets 200 and a URL containing `state=`.
  - `test_feature_flags_route_gone`: returns 404 or 405.
- [ ] Run the suite and lint, then commit: `chore: remove Whoop allowlist and feature flags`.

### Task 4: Account routes

- [ ] Delete `DELETE /api/account` (`account.py:120–182`; it has no helpers of its own — `_rows_to_csv` belongs to export). Keep `GET /api/account/export`, and add `garmin_exercise_summaries.csv` to the ZIP: one more `SELECT * FROM garmin_exercise_summaries WHERE user_id = :uid ORDER BY activity_id, exercise_name` in the same `engine.connect()` block, one more `zf.writestr`, and the docstring's "four CSV files" becomes five.
- [ ] Delete the `GarminCredentials` model (`src/database/models.py:355`): after the cascade goes, nothing in `src/` references it (roadmap 3.4 "drop the model references, keep the table"). Migration 010 and the table stay.
- [ ] Tests:
  - `test_delete_account_route_gone`: `DELETE /api/account` returns 404 or 405.
  - `test_export_includes_exercise_summaries`: seed one summary row, and the ZIP contains the file with 1 data row.
  - Delete `TestDeleteAccount` (6 tests, `:429–`) and `test_delete_leaves_other_user_intact` (`:548`); keep `test_export_isolation` (it tests export). Remove the `garmin_credentials` seeding at `:115–119` and its assertions at `:441,471`.
- [ ] Run the suite and lint, then commit: `chore: drop account deletion; export includes exercise summaries`.

### Task 5: Remove the Whoop webhook

- [ ] Delete `src/api/routes/webhooks.py` and its registration (`main.py:25,113`). Remove `/api/webhooks/` from `_NO_CACHE_PREFIXES` (`:67`). No test covers the route. It was also the only caller of `Normalizer(db)` without a `user_id`, which simplifies Task 9.
- [ ] Remove the webhook mentions in `README.md:15,138–139` and the CLAUDE.md "Whoop Webhook Setup" section (replace with one line: polling only, D3).
- [ ] Test `test_webhook_routes_gone`: `POST /api/webhooks/whoop` returns 404 or 405.
- [ ] Run the suite and lint, then commit: `chore: remove Whoop webhook receiver (polling only, D3)`.

### Task 6: Whoop hardening (roadmap 3.6, plus the cleanup decisions "Whoop overlap + run lock")

**Interfaces:**
- `src/clients/whoop_auth.py`:
  - Add a module-level `_REFRESH_LOCK = threading.Lock()`. It must be a `threading.Lock`, because the scheduler runs the pipeline with `asyncio.run` on the APScheduler thread (`scheduler.py:145`) while manual syncs run on the FastAPI loop (`sync.py:165`): two event loops, one process. A plain `Lock` may be released from a different thread than the one that acquired it, which is what `to_thread` needs.
  - **The lock lives in `refresh_access_token`, not `get_valid_token`.** `WhoopClient._request` (`whoop_client.py:87–92`) calls `refresh_access_token` directly on a 401, so a lock only in `get_valid_token` would leave that path unserialized. New signature: `refresh_access_token(self, db: Session, user_id: str | None = None, *, force: bool = False) -> TokenStore`.
    - Acquire with `acquired = await asyncio.to_thread(_REFRESH_LOCK.acquire, True, 30)`; if `False`, raise `WhoopAuthError("Timed out waiting for Whoop token refresh")` so a stuck lock fails loudly instead of hanging. Release in `finally`.
    - After acquiring, **re-read the row**: `db.expire(record)` (or `db.expire_all()`) then `db.get(TokenStore, key)`. A bare `db.get` is not a re-read — it returns the identity-map copy without a query. The expired `get` re-selects and returns `None` if the row was deleted meanwhile (Whoop disconnect), which maps to the existing "No refresh token" `WhoopAuthError`. The session factory keeps SQLAlchemy's default `expire_on_commit=True`, so after another caller's `_store_tokens` commit the same session also sees fresh data.
    - If `not force` and the re-read row is no longer expired, return it **without POSTing** (another caller refreshed first). If `force` (the client's 401 retry), always POST, but with the **re-read** `refresh_token`, so a refresh rotated by the other loop a moment earlier is used rather than the stale one.
    - On a POST response of 400 or 401 (`invalid_grant`, revoked, bad client secret): call `set_whoop_auth_error(user_id, msg, db)` and raise `WhoopReauthRequired`. Other HTTP errors keep raising `WhoopAuthError` (transient; the token stays, the next run retries).
  - `get_valid_token` is unchanged in shape: fast path returns an unexpired token with no lock; when expired it calls `refresh_access_token(db, user_id=user_id)` (`force=False`).
  - `_store_tokens` keeps persisting a returned `refresh_token`. Fix its misleading comment (`:216`).
  - Add `class WhoopReauthRequired(WhoopAuthError)` — a subclass, so every existing `except WhoopAuthError` keeps working.
  - Add `whoop_auth_error(user_id: str | None, db: Session) -> str | None` and `set_whoop_auth_error(user_id: str | None, message: str | None, db: Session) -> None`. Both take `db`, like the rest of the module, and accept `user_id=None` (key `"whoop"`), which is how `tests/test_whoop_auth.py` builds `WhoopAuth()`. The state is the key `"auth_error"` inside that row's `token_data_json`, so it survives restarts and needs no migration. `set_...(None)` removes the key; no row → no-op. The only other reader of that column is the OAuth-state helper (`auth.py:176,208`), which stores a bare user id in `whoop_state_*` rows, never in `whoop_{uid}` rows, so there is no clash; still, `whoop_auth_error` must treat a NULL or non-JSON `token_data_json` as "no error" rather than raise. **Clearing on success needs no code:** `_store_tokens` overwrites `token_data_json` with Whoop's response (`:220`), so any successful refresh or exchange wipes the key by construction. The test below pins that.
- `src/clients/whoop_client.py:87–92`: the 401 retry calls `refresh_access_token(..., force=True)`. When the retried request still gets 401, call `set_whoop_auth_error` and raise `WhoopReauthRequired` instead of `WhoopAPIError("... re-authorize")` — otherwise that case (the old substring match caught it) would degrade to "unexpected error" every 30 min with no status. `WhoopReauthRequired` is raised at the source for both call paths (scheduler and manual), so the scheduler only logs; it does not need to record the state itself.
- `src/ingestion/whoop_pipeline.py`:
  - Add a module-level non-blocking `_RUN_LOCK`, with the same contract as Garmin (`garmin_pipeline.py:38,413–419`): `run()` becomes `-> SyncLog | None`; a skipped run returns `None` before `start_sync_log`, so no SyncLog is written and no client call happens. `_RUN_LOCK.acquire(blocking=False)` is synchronous and fine inside the coroutine. The run lock and the refresh lock are different objects.
  - Add `INCREMENTAL_OVERLAP_DAYS = 2` (not 24 h: cleanup M2 says "same overlap as Garmin", and a Whoop cycle can run past 24 h while its recovery and sleep scores land after the cycle starts, so 24 h can miss a re-score). `_get_sync_window` returns `(last_success.sync_end - 2 days, now)`. The pipeline already re-normalizes `sync_start.date()..sync_end.date()` (`:301`), so the overlap days are re-matched, which Task 9 relies on.
  - Callers of `run()` that now get `None`: `scheduler._run_whoop_sync` (`:145–146` reads `log.records_stored` — guard), `sync.py:_run_sync_task` (`:165` — log "skipped (another Whoop sync running)" like the Garmin branch), `scripts/initial_sync.py` (`_print_summary(log)` — guard).
- `src/ingestion/scheduler.py` `_run_whoop_sync`:
  - **Delete the "401"-substring token deletion** (`:149–169`) and the docstring sentence about removing the row.
  - Add a pre-check next to the existing `has_token` query: when `whoop_auth_error(owner, db)` is set, log INFO "needs re-auth — skipping" and return. Only a new OAuth exchange clears the state, so running would just spend one doomed refresh POST per tick against a revoked refresh token.
  - `except WhoopReauthRequired as exc:` log a WARNING with the message, and **keep** the token row. Keep the generic `except Exception: logger.exception(...)` after it.
  - On a `None` return, log INFO "skipped (another Whoop sync running)".
- `GET /api/auth/whoop/status` returns `{"connected": bool, "needs_reauth": bool, "error": str | None}`. This is a superset of today's `{connected}` (the only field the frontend reads).
- `src/api/routes/sync.py`: a manual Whoop run that returns `None` logs "skipped", like Garmin. A manual trigger while `needs_reauth` is set is still allowed; it fails the same way and re-sets the same state, which is harmless and lets the user retry after re-connecting.

- [ ] **Step 1: Failing tests** (follow the file's existing mocking style: `patch("src.clients.whoop_auth.httpx.AsyncClient")` with `post = AsyncMock(...)`, so the POST count is `post.await_count`)
  - `test_concurrent_refresh_single_post`: two `get_valid_token()` calls via `asyncio.gather` against an expired row produce exactly 1 refresh POST, and both callers get the new access token.
  - `test_forced_refresh_posts_even_when_unexpired`: `refresh_access_token(force=True)` on an unexpired row POSTs once and uses the stored `refresh_token`.
  - `test_refresh_persists_rotated_refresh_token`: a refresh response with a new `refresh_token` replaces the stored one.
  - `test_refresh_400_raises_reauth_and_keeps_row`: it raises `WhoopReauthRequired` (which is also an instance of `WhoopAuthError`), the token row still exists, and `whoop_auth_error(...)` returns the message.
  - `test_refresh_503_raises_auth_error_without_reauth_state`: a 503 raises plain `WhoopAuthError` and leaves `auth_error` unset.
  - `test_successful_refresh_clears_auth_error`: set the error, refresh successfully, `whoop_auth_error(...)` is `None`.
  - `test_client_persistent_401_raises_reauth` in `tests/test_whoop_client.py` (next to `test_401_triggers_token_refresh_and_retries`, `:151`): 401 → refresh → 401 again raises `WhoopReauthRequired`; also assert the existing test now sees `refresh_access_token` called with `force=True`.
  - `test_concurrent_run_skipped`: hold `whoop_pipeline._RUN_LOCK`. `run()` returns `None`, with no SyncLog and no client call.
  - `test_sync_window_overlaps_2_days`: a success with `sync_end = T` gives a next start of `T - 2 days`. Update `test_sync_window_uses_last_successful_sync` (`tests/test_whoop_pipeline.py:381`), which currently expects `T` exactly.
  - `test_auth_failure_keeps_token_sets_needs_reauth`: flips `test_whoop_token_failure_removes_token_and_continues` (`tests/test_scheduler.py:433`; its docstring already says "Phase 3 flips this"). The mocked `run` raises `WhoopReauthRequired`; the token row survives. `test_whoop_transient_failure_keeps_token` (`:451`) stays as is.
  - `test_whoop_job_skips_when_needs_reauth`: with `auth_error` set, `_run_whoop_sync` returns without constructing the pipeline.
  - `test_whoop_job_logs_skip_on_none`: the mocked `run` returns `None`; no exception, INFO logged.
  - `test_whoop_status_needs_reauth`: the route returns `{"connected": true, "needs_reauth": true, "error": "..."}` when the error is set, and `{"connected": true, "needs_reauth": false, "error": null}` otherwise.
- [ ] **Step 2:** Run them and confirm they FAIL.
- [ ] **Step 3:** Implement the changes.
- [ ] **Step 4:** Run the full suite and lint.
- [ ] **Step 5:** Commit: `fix: serialize Whoop refresh, run lock + 2-day overlap, keep token on 401 (needs re-auth)`.

### Task 7: One Garmin import route

- [ ] Delete `src/api/routes/garmin_csv.py` and `tests/test_garmin_csv_import.py` (22 tests), and unregister the router (`main.py:15,111`).
- [ ] `garmin_upload.py` stays untouched apart from its docstrings (`:4,19` mention `csv-import`). Verified: it imports **nothing** from `garmin_csv.py` — it carries its own copies of the dedup helpers and imports `parse_activities_csv` from `src/ingestion/garmin_csv_parser.py`. `main.py` is the only importer of `garmin_csv`.
- [ ] Test `test_csv_import_route_gone`: `POST /api/garmin/csv-import` returns 404 or 405. There is no `tests/test_garmin_upload*.py` today; `tests/test_garmin_csv_parser.py` and `tests/test_csv_import.py` cover the ingestion modules and stay.
- [ ] Run the suite and lint, then commit: `chore: remove duplicate /api/garmin/csv-import route`.

### Task 8: Delete the legacy Streamlit app and default CORS to same-origin

- [ ] Delete `frontend/` and the `COPY frontend/ ./frontend/` line in `Dockerfile:38` (the image build fails otherwise). No test imports from `frontend/` or mentions `streamlit`.
- [ ] Drop `streamlit` from the dev group in `pyproject.toml:36`, then refresh `uv.lock`. Use the scratchpad uv at `/private/tmp/claude-501/-Volumes-Dock-Storage-Projects-garmin-whoop-dashboard/26b4f8fc-46fc-434b-bfa6-ea5ddc08c3fd/scratchpad/uvenv/bin/uv lock`, then `uv sync --frozen`. (If that copy is gone, `brew install uv` — roadmap Phase 0.)
- [ ] Remove `make run-frontend` and the `STREAMLIT` variable (`Makefile:3,7,12–13`), `streamlit_port` (`settings.py:21,56`), `STREAMLIT_PORT` (`.env.example:22`), `README.md:50,149` and the CLAUDE.md "Frontend — Streamlit Dashboard" section.
- [ ] CORS: `settings.py:57` currently parses `CORS_ORIGINS` with default `"*"`; change the default to `""` (the existing comprehension already yields `[]` for an empty string). In `src/api/main.py:92–99` delete the no-op ternary and add `CORSMiddleware` only when the list is non-empty. Same-origin is the default: `VITE_API_URL` defaults to `''` (same host) and the Vite dev server proxies `/api` to port 8000 (`vite.config.ts:64–70`), so neither prod nor dev needs CORS headers. Add a commented `CORS_ORIGINS=` line to `.env.example` (nothing documents it today).
- [ ] Tests (there is no existing CORS test):
  - `test_no_cors_header_by_default`: no `access-control-allow-origin` header on `GET /api/health` with an `Origin` header sent and `CORS_ORIGINS` unset.
  - `test_cors_when_configured`: `app` is built at import time, so don't rebuild it. Factor the add-middleware call into `install_cors(app: FastAPI, origins: list[str]) -> None` in `main.py`, call it on a throwaway `FastAPI()` with `["http://x.test"]` in the test, and assert the header on a request from that origin.
- [ ] Run the suite and lint, then commit: `chore: delete legacy Streamlit app; CORS off unless CORS_ORIGINS set`.

### Task 9: Follow-ups (roadmap Phase 3 item 10)

- [ ] **Normalizer stale `g_<aid>`.** Verified against `normalizer.py:268–308` and `deduplication.py`: matching is pure and recomputed from the source tables on every run (nothing persists matches except the unified row itself); Garmin-only rows are exactly the unclaimed activities (`deduplication.py:182`); the whole function is one session with a single commit at `:308`; and nothing ever deletes a unified row, so Garmin-first-then-Whoop leaves `g_<aid>` and `w_<wid>` side by side with the same `garmin_activity_id`. The strength volume queries (`workouts.py:85,96,138,150`) join on `uw.garmin_activity_id` inside a SUM, so the duplicate double-counts.
  - Fix, in the match loop (`:268–299`): after upserting the matched `w_<wid>` row, `stale = self._db.get(UnifiedWorkout, f"g_{aid}")`; if present, `self._db.delete(stale)`. A primary-key lookup needs no `user_id` filter (ids are globally unique), so the `user_id=None` normalizer still works. It lands before the existing single commit, so "same transaction" holds.
  - The reverse case (a match that later falls apart, or is stolen by another Whoop workout) needs no code: `whoop_mapper.py:190,204,206` resets `garmin_activity_id=None, matched=False, primary_source="whoop"` on every re-upsert of `w_<wid>`, and the Garmin-only branch recreates `g_<aid>`.
  - No production data cleanup is needed: the DB is rebuilt from scratch in Phase 6.
  - Test `test_matched_workout_removes_garmin_only_row` in `tests/test_integration.py` (next to `test_cross_source_workout_match_creates_unified_row`, `:285`): normalize with only the Garmin activity, assert `g_<aid>` exists. Add the matching Whoop workout and normalize the same window again. Assert `SELECT COUNT(*) FROM unified_workouts WHERE garmin_activity_id = :aid` is 1, that row's `id` is `w_<wid>`, and `g_<aid>` is gone. Row multiplicity is what the SUM joins multiply by, so the count of 1 is the double-count invariant.
- [ ] **`scripts/initial_sync.py`.** `main()` is `async def main() -> None` (`:35`); it already calls `get_owner_user_id(engine)` (`:39`) and passes a possibly-`None` owner to both pipelines. When it is `None`, print "No owner account. Run `make owner EMAIL=...` first." and `sys.exit(1)` before constructing either pipeline. Test `test_initial_sync_exits_without_owner` in `tests/test_initial_sync.py`: patch `scripts.initial_sync.get_engine` to return a fresh in-memory engine (`main` runs migrations itself), patch `WhoopPipeline` and `GarminPipeline`, run `asyncio.run(main())` under `pytest.raises(SystemExit)` with `.value.code == 1`, and assert neither pipeline class was constructed.
- [ ] Run the suite and lint, then commit: `fix: remove stale Garmin-only unified row on match; initial_sync requires owner`.

---

**Done when:**
- The full suite is green and lint is clean.
- `git grep -n -E "waitlist|feature-flags|/register|webhooks|WHOOP_ALLOWED|ADMIN_EMAIL|streamlit" -- src scripts config tests Makefile pyproject.toml .env.example Dockerfile` returns only migration files and the `*_route_gone` tests added by Tasks 1–7 (which necessarily name the deleted paths).
- `docker build .` still succeeds (Task 8 touches the Dockerfile).
- The Review Focus tests pass.
