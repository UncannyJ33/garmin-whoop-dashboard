# Phase 8: Product Decisions and Deferred Items, Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the product decisions SJ made on 2026-11-07, then clear the deferred technical items left from Phases 5–6.

**SJ's decisions (binding):**
1. Anomaly alerts: detection uses a proper lookback, so recent days aren't wiped.
2. Workout dates: every workout is dated by its **local** start time.
3. Auth: a 401 triggers a silent refresh with the stored 30-day refresh token, then one retry.
4. The sleep target is stored server-side and used for sleep debt and the "of Xh target" copy.
5. Today's "Last Night's Sleep" includes the sleep that ended this morning.
6. Error boundaries are per page: navigation keeps working, and the error clears on a route change.

(Default port 8001 was already done directly on `main`.)

**Deferred items** from earlier reviews:
- Backfill does redundant work: it normalizes twice and refreshes anomalies per chunk.
- The Garmin backfill keeps calling the daily endpoints past the history depth.
- The `create_owner` `:memory:` guard blocks the `sqlalchemy<2.1` pin from being lifted.
- The test suite emits 28 warnings.

**Spec:**
- SJ's answers above.
- `docs/reviews/2026-11-06-cleanup.md`, findings H3 and M1 (anomalies), M6 (UTC/local workout date), M19 (refresh-on-401), L43 (sleep target), M17 (Today filter), L41 (error boundary).
- `CLAUDE.md` alignment rules: daily rows are keyed by `DATE(whoop_cycles.start_time)`, sleep by the wake date. Task 2 changes both to **local** dates; Task 9 updates the rule text.
- Reviewed 2026-11-07 (Fable). Findings verified against the code are folded into the tasks below.

## Global Constraints

- Branch `feat/phase8-decisions`, cut from `main` (which includes the port-8001 commit). Baseline is **983 passed** (serial `.venv/bin/pytest -q`; xdist is broken). `make lint`, frontend `npm run typecheck` and `npm run build` must stay clean.
- Never delete migrations or drop tables. A new column needs an idempotent migration **015** (SQLite and Postgres) following the `_add_column_if_missing` pattern in `005_postgresql.py` (014 is a create-table migration and is the wrong template), registered in `src/database/migrations/__init__.py`.
- Settled decisions still bind: single owner (D1), polling only (D3), the Garmin failure policy, the run locks, the incremental overlaps, and the max-`sync_end` window.
- No secrets or personal data in git. Repo code-quality rules: surgical changes, never swallow errors, type hints and docstrings, `datetime.UTC`.
- Pipeline `run()` gains keyword-only arguments in Task 7; tests that fake `run` with `lambda start, end:` (`tests/test_backfill.py`) must accept `**kw`.

## Review Focus

1. **A recovery drop on the last synced day** shows up as an anomaly after an incremental sync. Today it never does. (Task 1 `test_incremental_refresh_flags_latest_day`.)
2. **A 9 pm local workout** in a UTC−5 zone is dated that day, for Whoop-matched and Garmin-only workouts alike. The daily strain sum (`fetch_daily_strain`) and ACWR for that day include it. (Task 2 `test_evening_workout_local_date_*`.)
3. **Two queries 401 at the same time** trigger exactly one refresh call; both retry with the new token. A failed refresh logs out once. (Task 3, documented behaviour plus a manual check; there is no frontend test runner.)
4. **A sleep target of 7 h:** sleep debt in `/api/sleep/insights` is computed against 420 min, the Recovery copy says "7h", and the change is visible immediately (no 5-minute HTTP-cache lag). (Task 4 `test_sleep_debt_uses_user_target`.)
5. **A crash on one page** leaves the sidebar working, and navigating away clears the error. (Task 6 manual check, recorded in the report.)
6. **A 23:00 local bedtime** shows on the Recovery consistency card as 23:00, not as 04:00 UTC. (Task 2 `test_sleep_consistency_uses_local_hours`.)

## Order and dependencies

1 → 2 → 4 → 8 → 7 (backend), then 3 → 5 → 6 (frontend), then 9.

- 1 before 7: the backfill's single final `refresh_anomalies` pass is only correct once detection uses the lookback.
- 2 before 7: both edit `normalizer.py`; Task 7 adds the `refresh_anomalies` flag after Task 2's key changes land.
- 4 before 8: migration 015 and its test exist before the SQLAlchemy 2.1 full-suite run.
- 1 and 2 don't interact: anomaly detection reads unified tables by `date`, and Task 1's tests seed unified rows directly.
- 3, 5 and 6 are independent of each other and of 4's hooks.

