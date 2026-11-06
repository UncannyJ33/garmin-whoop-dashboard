# Garmin Connect Personal API — research notes

*Researched 2026-11-06. Garmin launched the Personal tier on 2026-10-21.*

The short version: Garmin now offers an official, free, self-serve API key for your own data.
It reaches the same Garmin Connect service paths that the unofficial `garminconnect` library
scrapes, so our activity, daily-summary and HRV parsing carries over almost unchanged. The
Personal API replaces password login, the session-token juggling, the Fernet credential store
and the 429 death-spiral logic outright.

What it costs us: strength workouts lose set-level detail and get per-exercise summaries instead,
and the sleep and HRV parsers need small field renames.

---

## 1. What the Personal tier is

| | Personal | Business Starter | Business Enterprise |
|---|---|---|---|
| Who | One person, own data | Apps, ≤ ~1,000 users free | Apps, paid per active user from 2027-04-01 |
| Access | Instant, self-serve key | Application form | Upgrade from Starter |
| Delivery | **Pull only** | Push only | Push or ping/pull |
| Data | Activity (JSON + .FIT), Health (JSON), Women's Health (JSON) | + Courses, Training | + Golf, historical backfill |
| Cost | Free | Free | $1,000 entry + per-user fee |

Terms in brief: it's "available for personal use" and "not intended for commercial applications
serving multiple end users." A single-user, self-hosted dashboard is squarely what it's for.
Don't share the key or let other people's accounts in. We haven't read the full Developer
Agreement. Third-party summaries cite an attribution requirement and AI-use clauses, so read the
agreement before adding any feature that feeds Garmin data to an LLM.

## 2. Auth flow (confirmed from Garmin's FAQ and the official client source)

1. **Create a key**: Garmin Connect web → <https://connect.garmin.com/app/settings/personalApiToken>
   → Create Key → accept the terms → pick an expiry (**30, 90, 180 or 365 days**). The key is
   shown **once**. A lost key can't be recovered, only deleted and regenerated. Garmin emails
   about a week before expiry.
2. **Exchange the key for an access token**:
   ```
   POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token
   Authorization: ApiKey <key>
   Accept: */*
   (no body)
   ```
   The response body is the **raw JWT as plain text**, not JSON. Read expiry from the JWT `exp`
   claim (decode it without verifying). Tokens last **24 h** or until the key expires, whichever
   comes first.
3. **No refresh tokens.** To renew, call the token endpoint again with the key. The official
   client caches the token and re-exchanges when less than 1 h remains. A 400, 401 or 403 from
   the exchange means the key is rejected or expired.
4. **Data calls**: `GET https://personal.connectapi.garmin.com<path>` with
   `Authorization: Bearer <jwt>` and `Accept: application/json`. Everything is GET. On a 401,
   re-exchange once and retry, because tokens can be revoked before `exp`.
5. **Revocation**: deleting the key in Garmin Connect kills the key and every token issued from it.

Scopes seen in a decoded token, per one unverified commenter: `CONNECT_READ`,
`PERSONAL_API_FITNESS_READ`, `PERSONAL_API_WELLNESS_READ`, `PERSONAL_API_USER_READ`,
`PERSONAL_API_NUTRITION_READ`.

## 3. Endpoints (all 26, from Garmin's OpenAPI spec)

The full spec is vendored at [`docs/reference/garmin-personal-api-openapi.json`](../reference/garmin-personal-api-openapi.json).
It was extracted on 2026-11-06 from the Swagger page at
<https://developer.garmin.com/gc-developer-program/personal/swagger-docs/>. It has 26 paths and
109 schemas. The servers are `personal.connectapi.garmin.com` and `.cn`.

**Activity**
| Path | Notes |
|---|---|
| `/activitylist-service/activities/search/activities` | `startDate`/`endDate` (YYYY-MM-DD, local start), `start` (offset), `limit` (default 99), plus many filters → `SummarizedActivityDTO[]` |
| `/activity-service/activity/{activityId}` | `ActivitySummaryDTO` (detail + splits) |
| `/activity-service/activity/{activityId}/workouts` | Planned workouts linked to the activity |
| `/download-service/files/activity/{activityId}` | Original file, delivered as a ZIP containing the .FIT |
| `/wellnessactivity-service/activity/summary/range/{from}/{until}` | Wellness activity summaries |

