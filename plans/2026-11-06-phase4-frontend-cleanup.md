# Phase 4: Frontend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the React app into a single-user personal UI. Remove the SaaS pages (landing, privacy, onboarding, showcase, API test, demo, PWA) and the calls to backend routes Phase 3 deletes. Show Whoop "needs re-auth". Show strength per-exercise summaries in the workout row.

**Architecture:** This is frontend-only, with one exception: delete `pulse-demo/` and its Dockerfile steps. The `spa_fallback` hardening (stay inside `dist/`, 404 for unknown `/api/*`, a no-cache shell, no `/demo` case) moved to **Phase 3 Task 0** as a security fix, and is already done when this phase starts.

Routing simplifies to:
- public: `/login`, plus `/help/garmin-export` (GarminHelp stays public and unchanged)
- authenticated: Today (`/`, the index route under `ProtectedLayout`), Training, Recovery, Insights and Settings
- the legacy redirects, and a catch-all to `/`

**Tech Stack:** React 18, TypeScript, Vite 5, Tailwind 3, TanStack Query v5, react-router 6. There is no frontend test runner. Verification is `npm run typecheck` and `npm run build`. Task 5 also changes `main.py` and adds tests, so it also runs backend lint and serial pytest.

**Spec:**
- [`plans/2026-11-06-personal-relaunch-roadmap.md`](2026-11-06-personal-relaunch-roadmap.md), Phase 4. Q1 is answered as local-only, so the PWA is removed.
- Backend contract from [`plans/2026-11-06-phase3-saas-cut.md`](2026-11-06-phase3-saas-cut.md):
  - These routes are deleted: `/register`, `/feature-flags`, `DELETE /api/account`, `/api/webhooks/*`, `/api/garmin/csv-import`, `/api/waitlist`.
  - `GET /api/auth/whoop/status` now returns `{connected, needs_reauth, error}`. Phase 3 keeps the token row on re-auth, so the re-auth state is `connected: true, needs_reauth: true`. **`needs_reauth` takes precedence over `connected` in the UI.**
  - `GET /api/auth/whoop/url` is no longer allowlist-gated (Phase 3 Task 3). "Connect Whoop" is therefore always available. The feature-flag gate and its "coming soon" branches go.
  - The only way to create the account is `make owner EMAIL=…` (Phase 3 Task 1).
  - Phase 3 Task 0 hardened `spa_fallback`, and its tests live in `tests/test_spa_routes.py`. Unknown `GET /api/*` now returns 404.

**Verified frontend calls to deleted routes** (a grep of `frontend-react/src`, 2026-11-06). Everything else the frontend calls survives Phase 3. None of Phase 2's deleted Garmin credential routes is still called.

| Deleted route | Caller | Removed in |
|---|---|---|
| `POST /api/auth/register` | `Login.tsx:31` | Task 2 |
| `GET /api/auth/feature-flags` | `useFeatureFlags`. It's read by `Settings.tsx:121` and `ConnectDevicesPanel.tsx:119`, and by Onboarding | Task 2 (Onboarding in Task 1) |
| `DELETE /api/account` | `useDeleteAccount`, used by the Settings Danger Zone | Task 2 |
| `POST /api/garmin/csv-import` | `useGarminCSVImport`, which already has no consumer | Task 2 |
| `POST /api/waitlist` | `Landing.tsx:147` | Task 1 |
| `/api/webhooks/*` | none | n/a |

## Global Constraints

- Same branch as Phase 3 (`feat/phase3-saas-cut`). Execute it after Phase 3, Task 9.
- No new dependencies. Removing `vite-plugin-pwa` is fine. Use no visual redesign, and keep the existing component and styling patterns.
- `landing/` is the pulsebuilt.net studio page; leave it untouched (D6). `pages/Landing.tsx` is a different thing: the SaaS page, which is deleted here.
- Keep `GarminHelp.tsx` and `/help/garmin-export`, because the export import is the backfill path.
- This phase pulls two roadmap Phase 5 items forward:
  - removing the pulse-demo Dockerfile steps (part of 5.1)
  - deleting `frontend-react/vercel.json` (5.4)

  The Phase 5 plan treats both as done.
- Verify every task with `cd frontend-react && npm run typecheck && npm run build`, both clean. Run `make lint` and serial `.venv/bin/pytest -q` whenever Python changes.

## Review Focus