---

### Task 1: Anomaly lookback (decision 1)

**Problem:**
- `src/analytics/anomaly_store.py` `refresh_anomalies(engine, user_id, start_date, end_date)` deletes cached rows in `[start_date, end_date]` and re-inserts what detection returns for that window.
- `detect_anomalies` needs 7 prior non-None values. With 1–3-day incremental windows, nothing is ever flagged and recent anomalies get wiped.
- Root cause (verified): `get_metric_trend` and `get_batch_metric_trends` already fetch a 29-day lookback, but `src/analytics/trends.py` `_build_trend_from_calendar` slices the calendar to `start_idx` **before** calling `detect_anomalies`, so the lookback is used for rolling averages only. `refresh_anomalies` calls `get_batch_metric_trends(…, start_date, end_date)` and inherits the bug.

**Interfaces:**
- `trends.py` `_build_trend_from_calendar(metric_name, full_calendar, start_date)`: call `detect_anomalies(all_values, all_dates)` on the full calendar, then keep `[a for a in anomalies if a["date"] >= start_iso]`. Rolling averages, the `dates`/`values` slicing and the `MetricTrend` shape are unchanged. This one change fixes `get_metric_trend` (M1), `get_batch_metric_trends`, `refresh_anomalies` (H3) and the live fallback in `GET /api/trends/anomalies`. `_get_notable_anomalies` already does lookback-then-filter; leave it.
- `anomaly_store.refresh_anomalies`: **no range change.** Do not pass `start_date − 29 days` into `get_batch_metric_trends`; it subtracts 29 days itself, so that would double the lookback and return anomalies before `start_date`, which `_delete_range` never clears. Delete and insert stay bounded to `[start_date, end_date]`. Update the docstring: detection uses the 29-day lookback inside `get_batch_metric_trends`; only rows in the window are rewritten.
- Incremental windows: pipelines call `refresh_anomalies(start, end)` with the sync window (`latest sync_end − 2 days` → today). Rows before `start` are untouched, so anomalies persist across syncs; rows in the window are recomputed with full history, so a re-score inside the 2-day overlap clears a resolved anomaly. The backfill's final pass over `[START, today]` recomputes everything.
- `detect_anomalies` skips a day whose prior window has `std == 0`; test seeds need jitter (e.g. 60/62/58 alternating), not a flat value.

**Tests:**
- New `tests/test_anomaly_store.py` (engine fixture with migrations run so `anomaly_cache` exists; use one in-memory engine per the testing pattern):
  - `test_incremental_refresh_flags_latest_day`: seed 30 days of jittered `unified_daily.whoop_recovery_score` around 60, then 20 on the last day; `refresh_anomalies(engine, uid, last, last) >= 1` and `get_cached_anomalies(engine, uid, last, last)` has an item with `direction == "low"` and `metric == _ENRICHED_METRIC_LABELS["recovery"]`.
  - `test_refresh_does_not_touch_rows_outside_window`: insert a cache row dated `last − 10`; refresh over `[last, last]`; the row is still present.
  - `test_refresh_clears_resolved_anomaly_in_window`: a cache row on `last` whose value is now normal is gone after the refresh.
