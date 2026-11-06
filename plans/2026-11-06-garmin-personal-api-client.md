# Garmin Personal API Swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unofficial `garminconnect` password login with Garmin's official Personal
API (self-generated key → 24 h bearer JWT), keeping `GarminPipeline` and everything downstream
of it working. Collapse the scheduler to a single owner.

**Architecture:**
- A new `GarminPersonalAuth` exchanges the key for a JWT and caches it in memory.
- `GarminClient` is rewritten on `httpx` against `https://personal.connectapi.garmin.com` and
  keeps its public method names, so the pipeline changes only where response shapes differ:
  sleep, HRV and strength.
- Strength sets come from `summarizedExerciseSets` on the activity list record and go into a new
  table.
- One `get_owner_user_id()` helper replaces the per-user fan-out.

**Tech Stack:** Python 3.11+, httpx 0.28 (`httpx.MockTransport` in tests), SQLAlchemy 2, FastAPI,
APScheduler 3, pytest.

**Spec:** [`docs/research/2026-11-garmin-personal-api.md`](../docs/research/2026-11-garmin-personal-api.md)
(sections 2–5 and 8). Scope comes from [`plans/2026-11-06-personal-relaunch-roadmap.md`](2026-11-06-personal-relaunch-roadmap.md),
Phases 1–2. The endpoint and schema source of truth is
[`docs/reference/garmin-personal-api-openapi.json`](../docs/reference/garmin-personal-api-openapi.json).

## Global Constraints

- Base URL `https://personal.connectapi.garmin.com`. It can be overridden by
  `GARMIN_PERSONAL_API_BASE_URL`.
- Token exchange: `POST /personalapitoken-service/personal-api/personal-api-key/token` with
  header `Authorization: ApiKey <key>` and no body. The response is the raw JWT as **plain text**.
  Expiry comes from the JWT `exp` claim.
- Data calls: `GET` with `Authorization: Bearer <jwt>` and `Accept: application/json`.
- Re-exchange when less than **3600 s** of token life remain. There are no refresh tokens.
- A 400, 401 or 403 from the token exchange means the key was rejected → raise `GarminKeyError`.
  Its message must include `https://connect.garmin.com/app/settings/personalApiToken`.
  A 5xx or a network error on the exchange is **not** a key problem → raise `GarminTransientError`.
- One process-wide `GarminPersonalAuth` (and its `httpx.Client`, which is thread-safe) is shared
  by the scheduler thread, `asyncio.to_thread` manual syncs and the status endpoint, so the key is
  exchanged at most once per 23 h, not once per sync run. See `get_default_auth()` in Task 2.
- Use `httpx` only. Do not add `requests` or Garmin's official package (roadmap D2).
- Default delay between Garmin calls is **1.0 s**. Stop the sync run at the **first 429**, and
  also at the first 5xx/network failure, so `sync_end` never advances past a gap.
- Units in `SummarizedExerciseSet` are fixed by the spec: `maxWeight` and `volume` are in
  **grams**, `duration` is in **milliseconds**. The spike confirms; it doesn't decide.
- `DailySleepDTO.sleepStartTimestampGMT`/`EndTimestampGMT` are declared `string` (`date-time`) in
  the spec, while garminconnect returned Unix-ms integers. `transform_sleep` must accept both.
- Activity `startDate`/`endDate` filter on the activity's **local** start date, and the container
  clock is UTC. Incremental runs therefore re-fetch a 2-day overlap (Task 5); upserts make that
  idempotent.
- The key comes from the env var `GARMIN_PERSONAL_API_KEY`. Never log it and never store it in the DB.
- **No personal data in git.** Raw API samples go to `data/garmin_personal_samples/`
  (gitignored). Committed fixtures must be sanitized as described in Task 1.
- Repo conventions:
  - Type hints and docstrings on public functions.
  - `datetime.UTC`, not `timezone.utc`.
  - `make lint` must stay clean. The baseline had 25 existing errors; the roadmap's Phase 0
    "clean lint baseline" item fixes them before Task 1.
  - Run tests **serially** (`.venv/bin/pytest -q`). xdist (`-n auto`) is broken at baseline. The
    baseline is 909 passed.
  - Use the `.venv` created by `uv sync`.
- Do not delete migration files or drop tables. Existing databases have run them.

## Review Focus

1. **The key expires or is revoked mid-run.** The sync log row ends as `status="error"` with an
   actionable message. The scheduler doesn't spin. `/api/auth/garmin/status` reports
   `connected=false` with the error. Covered by Task 5 `test_run_records_key_error`, Task 7
   `test_garmin_status_reports_key_error`.
2. **Garmin returns 429.** The run stops immediately: no 60 s sleep-and-retry, no N more calls.
   The next scheduled interval tries again. Covered by Task 3 `test_429_raises_rate_limit`,
   Task 5 `test_run_aborts_on_rate_limit`.
3. **A night without the Garmin watch.** Sleep comes back as a near-empty `DailySleepDTO`; HRV
   returns **204**. Today's behavior must hold: a DTO that still carries `calendarDate` writes an
   all-NULL `garmin_sleep` row (as `_sync_daily` does now for any non-`None` dict), a 204 or `{}`
   writes nothing, and no HRV row is written. Unified sleep is Whoop-primary, so either outcome
   is harmless. Covered by Task 3 `test_get_hrv_204_returns_none`, Task 4
   `test_transform_sleep_flat_empty`, Task 5 `test_no_watch_night_writes_null_sleep_and_no_hrv`.
4. **Reprocessing old `raw_json`.** Rows stored from garminconnect have the
   `{"dailySleepDTO": {...}}` wrapper and HRV `lastNight`, and must still transform. Covered by
   Task 4 `test_transform_sleep_legacy_wrapper`, `test_transform_hrv_legacy_lastnight`.
5. **Strength history.** Activities that only have old set-level rows must still appear in the
   strength charts. An activity with both set rows and summary rows must not be double-counted:
   set rows win. A date with one legacy activity and one new activity returns **one** row.
   Covered by Task 6 `test_volume_prefers_sets_over_summaries`,
   `test_max_weight_includes_legacy_sets`, `test_volume_same_date_mixed_sources_one_row`.
6. **Garmin hiccups must not create silent gaps.** A 5xx or network error anywhere in a run ends
   it as `status="error"` (window not advanced); the next interval re-pulls the same window.
   Covered by Task 3 `test_5xx_raises_transient`, Task 5 `test_run_records_transient_error`.