1. **Deep links to deleted routes** (`/privacy`, `/onboarding`, `/showcase`, `/dev/api-test`, `/demo`) don't produce a blank page. The catch-all sends them to `/`, and `/` sends an unauthenticated visitor to `/login`.
2. **Whoop `needs_reauth: true`** (with `connected: true`):
   - Settings shows "Needs reconnect", the `error` text, and a "Reconnect Whoop" button in place of "Sync Now". The button uses the existing OAuth URL flow.
   - The card updates once a manual Whoop sync finishes, with no page reload.
   - The OAuth callback lands on `/settings?whoop_connected=1`, which already refetches the status.
3. **A post-Phase-2 strength workout with no set rows.**
   - `WorkoutRow` shows the per-exercise summary table in lb, like the set table.
   - Bodyweight exercises (`max_weight_kg` null or 0) show "BW".
   - A legacy workout with set rows still shows the set table and makes no summary request.
4. **No remaining fetch** to a backend route deleted in Phase 3. Check it with the Done-when grep.
5. **No stale app from an earlier PWA install.** A browser that ran the old build on this origin has a Workbox service worker that answers navigations from its precache. After this change its update check for `/sw.js` would get `index.html` as `text/html` and fail. The old worker would then keep serving the old app forever, and the new `main.tsx` cleanup would never load. Two fixes:
   - Ship a self-destroying `public/sw.js` at that same URL.
   - Keep the `main.tsx` unregister for any browser that does load the new app.
6. **`spa_fallback` path traversal.** Today `GET /..%2F..%2Fdata%2Ffitness_dashboard.db` serves files outside `dist/`, because uvicorn unquotes `%2F` and doesn't remove dot segments. This was reproduced against a copy of the function. `docker-compose.yml` publishes `0.0.0.0:8000`, so the SQLite DB, Whoop tokens included, is readable from the LAN. **This is fixed in Phase 3 Task 0, moved there by controller ruling.**

---

### Task 1: Delete the SaaS pages and simplify routing

**Files:**
- Delete:
  - these pages: `pages/Landing.tsx`, `pages/Privacy.tsx`, `pages/Onboarding.tsx`, `pages/Showcase.tsx`, `pages/ApiTest.tsx`, `pages/Demo.tsx`
  - `components/DigestCard.tsx` and `components/WeekComparison.tsx`. Only Showcase imports them, which the import graph confirms. Every other component the deleted pages import has a live consumer.
- Modify:
  - `App.tsx`:
    - Remove the deleted pages' routes and imports. `Landing` is an eager import.
    - Delete `HomeRoute`. Put Today under `ProtectedLayout` as `<Route index element={<Today />} />`. `ProtectedLayout` already holds while initializing and redirects to `/login`.
    - Add a top-level catch-all `<Route path="*" element={<Navigate to="/" replace />} />`.
    - Keep `/help/garmin-export` public.
    - Drop `Layout`'s `children` prop if nothing else passes it.
  - `components/ConnectDevicesPanel.tsx`. Its Onboarding consumer is gone, and Today renders it bare as its empty state. Remove:
    - the Onboarding-only props (`onStartSync`, `onSkip`), `handleStartSync`, `anyConnected`/`showActions` and the action row
    - the `whoop_connected`/`whoop_error` redirect-back effect. The backend callback always redirects to `/settings`, and Settings handles those params.

    Then update the header comment.
  - Links to deleted routes: the `/privacy` link in `Login.tsx` (inside the register-only block) and the footer `/privacy` link in `Settings.tsx`. `Layout`, `Sidebar` and `Header` have none.
  - Stale copy:
    - `GarminHelp.tsx`: the "or during onboarding" text and the header comment
    - `GarminUpload.tsx`: the "Used in: Onboarding, Settings" comment
  - `styles/globals.css`: drop the `.prose-policy` block. Only Privacy uses it.

- [ ] Make the edits.
- [ ] `grep -rni -E "landing|privacy|onboarding|showcase|apitest|api-test|/demo" frontend-react/src` → no hits. `ls frontend-react/src/components` shows no `DigestCard` or `WeekComparison`.
- [ ] Run typecheck and build.
- [ ] Commit: `chore(frontend): remove SaaS pages; catch-all redirect`.

### Task 2: Make Login login-only, and remove calls to deleted backend routes

**Files:** `pages/Login.tsx`, `hooks/useApi.ts`, `pages/Settings.tsx`, `components/ConnectDevicesPanel.tsx`, `types/api.ts`. `AuthContext` has no register helper, so it isn't touched.

- [ ] `Login.tsx`:
  - Remove the `mode` state, the register branch, the toggle and the register copy.
  - Set `autoComplete` to `current-password`.
  - Add a one-line hint under the form: "No account? Run `make owner EMAIL=you@example.com` on the server."