**Health**
| Path | Range limit | Response |
|---|---|---|
| `/usersummary-service/usersummary/daily?calendarDate=` | 1 day | `UserDailySummaryDto` (flat, 95 fields) |
| `/usersummary-service/v2/dailysummaries?startDate=&endDate=` | **1 year** | `{data: [UserDailySummaryV2DTO]}`, a **nested** shape (`movement`, `heartRate`, `stress`, `bodyBattery`, `pulseOx`, `respiration`, …) |
| `/usersummary-service/stats/steps/daily/{s}/{e}` | 28 days | |
| `/usersummary-service/stats/stress/daily/{s}/{e}` | 28 days | |
| `/usersummary-service/stats/hydration/daily/{s}/{e}` | 31 days | |
| `/sleep-service/sleep/dailySleep?date=` | 1 day | `DailySleepDTO` (**flat**) |
| `/sleep-service/sleep/dailySleepSummariesByDate?startDate=&endDate=` | 31 days | `DailySleepDTO[]` |
| `/hrv-service/hrv/{date}` | 1 day | `HrvChartDTO` (`hrvSummary`, `hrvReadings`). Returns **204** when there's no data |
| `/hrv-service/hrv/daily/{from}/{to}` | not stated | `HrvDailySummaryDTO` |
| `/wellness-service/wellness/bodyBattery/reports/daily?startDate=&endDate=` | 31 days | `BodyBatteryDailyReportDTO[]` |
| `/wellness-service/wellness/dailyHeartRate?date=` | 1 day | |
| `/wellness-service/wellness/daily/spo2acclimation/{date}` | 1 day | |
| `/weight-service/weight/range/{s}/{e}`, `/weight-service/weight/all/{s}/{e}` | | Weight and body composition entries |
| `/goal-service/goal/user/effective/weightgoal/{s}/{e}` | | |
| `/biometric-service/heartRateZones/v2` | | |
| `/fitnessage-service/fitnessage/v2/{date}` | | |
| `/nutrition-service/food/logs/{date}` | | |

**Women's Health**: `/periodichealth-service/menstrualcycle/summary/{date}` and `/dayview/{date}`.

**User Profile**: `/userprofile-service/userprofile/settings`. Use it as a cheap "is my key valid" probe.

**Not in the spec**: training readiness, training status, acute/chronic load, VO2max/max-metrics
endpoints, respiration day-detail, and **strength exercise sets** (`/exerciseSets`). There are no
webhooks.

**Rate limits**: none documented anywhere: not in the spec, the FAQ or the official client,
which has no 429 handling. Be polite. Use a small delay between calls and the range endpoints for
backfill, and abort the run on the first 429.

**History depth**: not documented. Commenters report that pulling historical data and FIT files
works. **Verify this with a real key** (relaunch plan, Phase 1).

## 4. Mapping to our current Garmin code

`src/clients/garmin_client.py` exposes six methods that `src/ingestion/garmin_pipeline.py`
calls. Each one's Personal API equivalent:

| Our method (garminconnect call) | Personal API | Shape vs our transform |
|---|---|---|
| `get_activities(start, end)` (`get_activities_by_date`) | `activitylist-service/.../search/activities?startDate&endDate&start&limit`, paging until a short page comes back | **Same.** Every field `transform_activity` reads is in `SummarizedActivityDTO`, including `vO2MaxValue`, `activityTrainingLoad`, `avgGroundContactTime`, `avgVerticalOscillation`, `avgVerticalRatio` and `avgStrideLength`. Also adds `hrTimeInZone_1..5`, `summarizedExerciseSets`, `totalSets` and `totalReps`. |
| `get_daily_summary(d)`, which merged 4 calls (`get_stats`, `get_heart_rates`, `get_body_battery`, `get_stress_data`) | **One call**: `usersummary-service/usersummary/daily?calendarDate=d` | **Same.** `UserDailySummaryDto` has every field `transform_daily_summary` reads: steps, distance, calories, RHR/min/max HR, stress avg/max, `bodyBatteryHighestValue`/`LowestValue` and `averageSpo2`/`lowestSpo2`. |
| `get_sleep(d)` (`get_sleep_data`) | `sleep-service/sleep/dailySleep?date=d` | **Different.** The response is flat, with no `dailySleepDTO` wrapper. `sleepScore` becomes `sleepScores.overall.value`; `sleepScores` is a map of `SleepScoreItem {value, qualifierKey, …}`, and the `overall` key is assumed, so verify it. `averageStressLevel` becomes `avgSleepStress`. Timestamps are still named `sleepStartTimestampGMT`/`EndTimestampGMT`, but the spec declares them `string` (`format: date-time`) while its description says "in ms" and garminconnect returned Unix-ms integers. The transform must accept both; the spike records which one comes back. Stage seconds are unchanged. |
| `get_hrv(d)` (`get_hrv_data`) | `hrv-service/hrv/{d}` (same path) | **Mostly the same.** `hrvSummary` and `baseline {lowUpper, balancedLow, balancedUpper}` are unchanged. The spec field is `lastNightAvg`, but our transform reads `lastNight` (`garmin_pipeline.py:258`), which is probably an existing bug that leaves `last_night_avg_ms` always NULL. Handle the 204 as "no data". |
| `get_exercise_sets(id)` (`get_activity_exercise_sets`) | **No endpoint.** Use `summarizedExerciseSets` from the activity list record. | **Coarser.** You get one row per exercise (`category`, `subCategory`, `sets`, `reps`, `volume`, `maxWeight`, `duration`) instead of one row per set. The spec documents the units: `maxWeight` in **grams**, `volume` as grams × reps summed, `duration` in **milliseconds**. For set-level detail, parse the `.FIT` from `download-service`; FIT `set` messages carry reps, weight and category. That's a follow-up, not part of the basic relaunch. |
| `get_activity_detail(id)` (unused in ingestion) | `activity-service/activity/{id}` | n/a |

What we can delete once we switch: `garminconnect` and `curl_cffi`, `src/clients/garmin_auth.py`
(551 lines), password login, `GARMIN_EMAIL`/`GARMIN_PASSWORD`/`GARMIN_TOKEN_DIR`, Garmin rows in
`token_store`, `src/auth/encryption.py` and `GARMIN_ENCRYPTION_KEY`, the `garmin_credentials`
routes and UI, and the scheduler's per-user backoff and auto-disable machinery.

## 5. Gaps and risks

- **Stripped fields.** Runalyze reported on 2026-10-06 that Garmin strips undocumented fields
  (VO2max estimate, recovery time, performance condition, training effect and others) from FIT
  files delivered through the business sync API. Sources disagree on whether Personal-key
  downloads are affected. The JSON schema still *declares* `vO2MaxValue` and
  `activityTrainingLoad`, but a commenter says VO2max and training status come back empty on
  Personal. Our readiness score uses `training_load`, so confirm it's populated before relying
  on it.
- **No webhooks.** That's fine: we already poll incrementally from the last `sync_log.sync_end`.
- **Key expiry.** It lasts a year at most, so the app has to report "key rejected/expired"
  clearly instead of failing silently. Pick the 365-day expiry and set a calendar reminder.
- **No documented rate limits.** Keep polling modest: every 30–60 min is plenty for one person.
- **The official client requires Python ≥ 3.12 and `requests`.** We don't need it, since the
  wire protocol is about 100 lines on our existing `httpx`. It's useful as a reference, and its
  `gc-personal` CLI is handy for poking at endpoints.

## 6. Status of the unofficial path (why we're leaving it)

- **garth is deprecated.** Its final release was 0.8.0 on 2026-03-28: "Garmin changed their
  auth flow, breaking the mobile auth approach that Garth depends on." New logins don't work.