7. **Evening workouts and late watch syncs.** Incremental runs start 2 days before the last
   `sync_end`. Covered by Task 5 `test_sync_window_overlaps_previous_end`.

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `scripts/garmin_personal_probe.py` | Create | One-off spike: exchange the key, call the endpoints, save raw + sanitized samples |
| `tests/fixtures/garmin_personal/*.json` | Create | Sanitized response fixtures |
| `config/settings.py` | Modify (Task 2) | Add the Personal API settings first, because `GarminClient()` defaults read them |
| `src/clients/garmin_personal_auth.py` | Create | Key → JWT exchange, cache, errors, process-wide default instance |
| `src/clients/garmin_client.py` | Rewrite | Personal API data calls with the same public method names |
| `src/ingestion/garmin_pipeline.py` | Modify | Shape fixes, exercise summaries, error handling, constructor, window overlap |
| `src/database/models.py` | Modify | Add `GarminExerciseSummary` |
| `src/database/migrations/014_exercise_summaries.py` | Create | Create the `garmin_exercise_summaries` table |
| `src/database/migrations/__init__.py` | Modify | Append `_load("014_exercise_summaries.py").run(**kwargs)` to the hardcoded list in `run()` |
| `src/api/routes/workouts.py`, `src/api/models.py` | Modify | Strength queries read summaries; new `/exercise-summary` |
| `tests/test_strength_routes.py` | Create | Route-level strength tests (none exist today) |
| `src/database/owner.py` | Create | `get_owner_user_id()` |
| `src/ingestion/scheduler.py` | Modify | One Garmin job and one Whoop job, owner only |
| `src/api/routes/sync.py`, `src/api/routes/auth.py` | Modify | Garmin gating and status from the key |
| `tests/test_sync_routes.py` | Create | Home for the sync-route tests now in `test_scheduler_multiuser.py` |
| `.env.example`, `pyproject.toml`, `uv.lock` | Modify (Task 8) | Swap the Garmin env vars; drop `garminconnect` |
| `frontend-react/src/hooks/useApi.ts`, `pages/Settings.tsx`, `components/ConnectDevicesPanel.tsx` | Modify (Task 9) | Garmin card reads key status; credential UI removed |
| Delete | `src/clients/garmin_auth.py`, `src/auth/encryption.py`, `src/api/routes/garmin_credentials.py`, `tests/test_garmin_auth.py`, `tests/test_garmin_credentials.py`, `tests/test_scheduler_multiuser.py` | |

Task order matters: 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Each task leaves `make test` green on its own
commit. Task 1 only needs the key and can run first or in parallel.

---

### Task 1: Spike — probe the live API and capture fixtures

Needs `GARMIN_PERSONAL_API_KEY` in `.env` (roadmap Phase 0). If the key isn't available, stop
and report back. Don't fabricate fixtures from the schema.

**Files:**
- Create: `scripts/garmin_personal_probe.py`
- Create: `tests/fixtures/garmin_personal/{activities.json,daily_summary.json,sleep.json,sleep_empty.json,hrv.json,user_settings.json}`
- Verify: `.gitignore` already ignores `data/` (line 5), so `data/garmin_personal_samples/` needs
  no new entry. Don't add one.
- Modify: `docs/research/2026-11-garmin-personal-api.md` (add a "§9 Spike results" section)

**Interfaces:**
- Produces: the fixture files above, plus these values recorded in research §9 that later tasks
  use:
  - `SLEEP_SCORE_KEY`, expected `"overall"` (`sleepScores` is a map of `SleepScoreItem`; record
    every key seen).
  - `SUMMARY_WEIGHT_DIVISOR = 1000`. The spec documents `maxWeight` and `volume` in grams and
    `duration` in milliseconds; the spike only confirms a plausible magnitude (a 100 kg lift shows
    as `100000`).
  - The JSON **type** of `sleepStartTimestampGMT`/`sleepEndTimestampGMT` (integer Unix ms, or an
    ISO string as the spec declares) and of `activityId` (integer; we `str()` it).
  - Whether `summarizedExerciseSets[].subCategory` values match the historical
    `garmin_exercise_sets.exercise_name` values. Check against a local DB or the old test fixtures.
  - What a no-watch night returns from `dailySleep` (a DTO with only `calendarDate`, `{}`, or 204)
    and that `hrv/{date}` returns 204 for the same night.

- [ ] **Step 1:** Write `scripts/garmin_personal_probe.py`. It uses plain `httpx` and does
  not import any `src` code, so it runs before Tasks 2–3 exist. It runs the token exchange
  and prints the JWT `exp` as an ISO time, without printing the token. Then it GETs, at 1.0 s
  spacing:
  - `/userprofile-service/userprofile/settings`
  - activities for the last 30 days (`startDate`, `endDate`, `start=0`, `limit=100`)
  - `/usersummary-service/usersummary/daily?calendarDate=<yesterday>`
  - `/sleep-service/sleep/dailySleep?date=<yesterday>`
  - `/sleep-service/sleep/dailySleep?date=` and `/hrv-service/hrv/<date>` for a night without the
    watch (pass it as `--no-watch-date`)
  - `/hrv-service/hrv/<yesterday>`
  - one strength activity's list record
  - the same daily, sleep and activities calls for a date 730 days ago, to check history depth

  It writes each raw response to `data/garmin_personal_samples/<name>.json` and records the
  status code, the `Content-Type`, and the body length (so a 204 or an empty 200 is visible).
  On a 429 it prints any `Retry-After` header and stops.
- [ ] **Step 2:** Run `.venv/bin/python scripts/garmin_personal_probe.py --no-watch-date <date>`.
  Expected: a 200 from the token exchange, and a status line per endpoint.
- [ ] **Step 3:** Sanitize the raw samples into `tests/fixtures/garmin_personal/`:
  - Keep every key name and nesting level exactly.
  - Drop these fields: `userProfilePk`, `userProfilePK`, `userProfileId`, `ownerId`,
    `ownerDisplayName`, `ownerFullName`, `ownerProfileImageUrl*`, `displayName`,
    `startLatitude`, `startLongitude`, `endLatitude`, `endLongitude`, `locationName`,
    `timeZone`, `deviceId`, `uuid`, `activityUUID`, `userDailySummaryId`, `id`,
    `lastSyncTimestampGMT`, `activityName`, `description`, `userNote`, `kidSleepNote`,
    `jetLagTripName`, `wellnessDescription`, `hydrationContainers`, and anything containing an
    email or name. Replace `activityName` with `"Run"`, `"Strength"` or `"Other"` rather than
    deleting it, because `transform_activity` reads it.
  - Replace `activityId` values with `10000000001` and up.
  - Replace every health metric number with a plausible synthetic value of the same type.
  - Keep at most 3 activities: one run, one strength session with `summarizedExerciseSets`,
    and one other.