- [ ] Delete these hooks and types:
  - `useFeatureFlags` and `FeatureFlags`
  - `useDeleteAccount`
  - `useGarminCSVImport` and `CSVImportResult`. They have no consumer today; `GarminUpload` uses `/api/garmin/upload`.
- [ ] Remove the feature-flag gate (`flagsQ`/`whoopOAuthEnabled`) in both Settings and `ConnectDevicesPanel`. "Connect Whoop" renders whenever Whoop isn't connected. Delete both "coming soon" Whoop branches.
- [ ] Settings: remove the delete-account state, handler and modal. Remove the whole Danger Zone section too; it holds only Delete Account.
- [ ] Settings keeps: data export, change password, theme, the Garmin key card, Whoop connect/disconnect, sync status and stats.
- [ ] `grep -rn -E "/api/(auth/register|auth/feature-flags|waitlist|webhooks|garmin/csv-import|garmin/credentials)|'/api/account'" frontend-react/src` → no hits. `/api/account/export` stays.
- [ ] Run typecheck and build.
- [ ] Commit: `chore(frontend): login-only; drop calls to removed backend routes`.

### Task 3: Whoop "needs re-auth" UI

**Interfaces:**
- `types/api.ts`: `WhoopStatus = { connected: boolean; needs_reauth: boolean; error: string | null }`.
- Precedence: `needs_reauth` wins over `connected`. Phase 3 keeps the token row, so both are true.
- Settings Whoop card, when `needs_reauth` is true:
  - The status dot and label read "Needs reconnect", in the existing error colours (`text-poor` / `bg-poor`). The `error` text goes below, in the existing error-box style.
  - The header button is "Reconnect Whoop" in place of "Sync Now". It uses the existing `handleConnectWhoop` (`GET /api/auth/whoop/url`, then redirect). "Disconnect Whoop" stays.
  - Hide the stale-sync warning, because it tells you to "tap Sync Now".
- Settings sync-completion effect: when a `whoop` run finishes, also invalidate `['auth', 'whoop-status', userId]`. Then a manual sync that hits re-auth shows it with no reload. `invalidateWorkoutQueries` doesn't cover `auth` keys.
- `ConnectDevicesPanel` Whoop card: show the same label, the error and "Reconnect Whoop" (existing handler). It only renders in Today's no-data empty state, so keep it minimal.
- After OAuth, the backend callback redirects to `/settings?whoop_connected=1`. Settings already invalidates the Whoop status there, and Phase 3 clears `auth_error` on a successful exchange. No new redirect handling is needed.
- Otherwise, render as today.

- [ ] Make the edits.
- [ ] Run typecheck and build.
- [ ] Commit: `feat(frontend): Whoop needs-reconnect state`.

### Task 4: Strength per-exercise summaries in `WorkoutRow`

**Interfaces:**
- `hooks/useApi.ts`: `useExerciseSummary(workoutId, enabled)` → `GET /api/workouts/{id}/exercise-summary` → `ExerciseSummaryItem[]`.
  - Query key `['workouts', 'exercise-summary', workoutId, userId]`. The `['workouts']` prefix keeps it inside `invalidateWorkoutQueries`.
  - Use `STALE.LONG` and the same `enabled` guards as `useExerciseSets`.
  - The type in `types/api.ts` mirrors `src/api/models.py:263` `ExerciseSummaryItem` exactly (verified): `exercise_category`, `exercise_name`, `set_count`, `repetition_count`, `volume_kg`, `max_weight_kg`, `duration_seconds`, all nullable.
- `components/WorkoutRow.tsx` `ExerciseSets`, in an expanded strength row:
  - Call `useExerciseSummary(id, setsQ.isSuccess && setsQ.data.length === 0)`, so legacy workouts with set rows make no extra request.
  - Show the skeleton while sets load, or while the sets are empty and the summaries load.
  - If there are set rows, show the existing set table, unchanged.
  - Otherwise, if there are summaries, show a table with columns Exercise, Sets, Reps, Max weight (lb) and Volume (lb). The set table is lb-only, with no kg toggle; match it:
    - Convert with `KG_TO_LB`, already imported from `utils/workoutTypes.ts`. Show weights to 1 dp and volume to 0 dp.
    - `max_weight_kg` null or 0 → "BW". Bodyweight is stored as 0; `strength-max-weight` filters on `> 0`.
    - `volume_kg` null or 0 → "—". Null counts → "—".
    - Keep the API order (`ORDER BY id`).
  - Exercise names: extract the set table's inline humanizer into one local helper that both tables use. Make it skip empty segments: today `"A__B"` throws on `w[0]`.
  - Otherwise, show the existing empty message, reworded: "No strength detail available for this workout."