- `tests/test_trends.py`: `test_trend_anomalies_use_lookback` (`get_metric_trend` over a 3-day range flags day 1 when the prior 28 days set the baseline) and `test_trend_anomalies_within_range` (every anomaly date `>= start_date`, for both `get_metric_trend` and `get_batch_metric_trends`). `TestDetectAnomalies` is unchanged (`detect_anomalies` itself doesn't change).

Commit: `fix: anomaly detection uses its lookback; incremental refresh no longer wipes recent anomalies`.

### Task 2: Local-time Whoop dates (decision 2)

**Problem (verified):** Whoop timestamps are UTC ISO strings; every Whoop row carries `timezone_offset` (e.g. `"-05:00"`, stored by `transform_cycle/sleep/workout`; `models.py:18/63/92`). Garmin rows are already local (`garmin_activities.start_time` = `startTimeLocal`; `garmin_daily_summary.date` and `garmin_sleep.date` are Garmin calendar dates). Whoop-derived dates and clock times are UTC in four places:
- `whoop_mapper.map_whoop_workout` (`workout.start_time[:10]`), the finding in M6.
- `normalizer._prefetch_range`: `cycles_by_date` keyed by `start_time[:10]` (daily key) and `sleep_by_end_date` by `end_time[:10]` (wake key). A 6 am-local wake in UTC+7 or later lands on the previous UTC date.
- `src/api/routes/recovery.py`: `act_date = row["start_time"][:10]` and `_ALL_RECOVERY_DATES_QUERY`'s `SUBSTR(start_time, 1, 10)` date recovery activities (strain-null) in UTC, which breaks the next-day join for evening sessions.
- `sleep_analysis.get_sleep_consistency` reads bedtime/wake hours from the UTC string (`_time_str_to_fractional_hours`): a 23:00 local bedtime in UTC−5 becomes 04:00, which the "<12 → +24" rule then averages as 28, so the card shows a 4 am bedtime.

**Scope decision:** every Whoop-derived date and clock time becomes local: workout date, daily key, sleep (wake) key, recovery-activity date, bedtime/wake hours. Garmin alignment improves (local vs local). Deduplication is unaffected: `match_workouts` compares parsed instants (`_parse_dt`), never dates; confirm by reading, no change. Analytics (readiness, training load, sleep insights, trends, anomalies) read unified tables by `date` and need no change. **Controller ruling R26:** `_prefetch_range`'s `vo2_by_date` also switches to the activity's local date: group by `start_time[:10]`, which is `startTimeLocal`, instead of `start_time_gmt[:10]`. That leaves no UTC date keys anywhere, and it's a one-line change. Add an assertion to an existing VO2 test, or a small new one. `comparison_tool.py` (dev-only) keeps `DATE(...)`; one docstring line.

**Interfaces:**
- `src/normalization/whoop_mapper.py`:
  - `local_datetime(ts_iso: str, tz_offset: str | None) -> datetime | None`: parse the UTC ISO string (`Z` or `+00:00`, with or without fractional seconds), apply the offset, return a **naive local** datetime. Offset formats `±HH:MM`, `±HHMM`, `Z`. Missing offset → UTC and `logger.debug`; unparseable offset → UTC and `logger.warning` with the value; unparseable timestamp → `None` and `logger.warning`.
  - `local_date(ts_iso: str, tz_offset: str | None) -> str | None` = `local_datetime(...).date().isoformat()`.
  - `map_whoop_workout`: `date = local_date(workout.start_time, workout.timezone_offset)`. The `start_time`/`end_time` columns stay UTC ISO.
- `src/normalization/normalizer.py`:
  - `_prefetch_range(start, end)`: widen the Whoop cycle and non-nap sleep queries by one day on each side (`>= (start − 1 day)` and `< (end + 2 days)` as bare-date strings, same trick as today), since a local date can sit on the neighbouring UTC date. Key `cycles_by_date` by `local_date(c.start_time, c.timezone_offset)` and `sleep_by_end_date` by `local_date(s.end_time, s.timezone_offset)`. Dates outside `[start, end]` are prefetched but never looked up. Garmin lookups unchanged.
  - `normalize_daily(target_date)` / `normalize_sleep(target_date)` are called only by `tests/test_normalization.py`. Reimplement each as `self._normalize_daily_from_cache(target_date, self._prefetch_range(target_date, target_date))` (and the sleep twin) so there is one key derivation; keep signatures and docstrings.
  - `normalize_workouts(start, end)`: query bounds stay UTC and unwidened. A local-`end` evening workout (UTC `end + 1`) is normalized by the next window: incremental windows end at the UTC date, which is already the next local day after about 19:00 US local, and backfill chunks are contiguous. Its matched Garmin activity sits at the same instant, so the pair is always normalized together. Say this in the method docstring.
- `src/api/routes/recovery.py`: select `ww.timezone_offset` in `_ACTIVITY_QUERY` and `_ALL_RECOVERY_DATES_QUERY` (drop the `SUBSTR`), widen `_ACTIVITY_QUERY`'s UTC bounds by one day each side, compute `act_date = local_date(start_time, timezone_offset)` in Python and keep rows with `start <= act_date <= end`. `rec_dates` becomes the set of local dates. The module already prefers Python for date arithmetic.
- `src/analytics/sleep_analysis.py`: `_fetch_whoop_sleep_times` also selects `timezone_offset` and widens its `end_time` bounds by one day each side, then filters on the local wake date in Python (same rule as the normalizer). `get_sleep_consistency` converts `start_time`/`end_time` with `local_datetime` before extracting hours (pass `dt.isoformat()` to `_time_str_to_fractional_hours`, or add `_fractional_hours(dt: datetime) -> float`).
- DST: `timezone_offset` is per record (Whoop reports the offset in force for that record), so DST needs no tz database. A sleep spanning the switch can be off by one hour at the wake end, which only matters for a wake within an hour of midnight. Accept; one docstring line.
- Missing `timezone_offset` (old rows): falls back to the UTC date at DEBUG. The DB is fresh, so there is no row migration; SJ's first backfill writes everything with the new keys, and incremental `normalize_all` rewrites its window.

**Tests:**
- `test_local_date_helper` (parametrised): `"2026-11-07T02:00:00Z"` with `"-05:00"` → `"2026-11-06"`, with `"+09:00"` → `"2026-11-07"`, with `"+0900"` → `"2026-11-07"`, with `"Z"` → `"2026-11-07"`, with `None` → `"2026-11-07"`; `"2024-03-03T03:50:11.610Z"` with `"-06:00"` → `"2024-03-02"`; garbage offset `"abc"` → UTC date and a WARNING record (`caplog`).
- `test_evening_workout_local_date_whoop_matched` and `_garmin_only`: Whoop workout `start_time="2026-11-08T02:00:00Z"`, `timezone_offset="-05:00"`, strain set; Garmin activity `start_time="2026-11-07 21:00:00"`, `start_time_gmt="2026-11-08 02:00:00"`. `normalize_workouts(date(2026,11,7), date(2026,11,8))`: both rows have `date == "2026-11-07"`; the matched row has `matched is True`; `fetch_daily_strain(engine, date(2026,11,7), date(2026,11,7), uid)` includes the strain (Review Focus 2).
- `test_prefetch_keys_daily_and_sleep_by_local_date`: cycle `start_time="2026-11-06T21:00:00Z"`, `timezone_offset="+09:00"` (06:00 local on 11-07); non-nap sleep `end_time="2026-11-06T21:30:00Z"`, `"+09:00"`. `normalize_all(date(2026,11,7), date(2026,11,7))` writes `unified_daily["2026-11-07"]` and `unified_sleep["2026-11-07"]`; nothing is written for 11-06.
- `test_recovery_activity_dated_locally` (add beside the `/api/recovery` tests in `tests/test_data_isolation.py`, or a new `tests/test_recovery_routes.py`): a strain-null yoga at `02:00Z` with `"-05:00"` lists with `date` of the previous local day, and `with_without` treats that day as a recovery day.
- `test_sleep_consistency_uses_local_hours`: seven nights with `start_time` at `04:00Z`, `end_time` at `12:00Z`, `"-05:00"` → `avg_bedtime_hour ≈ 23.0`, `avg_wake_hour ≈ 7.0`.
- Existing tests to update (list them in the report):
  - `tests/test_integration.py::test_whoop_pipeline_populates_unified_tables` (~lines 205–248): the cycle fixture starts `2024-03-03T03:50:11.610Z` with `"-06:00"` (21:50 local on 03-02), so the daily row would move to `2024-03-02` and fall outside the `[03-03, 03-03]` window. Change the cycle start to a wake-like `2024-03-03T12:50:11.610Z` (06:50 local) and keep the `2024-03-03` assertion. The sleep (`07:30Z` → 01:30 local 03-03) and the 14:00Z workout are unaffected.
  - `tests/test_normalization.py` rows have no `timezone_offset`, so they fall back to the UTC date and keep passing; add `timezone_offset="-06:00"` to one cycle and one sleep fixture there so `normalize_daily`/`normalize_sleep` exercise the local path (pick times that keep the asserted keys).

Commit: `fix: date Whoop workouts, daily and sleep keys, and sleep hours by local time`.

### Task 3: Silent token refresh on 401 (decision 3)

**Read first (verified):** `frontend-react/src/api/client.ts` holds only the access token (`_authToken`, set by `TokenSync`), dispatches `auth-error` on 401 and `AuthProvider.logout()` handles it. `context/AuthContext.tsx` keeps `{access_token, refresh_token, expires_at}` in `localStorage["pd_auth"]` and already runs a mount-time refresh (`POST /api/auth/refresh` with `Authorization: Bearer <refresh_token>`) when the access token is expired at load. `/api/auth/refresh` returns a full `TokenResponse` with a **new** refresh token; tokens are stateless JWTs, so an older refresh token stays valid until its own expiry and rotation cannot lock anyone out. Don't change the storage model.

**Interfaces:**
- `client.ts`:
  - `export function setRefreshHandler(fn: (() => Promise<string | null>) | null): void`; module-level `_refreshInFlight: Promise<string | null> | null`.
  - `refreshAccessToken(): Promise<string | null>`: single-flight, `_refreshInFlight ??= handler().finally(() => { _refreshInFlight = null })`; `null` when no handler is registered.
  - `request<T>(path, options, { retried = false } = {})`: on 401, if `path.startsWith('/api/auth/refresh') || path.startsWith('/api/auth/login') || retried || !handler` → dispatch `auth-error` and throw (today's behaviour). Otherwise `const token = await refreshAccessToken()`; `null` → dispatch `auth-error` once and throw; a token → `setAuthToken(token)` and `return request(path, options, { retried: true })`.
  - `api.download` keeps its own `fetch` and gets no retry (manual export only); say so in its comment.
- `AuthContext.tsx`:
  - `refreshTokens(): Promise<string | null>` (`useCallback`; reads the refresh token with `loadFromStorage()`; raw `fetch`, never `request()`): on `res.ok` write storage, `setAuthToken`, `setTokens`, return `access_token`; on any non-OK (401 expired/invalid, 403 not owner) or network error return `null`. It must **not** call `login()`, which clears the TanStack cache and would drop the queries being retried.
  - Register it with `setRefreshHandler` in a `useEffect` (unregister on unmount). The mount-time refresh calls the same `refreshTokens()` and keeps its own failure handling (clear storage, navigate to `/login`), so there is one implementation and the single-flight covers both. They cannot overlap in practice: `ProtectedLayout` renders nothing while `isInitializing`, so no page query fires during the mount refresh.
  - `isAuthenticated` becomes `tokens !== null`. Today it is `!isAccessTokenExpired(tokens)`, evaluated whenever `AuthProvider` re-renders; once the 401 flow handles expiry, an expired-but-refreshable access token must not bounce the user to `/login`. After `isInitializing` is false, `tokens` is either usable/refreshable or null.
  - Failure path: a failed refresh, or a 401 on the retried request, ends in the existing `auth-error` → `logout()` → `/login`, once even with several concurrent 401s (they await the same promise; `logout()` is idempotent).
- Edge cases to describe in the report: concurrent 401s (one refresh, each caller retries once); a 401 from `/api/auth/refresh` itself (no retry, logout); refresh-token expiry at day 30 (refresh returns 401 → logout → login page); a refresh that succeeds while the user is on `/login` (nothing navigates).
- Verify with `npm run typecheck` and `npm run build`. Manual check: edit `pd_auth.access_token` in DevTools to a garbage string while on the Training page, then change the date range: the request 401s, the refresh runs, the retry succeeds, no redirect.

Commit: `feat(frontend): refresh access token on 401 and retry once`.

### Task 4: Server-side sleep target (decision 4)

**Interfaces:**
- Migration `015_user_sleep_target.py`: `inspect(eng).get_columns("users")`; if `sleep_target_minutes` is missing, `ALTER TABLE users ADD COLUMN sleep_target_minutes INTEGER NOT NULL DEFAULT 480` (same SQL on SQLite and Postgres). Follow `005_postgresql.py::_add_column_if_missing`. Why an ALTER: 006 creates `users` from the `User` model (`User.__table__.create(checkfirst=True)`), and `create_all` in 001/005 also uses the model, so on a fresh DB the column already exists and 015 is a no-op; `create_all` never adds columns to an existing table, so a database created before 015 needs the ALTER.
- Model: `User.sleep_target_minutes = Column(Integer, nullable=False, default=480)` (`src/auth/models.py`).
- `get_current_user` returns a detached `User(id=…, is_active=True)` built from the JWT, so `current_user.sleep_target_minutes` is always `None`. Add `src/database/user_settings.py`: `get_sleep_target_minutes(engine: Engine, user_id: str) -> int` (SELECT; raise `LookupError` when no row, the owner row always exists) and `set_sleep_target_minutes(engine: Engine, user_id: str, minutes: int) -> None` (UPDATE; raise `LookupError` when 0 rows). One extra SELECT per sleep request is fine for one user.
- API:
  - `GET /api/settings` → `{"sleep_target_minutes": int}`; `PUT /api/settings` takes the same shape, validated 300–720 inclusive (5–12 h), returns it. Both behind `get_current_user`. Router in `src/api/routes/settings.py`, registered in `main.py`; Pydantic `SleepSettings(sleep_target_minutes: int = Field(ge=300, le=720))` in `src/api/models.py`. `LookupError` → 404.
  - **Controller ruling R27: drop HTTP caching of `/api/*` responses altogether.** Today `CacheControlMiddleware` gives authenticated GETs `Cache-Control: private, max-age=300`. After a sync or settings change, TanStack's `invalidateQueries` refetch can then be served from the browser cache for up to 5 minutes, across every analytics endpoint, not just sleep and settings.
    - Change the middleware so every `/api/*` response gets `Cache-Control: no-store`. TanStack Query's `staleTime` already handles client-side caching for this single-user local app.
    - Static `/assets/*` and the SPA shell rules stay as Phase 3 set them.
    - Simplify `_NO_CACHE_PREFIXES` if it becomes redundant.
    - Test: `test_api_responses_are_no_store` (one GET analytics route plus `/api/settings`) asserts the header.
- Analytics:
  - `GET /api/sleep/insights` reads the target with `get_sleep_target_minutes` and passes `target_sleep_minutes=` to `get_sleep_insights` (already a parameter; `DEFAULT_TARGET_SLEEP_MINUTES` stays the default).
  - `get_sleep_consistency` uses the constant for `debt_series`, but its only output from that series is the OLS slope, which is invariant to subtracting a constant. Leave it; add a comment saying why no target is passed.
  - `weekly_digest._sleep_debt_status` uses fixed 6.5/7.5 h prose thresholds, not the target; leave it. Grep for other uses of the constant and `480` and list them in the report (none expected beyond `sleep_analysis.py`).
- Frontend:
  - `useSleepTarget()` → `useQuery({ queryKey: ['settings', 'sleep-target', userId] })` returning minutes; `useUpdateSleepTarget()` → mutation PUT; `onSuccess`: `setQueryData` for that key and `invalidateQueries({ queryKey: ['sleep'] })`.
  - `Settings.tsx`: delete the local `useSleepTarget` hook, `SLEEP_TARGET_KEY`, `DEFAULT_SLEEP_TARGET` and the localStorage code; the stepper runs 5–12 h in 0.5 h steps (minutes = hours × 60), matching the server. **Drop the localStorage→server migration**: a one-time two-click re-set for one user isn't worth the code, and a stored 4 h would fail validation. `localStorage.removeItem('sleepTargetHours')` on Settings mount is enough.
  - `Recovery.tsx:~416`: `of the {hours}h/night target this week` from `useSleepTarget()` (show `8h` while loading).
  - The target applies to all history (debt is recomputed from the current target on each request; no effective date). Say so in the Settings help text.

**Tests:**
- `test_settings_get_default_480`, `test_settings_put_validates_range` (299 and 721 → 422), `test_settings_put_persists` (PUT 420 then GET → 420), `test_settings_requires_auth` (401 without a token), `test_settings_get_is_no_store` (`Cache-Control: no-store`).
- `test_sleep_debt_uses_user_target`: set 420 for the owner; `/api/sleep/insights` debt for a 400-min rolling average is `−20`, not `−80`.
- `test_migration_015_idempotent`: create a pre-015 `users` table with raw SQL (no `sleep_target_minutes`), run 015 twice → column present, default 480, no error; on a DB where 006 just created the table from the model, 015 is a no-op.

Commit: `feat: server-side sleep target used for sleep debt`.

### Task 5: Today's "Last Night's Sleep" (decision 5)

- `frontend-react/src/pages/Today.tsx:~126` filters `s.date <= yesterday`. The query `useSleepInsights(range3.start, today)` already ends at today, so drop the filter and take the last element, which is exactly `Recovery.tsx`'s `lastNight` (`insights[insights.length - 1]`). Remove `yesterday`/`yesterdayISO` if nothing else uses them. A sleep that ended this morning but is still PENDING in Whoop has null scores; the card shows the duration and dashes for the scores, which is acceptable.
- Verify with typecheck and build.

Commit: `fix(frontend): Today shows the sleep that ended this morning`.

### Task 6: Per-page error boundary (decision 6)

- In `components/layout/Layout.tsx`, `const { pathname } = useLocation()` and wrap `<Outlet/>` as `<ErrorBoundary key={pathname}><Suspense fallback={<PageSkeleton/>}><Outlet/></Suspense></ErrorBoundary>`. The `key` remounts the boundary on navigation, which clears the error. Moving `Suspense` inside too keeps the sidebar mounted while a lazy page chunk loads (today the App-level `Suspense` replaces the whole tree, Layout included, with `PageSkeleton`).
- Keep the App-level `ErrorBoundary` and `Suspense` in `App.tsx:55–78` for `/login`, `/help/garmin-export` and errors outside Layout; page errors are caught by the inner one first.
- Verify with typecheck and build. In the report, describe the manual reasoning check: a thrown error in a page component renders the error card inside `<main>`, with the sidebar and bottom tab bar still mounted; clicking another tab shows that page.

Commit: `fix(frontend): per-page error boundary that resets on navigation`.

### Task 7: Backfill efficiency (deferred items)

**Per-chunk anomaly refresh.**
- `Normalizer.normalize_all(start, end, *, refresh_anomalies: bool = True)`; `GarminPipeline.run(start=None, end=None, *, daily: bool = True, refresh_anomalies: bool = True)` with `_run_locked(start, end, daily, refresh_anomalies)`; `WhoopPipeline.run(start=None, end=None, *, refresh_anomalies: bool = True)`. Scheduler, sync routes, CSV import and upload routes are unchanged (defaults). The analytics-cache invalidation in `normalize_all` stays unconditional.
- `scripts/backfill.py` passes `refresh_anomalies=False` to both pipelines and keeps the final `refresh_anomalies(engine, owner, args.start, today)` exactly as it is, including the `stored_total > 0` gate (an existing test asserts `assert_not_called()` when nothing was stored; nothing stored means nothing changed).
- **Decision: keep the double normalization with `--source all`.** Normalization is DB-only and takes seconds per chunk against about 40 minutes of API calls. Skipping the Garmin pass would leave dates with no unified rows whenever the Whoop pass is skipped (no token, auth error) or fails partway and is never resumed. Dropped.

**Garmin calls past the daily-history depth.**
- Observed (`docs/research/2026-11-garmin-personal-api.md`, "History depth"): daily summaries populated at 90 d and 180 d, empty (200, all metric fields null) at 365 d and beyond. `GarminClient.get_daily_summary` returns `{}` for those, and a day with the watch off all day looks identical, so a single empty day proves nothing. Daily summaries do exist on days the watch isn't worn at night, so "empty" means the whole day had no device data or the date is past the depth.
- `GarminPipeline.run(..., daily=False)` skips the `_sync_daily` loop (activities and strength summaries only). The SyncLog still records the window; `_get_sync_window` uses max `sync_end`, so old chunks never move the incremental start.
- `scripts/backfill.py`:
  - `--daily-from YYYY-MM-DD` (optional): chunks whose `end` is before it run `daily=False`; no probe.
  - Without it, and only when `START < today − 180`: probe. `_has_daily(client, d) -> bool` is "any non-empty `get_daily_summary` for `d`, `d+1`, `d+2`" (3 calls; a 3-day all-off streak is the residual false-negative). Probe `START`: has data → every chunk runs daily, done. Probe `today − 180`: no data → print a note that the depth assumption no longer holds and run every chunk with daily on. Otherwise binary-search the earliest date with data between them (about 8 steps × 3 calls, roughly 30 s with the client's 1 s spacing), subtract a 7-day margin, and use that as `daily_from`. Chunks with `end < daily_from` run `daily=False`; the chunk containing `daily_from` runs with daily on.
  - Print `Garmin daily summaries start about <date>; <n> chunks before <chunk start> run activities-only (override with --daily-from).` A wrong boundary (the probe hit a 3-day off streak) costs at most the daily data between the true and the found boundary; the note tells SJ how to re-run.
  - One `GarminClient()` for the probe, referenced as a module attribute (`scripts.backfill.GarminClient`) so tests can patch it. Probe failures (`GarminPersonalApiError`) print and exit 1 like a failed chunk; never swallow them.

**Tests:**
- `tests/test_garmin_pipeline.py` with `FakeClient`: `test_pipeline_daily_false_skips_daily_calls`: `run(start, end, daily=False)` → `"get_daily_summary"`, `"get_sleep"`, `"get_hrv"` absent from `client.calls`, `client.calls.count("get_activities") == 1`, `log.status == "success"`.
- `tests/test_normalization.py`: `test_normalize_all_skips_anomaly_refresh_when_disabled` (patch `src.analytics.anomaly_store.refresh_anomalies`; not called with `refresh_anomalies=False`, called once by default).
- `tests/test_backfill.py`: the fake `run` lambdas become `lambda start, end, **kw: _log()`.
  - `test_backfill_skips_per_chunk_anomaly_refresh`: every `garmin_run`/`whoop_run` call has `kwargs["refresh_anomalies"] is False`; the existing `env.refresh.assert_called_once_with(...)` still holds.
  - `test_backfill_activities_only_before_daily_depth`: patch `scripts.backfill.GarminClient` with a fake whose `get_daily_summary(d)` is `{}` for `d < CUTOFF` else `{"totalSteps": 1}`; `START = TODAY − 400`, `CUTOFF = TODAY − 300`. Every chunk with `end < CUTOFF − 7 days` has `kwargs["daily"] is False`, every later chunk `True`, and the note is printed.
  - `test_backfill_no_probe_when_start_recent`: `START = TODAY − 100` → the fake client is never constructed and every chunk has `daily=True`.
  - `test_backfill_daily_from_override`: `--daily-from` given → no probe calls; the split follows the given date.

Commit: `perf: backfill skips per-chunk anomaly refresh and daily calls past Garmin's history depth`.

### Task 8: Lift the SQLAlchemy pin and clear test warnings (deferred items)

- Verified with SQLAlchemy 2.1.8: `str(create_engine("sqlite:///:memory:").url)` renders `sqlite:///%3Amemory%3A`, so `scripts/create_owner.py`'s `endswith(":memory:")` guard is false, `dispose()` runs, and `tests/test_create_owner.py` (one `StaticPool` in-memory engine shared across the test) loses its database. `engine.url.database` is still `":memory:"`, but don't keep a test-only branch: **remove the guard and always `engine.dispose()`**; the test fixture patches `eng.dispose` (`patch.object(eng, "dispose")`) and asserts it was called once.
- Also verified under 2.1.8 with `-W error`: `sessionmaker(bind=..., autocommit=False, autoflush=False)` (`src/database/connection.py:~102`) is still accepted. Nothing in `src/`, `scripts/` or `tests/` uses the 2.x-removed APIs (`ext.declarative`, `Query.get`, `select([...])`, `engine.execute`). Then remove `sqlalchemy<2.1` from `pyproject.toml`, re-lock with uv (scratchpad uv at `/private/tmp/claude-501/-Volumes-Dock-Storage-Projects-garmin-whoop-dashboard/26b4f8fc-46fc-434b-bfa6-ea5ddc08c3fd/scratchpad/uvenv/bin/uv`), sync `.venv`, run the full suite serially. If 2.1 breaks anything else, restore the pin, keep the guard removal, and report what broke.
- Warnings: run `.venv/bin/pytest -q -W default` and read the summary (`-W error::DeprecationWarning` turns them into failures, useful for locating, not for config). Fix deprecations that come from our code in `src/`, `scripts/` or `tests/`. For warnings raised inside third-party modules, add `filterwarnings` entries under `[tool.pytest.ini_options]` in `pyproject.toml` (`ignore:<message regex>:<Category>:<module>`), each with a comment naming the package and version; only for third-party module patterns. Likely sources to check first: `python-jose` (`datetime.utcnow()`), `pytest-asyncio` loop-scope config, Starlette `TestClient`/`httpx` deprecations. Target: 0 warnings from our own code.

Commit: `chore: drop sqlalchemy<2.1 pin; fix deprecation warnings`.

### Task 9: Docs

- Update `CLAUDE.md` and `README.md`:
  - local-time Whoop dates and clock times (daily key, wake key, workout date, recovery-activity date, bedtime/wake hours); VO2 also keyed by local date (R26); `/api/*` responses are `no-store` (R27)
  - sleep target setting (`/api/settings`, 300–720 min, applies to all history) and the `no-store` paths
  - silent refresh on 401 (single-flight, one retry, `download` excluded)
  - per-page boundary and Suspense inside Layout
  - the anomaly lookback (detection over the 29-day lookback, cache rows rewritten only inside the sync window)
  - backfill: no per-chunk anomaly refresh, `--daily-from`, the depth probe; the double normalization is kept on purpose
  - the test count
- In the "Open items" lists (`CLAUDE.md` and `plans/2026-11-06-personal-relaunch-roadmap.md`), remove the resolved decisions, the `create_owner` follow-up and the backfill optimization line.
- Check off Phase 8 in the roadmap.

Commit: `docs: Phase 8 decisions`.