- [ ] **Step 4:** Record the §8 answers as "§9 Spike results" in the research doc:
  - Which activity fields are populated (`vO2MaxValue`, `activityTrainingLoad`, running dynamics).
  - The `sleepScores` keys and the sleep timestamp JSON type.
  - The HRV summary keys.
  - `maxWeight` magnitude (confirms grams), plus `SUMMARY_WEIGHT_DIVISOR`.
  - Whether `subCategory` matches historical `exercise_name`.
  - No-watch night shapes for sleep and HRV.
  - History depth (did the 730-day calls return data?).
  - Any 429s.
- [ ] **Step 5:** Run `git diff --cached` and confirm it contains no raw samples, tokens or real
  values. Then commit:
  `git add scripts/garmin_personal_probe.py tests/fixtures/garmin_personal docs/research && git commit -m "spike: probe Garmin Personal API and capture sanitized fixtures"`

### Task 2: Settings + `GarminPersonalAuth`

**Files:**
- Modify: `config/settings.py` (the settings live here, not in Task 7, because Task 3's
  `GarminClient()` and Task 5's `GarminPipeline()` defaults read them; without this the Task 3–6
  commits would raise `AttributeError` on default construction)
- Create: `src/clients/garmin_personal_auth.py`
- Test: `tests/test_garmin_personal_auth.py`

**Interfaces:**
- Produces:
  - Settings fields on the `Settings` dataclass:
    - `garmin_personal_api_key: str` (env `GARMIN_PERSONAL_API_KEY`, default `""`)
    - `garmin_personal_api_base_url: str` (env `GARMIN_PERSONAL_API_BASE_URL`, default
      `"https://personal.connectapi.garmin.com"`)
    - `garmin_poll_interval_minutes` default changes from `15` to `30`.
  - `DEFAULT_BASE_URL: str`, `TOKEN_PATH: str` and `KEY_PAGE_URL: str` constants.
  - `class GarminPersonalApiError(Exception)`: base for the three below, so `run()` can catch one
    thing.
  - `class GarminKeyError(GarminPersonalApiError)` for a missing, rejected or expired key.
  - `class GarminRateLimitError(GarminPersonalApiError)` for any 429.
  - `class GarminTransientError(GarminPersonalApiError)` for 5xx and `httpx.TransportError`.
  - `@dataclass(frozen=True) class BearerToken: access_token: str; expires_at: datetime`
  - `def decode_jwt_exp(token: str) -> datetime`: returns the `exp` claim as an aware UTC
    datetime with no signature check. Use `jose.jwt.get_unverified_claims` (python-jose is
    already a dependency and handles base64url padding); map `JWTError` and a missing `exp` to
    `GarminKeyError`.
  - `class GarminPersonalAuth.__init__(self, api_key: str | None = None, base_url: str | None = None, http: httpx.Client | None = None)`:
    the key defaults to `settings.garmin_personal_api_key` and the base URL to
    `settings.garmin_personal_api_base_url`.
  - `GarminPersonalAuth.get_token(self, force_refresh: bool = False) -> str`
  - `GarminPersonalAuth.token_expires_at: datetime | None` (property)
  - `GarminPersonalAuth.last_error: str | None`: the message of the most recent `GarminKeyError`,
    cleared on the next successful exchange. The status endpoint (Task 7) reads it so a key
    failure seen by the scheduler shows up without a live probe.
  - `def get_default_auth() -> GarminPersonalAuth`: lazily creates and returns the one
    process-wide instance (lock-guarded). `def reset_default_auth() -> None` for tests. This is
    how "the scheduler thread and manual-sync threads share one instance" actually happens;
    `GarminClient(auth=None)` (Task 3) and the status route (Task 7) call it.