- Cleanup item L74, since this task owns the file. The B2 cleanup batch skipped it, and the stat cells already share `DetailCell`. What's still repeated is the uppercase section-label `<p>` before each grid. Extract a local `SectionHeading` as a pure refactor with no visual change, or skip it if it can't stay one.
- [ ] Make the edits.
- [ ] Run typecheck and build.
- [ ] Commit: `feat(frontend): show per-exercise strength summaries`.

### Task 5: Remove the PWA, `pulse-demo` and the `/demo` mount; harden `spa_fallback`

**Files:**
- `frontend-react/package.json` and `package-lock.json`: drop `vite-plugin-pwa` with `npm uninstall vite-plugin-pwa`.
- `vite.config.ts`: remove the `VitePWA` import and plugin.
- Delete `public/manifest.json` and `components/InstallPrompt.tsx`. Remove `<InstallPrompt />` from `Layout.tsx`, its only consumer.
- `index.html`:
  - Drop `<link rel="manifest">` and these metas: `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`, `apple-mobile-web-app-title`, `mobile-web-app-capable`, `application-name`.
  - Keep the favicon, `apple-touch-icon`, `theme-color` and the icon PNGs.
- **Keep `hooks/useOnlineStatus.ts`.** `ErrorState.tsx` and `Layout.tsx`'s `OfflineBanner` use it. API network failures drive it, so it still tells you when the local server is unreachable.
- New `public/sw.js`: a self-destroying worker, served at the old worker's URL.
  - On install, call `skipWaiting`.
  - On activate, delete every Cache Storage entry, call `self.registration.unregister()`, then navigate each open window client to its own URL.
  - No Workbox and no fetch handler. Nothing registers it; it only replaces an existing registration when the browser checks for an update.
  - Add a header comment saying why, and that it can go once no browser still has the old PWA.
- `main.tsx`: add a one-time cleanup on startup. If `'serviceWorker' in navigator`, unregister every registration from `getRegistrations()` and delete all `caches` keys. Explain why in a comment. Move `clearSwCaches` here from `AuthContext.logout`, and remove it there.
- Delete `pulse-demo/`.
- `Dockerfile`: the pulse-demo steps are in the same `frontend-builder` stage, not a separate stage.
  - Drop lines 11–17, from `npm install -g pnpm` through `pnpm exec vite build`.
  - Drop lines 48–49, the `dist/demo` copy.
  - Confirm Phase 3 Task 8 already removed `COPY frontend/ ./frontend/` (line 38).
  - Leave the base images to Phase 5.
- `src/api/main.py` `spa_fallback`: already hardened in Phase 3 Task 0. Nothing to change here except confirming it no longer mentions `/demo`.
- `frontend-react/vercel.json`: delete it (Railway and Vercel are gone; Q1).

- [ ] Make the edits.
- [ ] Run typecheck and build. Check the build output:
  - `ls frontend-react/dist` shows no `registerSW.js`, `workbox-*.js` or `manifest.json`.
  - `dist/sw.js` exists, and `grep -c -E "workbox|precache" frontend-react/dist/sw.js` prints 0.
- [ ] `grep -n -E "pulse-demo|pnpm|COPY frontend/" Dockerfile` → no hits.
- [ ] Run `make lint` and serial `pytest`.
- [ ] Commit: `chore: remove PWA, pulse-demo and /demo mount`.

### Task 6: Docs touch-up

Phase 7 does the full docs pass. This task only fixes what Phase 4 makes wrong.

- [ ] `CLAUDE.md`:
  - From the "slated for removal" list (around line 11), remove the pages, `pulse-demo/`, `/demo` and registration items.
  - Around line 122: `spa_fallback` has no `/demo` case, stays inside `dist/`, and returns 404 for unknown `/api/*`.
  - Around line 123: drop `frontend-react/vercel.json` from the Phase 5 leftovers.
  - Add one line: the PWA is removed, and `public/sw.js` is only a kill-switch for old installs.
- [ ] `README.md`, unless Phase 3 already changed these lines:
  - Around lines 88–89, "Register an account at `/login`" becomes `make owner EMAIL=…`.
  - Around line 167, drop the `vercel.json` mention.
- [ ] Commit: `docs: Phase 4 frontend cleanup`.

---

**Done when:**
- Typecheck, build, lint and pytest are all green.
- The Task 1, Task 2 and Task 5 greps are clean.
- `ls frontend-react/src/pages` shows exactly: GarminHelp, Insights, Login, Recovery, Settings, Today, Training.
- `ls frontend-react/src/components` has no `DigestCard`, `WeekComparison` or `InstallPrompt`.
- `pulse-demo/` and `frontend-react/vercel.json` are gone.