- **garminconnect** dropped garth in 0.3.0 and now runs its own mobile-SSO flow; it needs
  `curl_cffi` and Python ≥ 3.12. Its release notes describe an ongoing arms race: mobile login
  returned 429 on every attempt from April to October 2026 (fixed in 0.3.20 on 2026-10-23),
  Garmin blocks on client fingerprint, and it has started returning the non-standard HTTP 427.
  We pin 0.3.1, so our password login has been degraded since April.
- Garmin has cut off third parties that scraped or stored credentials (Terra, intervals.icu
  briefly). An official key removes that risk for us.

## 7. Whoop: what changed since April 2026

- **v2 only.** v1 is unsupported and **v1 webhooks are no longer published**. Our client already
  targets `https://api.prod.whoop.com/developer/v2`.
- **2026-09-23**: Cycles gained a `step_count` field under the existing `read:cycles` scope.
  It's optional for us.
- **Refresh tokens rotate.** Using a refresh token invalidates the old access token *and* the old
  refresh token, so concurrent refreshes fail. What our code does:
  1. `_store_tokens` (`whoop_auth.py:194`) **does** persist a `refresh_token` whenever the
     response carries one; only its comment ("Whoop only returns a new refresh token on initial
     exchange") is wrong. Not a bug, but the comment should go.
  2. Nothing serializes refreshes across the scheduler thread (its own `asyncio.run()` loop) and
     the FastAPI loop (manual sync, webhook). That's the real bug.
  On a single-user box this shows up as random forced re-auths, made worse because the scheduler
  deletes the token row on a 401.
- **Webhooks**: v2 signs requests with `X-WHOOP-Signature` and `X-WHOOP-Signature-Timestamp`
  (base64 HMAC-SHA256 of `timestamp + raw_body` keyed by the client secret). Our receiver verifies
  nothing, and since migration 008 it reads a token row that no longer exists, so it's broken
  anyway. For a personal box, rely on polling and drop the webhook.
- **App tiers**: new apps start on Sandbox, which allows **10 members**. That's plenty for
  personal use, and no approval is needed.
- **Rate limits**: 100 requests/min and 10,000/day by default.

## 8. To verify with a real key (relaunch Phase 1 spike)

1. Token exchange works and the JWT `exp` is about 24 h out.
2. Activity list: are `vO2MaxValue`, `activityTrainingLoad` and the running-dynamics fields
   populated for a recent run? What are the `summarizedExerciseSets.maxWeight` units for a
   strength session?
3. Sleep: is the `sleepScores` key `overall`? Do we get data on nights Garmin wasn't worn?
4. HRV: `lastNightAvg` present, and 204 on nights without the watch.
5. History depth: request a date about 2 years back for the daily summary, activities and one
   FIT download.
6. Note any 429 or `Retry-After` behavior while pulling one month of daily summaries at 1 call/sec.

## Sources

- Garmin Personal API FAQ: <https://developer.garmin.com/gc-developer-program/personal/personal-faq/>
- Garmin program overview (tiers): <https://developer.garmin.com/gc-developer-program/overview/>
- Garmin Personal API Swagger: <https://developer.garmin.com/gc-developer-program/personal/swagger-docs/>
- Official Python client (Apache-2.0, v1.0.0, 2026-10-21): <https://github.com/garmin/connect-personal-api-python>
- Community MCP server using the Personal API: <https://github.com/Mason-Levyy/garmin-personal-mcp>
- DC Rainmaker on the program revamp: <https://www.dcrainmaker.com/2026/10/garmin-connect-api-revamps-connect-developer.html>
- the5krunner on the Personal key: <https://the5krunner.com/2026/10/22/garmin-personal-api/>
- Sahha on tiers, fees and terms: <https://sahha.ai/blog/garmin-connect-api-reopened-fees/>
- garth deprecation: <https://github.com/matin/garth>
- garminconnect releases: <https://github.com/cyberjunky/python-garminconnect/releases>
- WHOOP API changelog: <https://developer.whoop.com/docs/api-changelog>, webhooks: <https://developer.whoop.com/docs/developing/webhooks/>, OAuth: <https://developer.whoop.com/docs/developing/oauth>, app approval: <https://developer.whoop.com/docs/developing/app-approval>