- [ ] **Step 1: Write the failing tests.** Build JWTs in the tests by base64url-encoding
  `{"alg":"none"}.{"exp":<ts>}.` and serve them through `httpx.MockTransport`.
  - `test_exchange_sends_apikey_header`: exactly one request, `POST {base}{TOKEN_PATH}`,
    `request.headers["Authorization"] == "ApiKey k123"`, empty body.
  - `test_get_token_returns_plaintext_jwt`: the response body is `"  <jwt>\n"`, and
    `get_token()` returns `<jwt>` stripped.
  - `test_token_cached_while_more_than_1h_left`: `exp` = now + 24 h, `get_token()` called twice,
    1 request.
  - `test_token_reexchanged_when_under_1h_left`: `exp` = now + 30 min, `get_token()` called
    twice, 2 requests.
  - `test_force_refresh_reexchanges`: 2 requests.
  - `test_rejected_key_raises` (parametrized over 400, 401, 403): `GarminKeyError` is raised,
    and `KEY_PAGE_URL in str(exc)`.
  - `test_missing_key_raises`: `api_key=""` raises `GarminKeyError` with no HTTP request made.
  - `test_malformed_jwt_raises`: a body of `"not-a-jwt"` raises `GarminKeyError`.
  - `test_exchange_429_raises_rate_limit`: raises `GarminRateLimitError`.
  - `test_exchange_5xx_raises_transient` (parametrized over 500, 503, and a
    `httpx.ConnectError` raised by the transport): raises `GarminTransientError`, not
    `GarminKeyError`, and `last_error` stays `None`.
  - `test_last_error_set_and_cleared`: a 401 sets `last_error` to the message; a following 200
    clears it.
  - `test_get_default_auth_is_singleton`: two calls return the same object;
    `reset_default_auth()` then a call returns a new one.
  - `test_key_never_in_exception_text`: for every error above, `"k123" not in str(exc)`.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_garmin_personal_auth.py -v`. Expected: FAIL
  (ImportError).
- [ ] **Step 3:** Add the settings fields, then implement `src/clients/garmin_personal_auth.py`.
  Guard the exchange with an instance-level `threading.Lock`, and re-check the cache after
  acquiring it. `get_default_auth()` uses a module-level lock for its own lazy init. Never log
  the key or the token; log only `expires_at`.
- [ ] **Step 4:** Run the tests plus `tests/test_scheduler.py` (it patches `settings`).
  Expected: all PASS.
- [ ] **Step 5:** Commit:
  `git add config/settings.py src/clients/garmin_personal_auth.py tests/test_garmin_personal_auth.py && git commit -m "feat: Garmin Personal API key-to-token auth"`

### Task 3: Rewrite `GarminClient` on the Personal API

**Files:**
- Rewrite: `src/clients/garmin_client.py`
- Rewrite: `tests/test_garmin_client.py` (the old tests mock garminconnect; replace them)

**Interfaces:**
- Consumes: Task 2's `GarminPersonalAuth`, `get_default_auth`, and the error classes.
- Produces: `class GarminClient.__init__(self, auth: GarminPersonalAuth | None = None, request_delay: float = 1.0, http: httpx.Client | None = None)`.
  `auth=None` means `get_default_auth()`; `http=None` means the auth instance's shared client.
  Public methods, all synchronous:
  - `get_activities(start_date, end_date) -> list[dict]`: pages
    `/activitylist-service/activities/search/activities` with `startDate`, `endDate`, `start` and
    `limit=100`, until a page has fewer than 100 items (an empty page counts). The API default
    `limit` is 99, so always pass it explicitly.
  - `get_daily_summary(date_) -> dict`: one call to
    `/usersummary-service/usersummary/daily?calendarDate=`. Returns `{}` on no data.
  - `get_sleep(date_) -> dict | None`: `/sleep-service/sleep/dailySleep?date=`. Returns the flat
    `DailySleepDTO` as-is (even if it only carries `calendarDate`), or `None` on 204, an empty
    body or `{}`.
  - `get_hrv(date_) -> dict | None`: `/hrv-service/hrv/{date}`. Returns `None` on 204 or empty.
  - `get_user_settings() -> dict`: `/userprofile-service/userprofile/settings`, used as the
    key-validity probe. Never log its body (it carries `displayName` and `timeZone`).
  - **Removed:** `get_exercise_sets` (no endpoint) and `get_activity_detail` (no callers; add it
    back when the .FIT follow-up needs it).

  The date parameters accept `date | datetime | str`; keep the existing `_fmt_date` helper
  (`garmin_client.py:27`). Keep the `_rate_limit` shape too (`time.monotonic` + `time.sleep`,
  `garmin_client.py:170`); the existing delay tests only need the default changed to 1.0.

- [ ] **Step 1: Write the failing tests** (use `httpx.MockTransport` with a stub auth whose
  `get_token(force_refresh)` returns `"t1"`, or `"t2"` after a forced refresh):
  - `test_requests_use_bearer_and_base_url`: the request URL starts with
    `https://personal.connectapi.garmin.com/`, and the headers carry `Authorization: Bearer t1`
    and `Accept: application/json`.
  - `test_get_activities_pages_until_short_page`: two pages of 100 and 3 items. The result has
    103 items, and the second request has `start=100`, `limit=100`, `startDate=2026-10-01` and
    `endDate=2026-10-31`.
  - `test_get_activities_exact_page_stops_on_empty`: a page of exactly 100 then `[]`. 2 requests,
    100 items, no third request.
  - `test_get_daily_summary_single_call`: exactly 1 request, path
    `/usersummary-service/usersummary/daily`, `calendarDate=2026-11-01`. Returns the
    `daily_summary.json` fixture unchanged.
  - `test_get_sleep_returns_flat_dto`: given the `sleep.json` fixture, `result["sleepTimeSeconds"]`
    is present and `"dailySleepDTO" not in result`.
  - `test_get_sleep_empty_returns_none`: a 200 with body `{}` returns `None`.
  - `test_get_hrv_204_returns_none`.
  - `test_401_retries_once_with_forced_refresh`: a 401 then a 200. 2 data requests; the second
    one carries `Bearer t2`.
  - `test_401_twice_raises_key_error`: raises `GarminKeyError`.
  - `test_403_raises_key_error_without_retry`: 1 request, `GarminKeyError` (a 403 on a data call
    is a scope/key problem, not a stale token).
  - `test_429_raises_rate_limit`: raises `GarminRateLimitError`, after exactly 1 request (no
    retry, no sleep).
  - `test_404_returns_none_and_logs_warning`: uses `caplog`.
  - `test_5xx_raises_transient` (parametrized over 500, 502, and `httpx.ConnectError`): raises
    `GarminTransientError` after 1 request. `get_activities` must not swallow this into `[]`,
    or a Garmin outage would end a run as "success" and advance `sync_end` past a gap.
  - `test_request_delay_enforced`: monkeypatch `time.monotonic` and `time.sleep`. With
    `request_delay=1.0`, two back-to-back calls sleep about 1.0 s.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_garmin_client.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. All HTTP goes through one private `_get(path, params=None) -> Any`:
  - 204 or an empty body → `None`.
  - 400 or 404 → warn and return `None`.
  - 401 → retry once with `get_token(force_refresh=True)`; a second 401 raises `GarminKeyError`.
  - 403 → raise `GarminKeyError` (no retry).
  - 429 → raise `GarminRateLimitError`.
  - 5xx or `httpx.TransportError` → raise `GarminTransientError`.
  - A JSON decode failure on a 200 → warn and return `None`.
  The rate-limit timestamp is per client instance. A manual sync and a scheduled run can
  overlap (the 409 in `sync.py` only guards manual-vs-manual; APScheduler `max_instances=1`
  only guards scheduled-vs-scheduled), which briefly doubles the call rate. Acceptable for one
  user; don't add cross-instance throttling.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit:
  `git add src/clients/garmin_client.py tests/test_garmin_client.py && git commit -m "feat: GarminClient on Garmin Personal API"`

### Task 4: Pipeline transforms, exercise-summary model and migration 014

**Files:**
- Modify: `src/ingestion/garmin_pipeline.py` (`transform_sleep` at 158, `transform_hrv` at 242,
  `_ms_to_iso` at 43, new `transform_exercise_summaries`; leave `transform_exercise_sets` at 201
  in place, because old set rows stay readable)
- Modify: `src/database/models.py` (add `GarminExerciseSummary` after `GarminExerciseSet`, which
  ends at line 165)
- Create: `src/database/migrations/014_exercise_summaries.py`. Follow the structure of
  `013_anomaly_cache.py`: `inspect(eng).get_table_names()` early return, separate SQLite and
  Postgres DDL chosen by `"postgresql" in str(eng.url)`, then index DDL.
- Modify: `src/database/migrations/__init__.py`. The loader is a hardcoded sequence of
  `_load("0NN_name.py").run(**kwargs)` calls inside `run()`, not a glob; append
  `_load("014_exercise_summaries.py").run(**kwargs)` after 013. Every migration runs on every
  startup, so 014 must be idempotent.
- Test: `tests/test_garmin_pipeline.py`

**Interfaces:**
- Consumes: Task 1's fixtures and its `SLEEP_SCORE_KEY` and `SUMMARY_WEIGHT_DIVISOR` values.
- Produces:
  - Model `GarminExerciseSummary`, table `garmin_exercise_summaries`, with columns:
    - `id` (int PK autoincrement)
    - `activity_id` (String, FK `garmin_activities.activity_id`, not null, indexed)
    - `exercise_category` (String)
    - `exercise_name` (String; from `subCategory`, falling back to `category`)
    - `set_count` (Integer)
    - `repetition_count` (Integer)
    - `volume_kg` (Float)
    - `max_weight_kg` (Float)
    - `duration_seconds` (Float)
    - `fetched_at` (String, not null)
    - `user_id` (Text, indexed)
  - `transform_exercise_summaries(activity_id: str, record: dict, fetched_at: str) -> list[dict]`
    reads `record["summarizedExerciseSets"]`. Divide `maxWeight` and `volume` by
    `SUMMARY_WEIGHT_DIVISOR` (grams → kg), and `duration` by `1000` (ms → s). Map `sets` →
    `set_count` and `reps` → `repetition_count`. Skip entries with no category. Don't gate on
    `_STRENGTH_TYPES`: write rows for any activity whose record carries a non-empty list.
  - A `_ts_to_iso(value: int | float | str | None) -> str | None` helper replaces `_ms_to_iso`
    for sleep: an int/float is Unix ms (legacy `raw_json`), a string is parsed as ISO 8601 (the
    spec's declared type), `None` stays `None`. Output is always an aware UTC ISO string.
  - `transform_sleep` accepts both the flat DTO and the legacy `{"dailySleepDTO": {...}}`.
    `sleep_score` comes from `sleepScores[SLEEP_SCORE_KEY]["value"]`, falling back to
    `sleepScore`. `avg_stress_sleep` comes from `avgSleepStress`, falling back to
    `averageStressLevel`.
  - `transform_hrv`: `last_night_avg_ms` comes from `lastNightAvg`, falling back to `lastNight`.

- [ ] **Step 1: Write the failing tests:**
  - `test_transform_sleep_flat_fixture`: using `sleep.json`, `total_sleep_seconds`,
    `deep_sleep_seconds`, `sleep_score` and `start_time` all equal the fixture values; the
    timestamp is ISO.
  - `test_transform_sleep_accepts_ms_and_iso_timestamps`: parametrized; `sleepStartTimestampGMT`
    as `1762387200000` and as `"2025-11-06T00:00:00.0"` both give `start_time ==
    "2025-11-06T00:00:00+00:00"`.
  - `test_transform_sleep_flat_empty`: `transform_sleep("2026-11-01", {"calendarDate": "2026-11-01"}, ts)`
    gives `start_time is None` and `total_sleep_seconds is None`.
  - `test_transform_sleep_legacy_wrapper`: the existing `SAMPLE_SLEEP` (wrapped) still maps.
    Keep the old assertions (`test_transform_sleep_converts_timestamps`,
    `test_transform_sleep_null_timestamps` at `tests/test_garmin_pipeline.py`).
  - `test_transform_hrv_lastnightavg`: given `{"hrvSummary": {"lastNightAvg": 55}}`,
    `last_night_avg_ms == 55`.
  - `test_transform_hrv_legacy_lastnight`: given `{"hrvSummary": {"lastNight": 62}}`, the result
    is `62`.
  - `test_transform_exercise_summaries_maps_fixture`: the strength record in `activities.json`
    produces one row per `summarizedExerciseSets` entry. `max_weight_kg` and `volume_kg` equal
    the fixture values ÷ `SUMMARY_WEIGHT_DIVISOR`; `duration_seconds` equals `duration` ÷ 1000.
  - `test_transform_exercise_summaries_absent_field`: a record with no `summarizedExerciseSets`
    returns `[]`.
  - `test_migration_014_creates_table_idempotent`: run all migrations twice on in-memory SQLite.
    The `garmin_exercise_summaries` columns match the list above.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_garmin_pipeline.py tests/test_database.py -v`.
  Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the transforms, the model and migration 014.
- [ ] **Step 4:** Run the tests. Expected: PASS, and the old transform tests still pass.
- [ ] **Step 5:** Commit:
  `git commit -m "feat: transforms for Personal API sleep/HRV shapes + exercise summaries table"`

### Task 5: Pipeline wiring

**Files:**
- Modify: `src/ingestion/garmin_pipeline.py` (`__init__` at 288, `run` at 320, `_get_sync_window`
  at 422, `_sync_activities` at 445). Delete `_find_strength_activities_without_sets` (477) and
  `_sync_strength_sets` (513), and the lazy `from src.clients.garmin_auth import …` at 302.
- Test: `tests/test_garmin_pipeline.py`

**Interfaces:**
- Consumes: Task 3's `GarminClient` and Task 4's transforms and model.
- Produces:
  - `GarminPipeline.__init__(self, db: Session, client: GarminClient | None = None, user_id: str | None = None)`
    defaults to `GarminClient()`. There is no more `GarminAuth` branch.
  - `_sync_activities` writes `garmin_exercise_summaries` rows (delete-then-insert per
    `activity_id`, tagged with `user_id`) for every record whose
    `transform_exercise_summaries` result is non-empty, in the same loop that upserts the
    activity. No extra HTTP call.
  - `INCREMENTAL_OVERLAP_DAYS = 2`. `_get_sync_window()` returns
    `(sync_end_of_last_success - INCREMENTAL_OVERLAP_DAYS, today)`. Why: `startDate`/`endDate`
    filter on the activity's **local** start date while the container clock is UTC, so a
    21:00-local workout can fall before a `sync_end` computed after 00:00 UTC and never be
    fetched again; and Garmin keeps revising yesterday's daily summary until the watch syncs.
    Upserts by PK make the re-fetch idempotent; the cost is 6 extra calls per run.
  - `run()` catches `GarminPersonalApiError` (key, rate-limit and transient). It sets the
    `SyncLog` to `status="error"`, puts `str(exc)` in the error message, and **returns** the log
    without re-raising, so the scheduler doesn't crash. Because the window starts from the last
    *successful* run, an aborted run is re-pulled in full next time; `normalize_all` only runs
    after success, which is already the case today. All other exceptions keep their current
    handling (status error, then re-raise).
  - A module-level `_RUN_LOCK = threading.Lock()` wraps `run()`. Acquire it with
    `blocking=False`. If another run holds it (manual sync overlapping a scheduled one), log at
    INFO and return `None` without writing a `SyncLog`. Callers already ignore the return value.
    Why: two concurrent runs would delete-then-insert the same `garmin_exercise_summaries` rows
    and double the call rate.

- [ ] **Step 1: Write the failing tests** (fake client object, in-memory SQLite, shared engine
  per the repo's testing pattern):
  - `test_strength_activity_writes_summaries_without_extra_call`: the fake client's
    `get_activities` returns the fixture strength record. After `run()`, the
    `garmin_exercise_summaries` rows equal the fixture entry count, and the fake client received
    no other per-activity call.
  - `test_resync_replaces_summaries`: running twice over the same window leaves the same row
    count. Implement this as delete-then-insert per `activity_id`.
  - `test_run_records_key_error`: `get_activities` raises `GarminKeyError("key rejected …")`.
    The returned log has `status == "error"` and the message contains `"key rejected"`.
  - `test_run_aborts_on_rate_limit`: `get_activities` succeeds, then `get_daily_summary` raises
    `GarminRateLimitError` on the first day of a 5-day window. `get_daily_summary` was called
    exactly once, and `status == "error"`.
  - `test_run_records_transient_error`: `get_activities` raises `GarminTransientError`. The log
    is `status == "error"` and the method returns (no raise).
  - `test_sync_window_overlaps_previous_end`: with a successful log whose `sync_end` is D, the
    next window starts at D − 2 days. Update the existing
    `test_sync_window_uses_last_successful_sync` accordingly;
    `test_sync_window_defaults_to_30_days` and `test_sync_window_ignores_failed_syncs` stay.
  - `test_no_watch_night_writes_null_sleep_and_no_hrv`: `get_sleep` returns
    `{"calendarDate": d}` and `get_hrv` returns `None`. One `garmin_sleep` row with NULL
    metrics; zero `garmin_hrv` rows.
  - `test_concurrent_run_skipped`: hold `_RUN_LOCK` from the test, then call `run()`. It
    returns `None`, and the fake client and `sync_log` are both untouched.
  - Keep `test_run_marks_error_on_exception` (a `RuntimeError` still re-raises).
  - Delete the old tests that assert per-user `GarminAuth` client selection.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `.venv/bin/pytest tests/test_garmin_pipeline.py tests/test_normalization.py -v`.
  Expected: PASS.
- [ ] **Step 5:** Commit:
  `git commit -m "feat: GarminPipeline on Personal API client; strength summaries from activity list"`

### Task 6: Strength API routes read summaries

**Files:**
- Modify: `src/api/routes/workouts.py` (`/strength-volume` at 52, `/strength-max-weight` at 92,
  `/{workout_id}/exercise-sets` at 170; add `/{workout_id}/exercise-summary`). These routes use
  raw `text()` SQL joined `unified_workouts uw → garmin_exercise_sets es ON es.activity_id =
  uw.garmin_activity_id`, date from `uw.date`, scoping via `uw.user_id = :uid`, and
  `es.set_type = 'ACTIVE'`.
- Modify: `src/api/models.py` (add `ExerciseSummaryItem` next to `ExerciseSetItem` at 228)
- Test: create `tests/test_strength_routes.py`. `tests/test_workout_analysis.py` has no
  `TestClient`, and no test covers these routes today. Copy the fixture pattern from
  `tests/test_data_isolation.py` (240–267): module-scoped engine, `app.dependency_overrides`
  for `get_engine_dep` and `get_db`, `patch("src.api.main.start_scheduler")` /
  `stop_scheduler`, and a real JWT from `create_access_token(user_id)` as the auth header. Seed
  `garmin_activities` (FK target), `unified_workouts` with `garmin_activity_id`, and then set or
  summary rows.

**Interfaces:**
- Produces:
  - `ExerciseSummaryItem(exercise_category: str | None, exercise_name: str | None, set_count: int | None, repetition_count: int | None, volume_kg: float | None, max_weight_kg: float | None, duration_seconds: float | None)`
  - `GET /api/workouts/{workout_id}/exercise-summary -> list[ExerciseSummaryItem]`, with the
    same workout → `garmin_activity_id` resolution and `user_id` scoping as `/exercise-sets`.
  - The existing endpoints keep their response models unchanged.
  - Per activity, use set rows when any `ACTIVE` set rows exist; otherwise use summary rows.
  - Volume per session: Σ(`weight_kg` × `repetition_count`) over set rows, or Σ`volume_kg` over
    summary rows.
  - Max weight per session per exercise: `MAX(weight_kg)` from set rows, or `MAX(max_weight_kg)`
    from summary rows.

- [ ] **Step 1: Write the failing tests:**
  - `test_volume_from_summaries_only`: an activity with summaries only. Volume equals the sum of
    `volume_kg`.
  - `test_volume_prefers_sets_over_summaries`: an activity that has both. Volume equals the
    set-based value only.
  - `test_volume_same_date_mixed_sources_one_row`: two activities on one date, one with sets and
    one with summaries. The response has one row for that date whose value is the sum of both.
  - `test_max_weight_includes_legacy_sets`: one legacy activity (sets only) and one new activity
    (summaries only). Both dates appear.
  - `test_exercise_summary_endpoint_scoped_to_user`: another user's activity returns `[]`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. Shape for both aggregate routes, portable to SQLite and Postgres:
  ```sql
  SELECT date, SUM(v) AS total_volume_kg FROM (
      <existing sets query, selecting uw.date AS date, SUM(...) AS v, GROUP BY uw.date>
      UNION ALL
      SELECT uw.date AS date, SUM(s.volume_kg) AS v
      FROM unified_workouts uw
      JOIN garmin_exercise_summaries s ON s.activity_id = uw.garmin_activity_id
      WHERE uw.date BETWEEN :start AND :end AND uw.user_id = :uid AND s.volume_kg IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM garmin_exercise_sets es
                        WHERE es.activity_id = uw.garmin_activity_id AND es.set_type = 'ACTIVE')
      GROUP BY uw.date
  ) AS u GROUP BY date ORDER BY date
  ```
  The outer `GROUP BY` is what collapses a mixed date into one row; Postgres requires the
  derived-table alias. Use `NOT EXISTS`, not `NOT IN` (a NULL in the subquery would empty the
  result). Max-weight is the same shape with `MAX` and `GROUP BY date, exercise_name`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5:** Commit:
  `git commit -m "feat: strength routes read exercise summaries, keep set-level history"`

### Task 7: Owner helper, single-owner scheduler, sync gating, Garmin status

(The settings fields moved to Task 2.)

**Files:**
- Create: `src/database/owner.py`
- Modify: `src/ingestion/scheduler.py`:
  - Replace `get_users_to_sync` (96), `_run_garmin_multi_user` (157) and
    `_run_whoop_multi_user` (338) with `_run_garmin_sync()` and `_run_whoop_sync()`.
  - Delete the `_garmin_backoff` machinery (49–88), the startup `load_garmin_tokens_from_db`
    call (586) and the import of `load_garmin_tokens_from_db, save_garmin_tokens_to_db` at
    line 30, plus the in-function imports of `decrypt_credential`, `GarminAuthError` and
    `authenticate_user_garmin` (170–171).
  - `_schedule_catchup_if_stale` (480) stays, but its one-shot jobs must point at
    `_run_garmin_sync` / `_run_whoop_sync`. Rename the job names from "multi-user sync".
- Modify: `src/api/routes/sync.py`. Delete `_try_garmin_reauth` (194) and
  `_user_has_garmin_access` (229), the `has_garmin_token` import at line 15, and the
  `decrypt_credential` / `authenticate_user_garmin` imports at 217–218. Garmin is available iff
  `settings.garmin_personal_api_key` is set; `trigger_sync` keeps its **403** for the "not
  available" case, its 409 for "already running", and its 30-day manual window.
- Modify: `src/api/routes/auth.py` (`GET /garmin/status` at 304; it's `async def`, so run the
  probe via `await asyncio.to_thread(...)`; drop the `has_garmin_token` import at 311).
- Rewrite: `tests/test_scheduler.py` (it patches `load_garmin_tokens_from_db`,
  `save_garmin_tokens_to_db` and `get_users_to_sync`, all of which go away). Delete
  `tests/test_scheduler_multiuser.py`, but first move these into new homes:
  - the sync-route tests (`TestSyncStatusPerUser`, 643–747: status scoping, per-user running
    key, 409 for a second trigger, 403 for Whoop not connected) → `tests/test_sync_routes.py`,
    minus the credential-seeded case (`test_garmin_trigger_works_with_credentials_no_token`);
  - the catch-up tests (`TestCatchupOnRestart`, 749+) → `test_scheduler.py`, repointed at the
    new job functions;
  - the Whoop 401 token-removal test (`test_whoop_token_failure_removes_token_and_continues`,
    452) → `test_scheduler.py`, because Phase 3 changes that behavior and needs a test to flip.

**Interfaces:**
- Produces:
  - `def get_owner_user_id(engine: Engine) -> str | None`: the single `users.id`. Returns `None`
    when there are no users. Raises `RuntimeError` when there is more than one user. The DB starts
    fresh (Supabase was deleted, 2026-11-06), and Phase 3's `create_owner.py` refuses a second
    user, so more than one user means misconfiguration. The scheduler jobs catch this, log an
    error and skip the run instead of crash-looping.
  - `def _run_garmin_sync() -> None`:
    - No key → log once at INFO and return.
    - No owner → log a warning and return.
    - Otherwise, `GarminPipeline(db, user_id=owner).run()` (the pipeline computes its own
      overlapping window, Task 5). `run()` no longer raises for Garmin API errors; log the
      returned `SyncLog.status` and `error_message`.
    - Keep `_schedule_catchup_if_stale`.
  - `def _run_whoop_sync() -> None`: the same owner-only shape. No `whoop_{owner}` row in
    `token_store` → log at INFO and return (this replaces `get_users_to_sync`'s
    `whoop_connected` check). **Keep the current Whoop token behavior**, including the 401 →
    delete-token-row branch. Phase 3 fixes token rotation; don't change it here.
  - `GET /api/auth/garmin/status` returns
    `{"connected": bool, "configured": bool, "error": str | None}`. This is a superset of
    today's `{"connected": bool}`, which is all the frontend reads (`useApi.ts:401`,
    `Settings.tsx:390`, `ConnectDevicesPanel.tsx:270`), so the UI keeps working until Task 9.
    - `configured` = the key is set.
    - `connected` = `get_default_auth().last_error is None` **and** the `get_user_settings()`
      probe succeeded. Cache the probe result in memory for 10 min; a non-`None` `last_error`
      bypasses the cache so a scheduler-side key failure shows immediately.
    - `error` = `last_error`, or the `GarminKeyError` message from the probe, or `None`. A
      `GarminTransientError` from the probe gives `connected=false` with its message but does
      not set `last_error`.

- [ ] **Step 1: Write the failing tests:**
  - `test_get_owner_user_id_none_one_many`: 0 users → `None`, 1 user → its id, 2 users →
    `RuntimeError`.
  - `test_garmin_job_skips_when_multiple_users`: with 2 users, the job logs an error and
    constructs no pipeline (no exception escapes).
  - `test_garmin_job_skips_without_key`: with an empty key setting, no pipeline is constructed
    (monkeypatch `GarminPipeline`).
  - `test_garmin_job_runs_for_owner`: the pipeline is constructed with `user_id=<owner>`.
  - `test_garmin_job_logs_error_status_without_raising`: the patched pipeline's `run()` returns
    a `SyncLog(status="error", error_message="key rejected")`; the job logs it and returns.
  - `test_scheduler_registers_two_jobs`: `create_scheduler()` job ids are exactly
    `{"garmin_incremental_sync", "whoop_incremental_sync"}` (today's ids, which `sync.py`'s
    `_SCHEDULER_JOB_IDS` also depends on), and Garmin's interval is
    `settings.garmin_poll_interval_minutes`.
  - `test_catchup_jobs_use_single_owner_functions`: moved from `TestCatchupOnRestart`.
  - `test_garmin_status_reports_key_error`: the client stub raises `GarminKeyError("rejected")`.
    The response is `{"connected": false, "configured": true, "error": "rejected"}`.
  - `test_garmin_status_reports_scheduler_key_error_without_probe`: `last_error` is set on the
    default auth; the response carries it and the probe stub is not called.
  - `test_garmin_status_unconfigured`: `{"connected": false, "configured": false, "error": null}`.
  - `test_manual_garmin_sync_rejected_without_key`: `POST /api/sync/trigger/garmin` with no key
    returns **403** (what `_user_has_garmin_access == False` produces today, `sync.py:~281`).
  - `tests/test_sync_routes.py`: the moved status/409/403 tests, with the Garmin "available"
    case now driven by patching `settings.garmin_personal_api_key` instead of seeding
    `garmin_credentials`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `.venv/bin/pytest tests/test_scheduler.py tests/test_sync_routes.py tests/test_integration.py -v`.
  Expected: PASS.
- [ ] **Step 5:** Commit:
  `git commit -m "feat: single-owner scheduler and Personal API Garmin status"`

### Task 8: Remove the garminconnect surface

**Files:**
- Delete:
  - `src/clients/garmin_auth.py`
  - `src/auth/encryption.py`
  - `src/api/routes/garmin_credentials.py`
  - `tests/test_garmin_auth.py`
  - `tests/test_garmin_credentials.py`
- Modify:
  - `src/api/main.py`: drop the `garmin_credentials_router` import (15) and registration (104).
  - `src/api/routes/auth.py`: drop `POST /garmin/connect` (256–272), `GarminConnectBody` (251)
    and the `authenticate_user_garmin` / `GarminAuthError` imports (266, 269). No frontend code
    calls `/garmin/connect`.
  - `src/logging_config.py:50`: drop the `garminconnect` logger line.
  - `config/settings.py`: drop `garmin_email`, `garmin_password`, `garmin_token_dir` and
    `garmin_encryption_key`.
  - `.env.example`: drop `GARMIN_EMAIL`, `GARMIN_PASSWORD`, `GARMIN_TOKEN_DIR` and
    `GARMIN_ENCRYPTION_KEY`. Add `GARMIN_PERSONAL_API_KEY=` with a comment pointing at the key
    page and the 365-day recommendation. Change `GARMIN_POLL_INTERVAL_MINUTES` to 30. (The
    local `.env`, created 2026-11-06, already has `GARMIN_PERSONAL_API_KEY=` and a 30-minute
    poll interval.)
  - `docker-compose.yml`: drop the token-dir volume comments.
  - `pyproject.toml`: drop `garminconnect`. Then run `uv lock`; `curl_cffi` and `requests` are
    transitive from it and should disappear from `uv.lock`. `cryptography` stays (it comes from
    `python-jose[cryptography]`).
  - `scripts/initial_sync.py:50`: `GarminPipeline(db, user_id=owner)` with
    `owner = get_owner_user_id(engine)`; pass the same `user_id` to `WhoopPipeline` on line 44,
    which today also runs without one.
- **Leave alone:**
  - `src/api/routes/account.py`. Its `token_store` / `garmin_credentials` deletes (140–151) are
    harmless against tables that still exist, and `tests/test_account_settings.py` (442, 472)
    asserts on them. The whole route goes in Phase 3.
  - The `GarminCredentials` and `TokenStore` models and tables. Whoop still uses `TokenStore`.
  - All migration files.

- [ ] **Step 1:** Run `grep -rn -E "garminconnect|curl_cffi|garth|garmin_auth|GarminAuth|has_garmin_token|load_garmin_tokens|save_garmin_tokens|encrypt_credential|decrypt_credential|garmin_email|garmin_password|garmin_token_dir|garmin_encryption_key|GARMIN_EMAIL|GARMIN_PASSWORD|GARMIN_TOKEN_DIR|GARMIN_ENCRYPTION_KEY" src scripts tests config docker-compose.yml Dockerfile railway.toml`.
  Every hit is something to remove or update, except `account.py` and migration files.
- [ ] **Step 2:** Make the deletions and edits.
- [ ] **Step 3:** Run `.venv/bin/pytest -q`. Expected: all pass. Record the new total, which
  will be lower than the baseline because the deleted test files are gone.
- [ ] **Step 4:** Run `make lint`. Expected: clean. Re-run the Step 1 grep. Expected: no hits
  outside `account.py`, migration files, and the research and plan docs.
- [ ] **Step 5:** Smoke test. With a real key in `.env`, run `make run-api` and then
  `curl -s localhost:8000/api/health`. Log in, then
  `curl -s -H "Authorization: Bearer <jwt>" localhost:8000/api/auth/garmin/status` returns
  `connected: true`. `POST /api/sync/trigger/garmin` produces a `sync_log` row with
  `status="success"` and new `garmin_daily_summary` rows. Check the log for exactly one
  "token expires at" line across the status call and the sync (one exchange, shared instance).
- [ ] **Step 6:** Commit:
  `git commit -m "chore: remove garminconnect, password login, and credential encryption"`

### Task 9: Frontend Garmin card reads key status

Moved here from roadmap Phase 4.3–4.4 so Phase 2 merges on its own. After Task 8 the backend
returns 404 for `/api/garmin/credentials*`, and the Settings and Connect-devices Garmin cards
still call them (`useApi.ts:418–445`, `ConnectDevicesPanel.tsx:66`). Everything else in the UI
keeps working, because `GET /api/auth/garmin/status` stayed a superset.

**Files:**
- Modify: `frontend-react/src/hooks/useApi.ts`: `useGarminStatus` (401) returns
  `{ connected: boolean; configured: boolean; error: string | null }`. Delete
  `useGarminCredentialsStatus` and the store/delete credential hooks (410–445) and the
  `GarminCredentialsStatus` type.
- Modify: `frontend-react/src/pages/Settings.tsx` (Garmin card around 390): show
  Connected / Key not set / Key rejected (with `error`), a link to
  `https://connect.garmin.com/app/settings/personalApiToken`, and the hint "set
  `GARMIN_PERSONAL_API_KEY` in `.env` and restart". Remove the credential modal, the auto-sync
  toggle and the consent text.
- Modify: `frontend-react/src/components/ConnectDevicesPanel.tsx` (66, 270): same status
  rendering; delete the credential form. Keep the upload modal.

- [ ] **Step 1:** Make the edits. No new tests; the frontend has no test runner.
- [ ] **Step 2:** `cd frontend-react && npm run typecheck && npm run build`. Expected: clean.
- [ ] **Step 3:** `grep -rn "garmin/credentials\|GarminCredentialsStatus" frontend-react/src`.
  Expected: no hits.
- [ ] **Step 4:** With the API running, open Settings and confirm the Garmin card shows
  "Connected" with a valid key and "Key rejected" with `GARMIN_PERSONAL_API_KEY=bogus`.
- [ ] **Step 5:** Commit:
  `git commit -m "feat(frontend): Garmin card shows Personal API key status"`
