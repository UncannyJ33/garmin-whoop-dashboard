# /code-review xhigh — frontend-react/src (2026-11-06, unverified recipe output)

1. high — pages/Insights.tsx:616 (+730): null correlation → `.r` read on null throws in render when correlation queries are paused/errored → guard on data presence, not isLoading.
2. high — pages/Login.tsx:56/172: 422 `detail` is a list → rendered as React child → crash; also client.ts:72 "[object Object]" → normalize detail to string.
3. medium — pages/Today.tsx:126: "Last Night's Sleep" filters out today's wake-date sleep → include today (sleep keyed by wake date).
4. high — components/WorkoutRow.tsx:152: strength rows call /exercise-sets only; post-Phase-2 data lives in /exercise-summary → roadmap Phase 4.5 (decision/feature).
5. high (likely, untested) — pages/Training.tsx:942: Virtuoso useWindowScroll but <main> scrolls (Layout.tsx:139/154) → log renders empty → use customScrollParent.
6. medium — context/AuthContext.tsx:157: no refresh-on-401 mid-session → logout despite valid refresh token.
7. medium — context/DateRangeContext.tsx:30 (+hooks/useDateRange.ts:13): start/end memoized on days only → stale past midnight.
8. medium — pages/Settings.tsx:191 (+Onboarding.tsx:64): sync completion detection misses fast/skipped syncs; Onboarding can hang.
9. medium — pages/Settings.tsx:199 (+useApi.ts:389): post-sync invalidation lists incomplete/duplicated → shared helper.
10. low — components/ReadinessArcGauge.tsx:102 (+ACWRGauge.tsx:86, SleepStageBar.tsx:57): null score shows "Rest day" + endless skeleton → explicit no-data state.
11. medium — components/WorkoutRow.tsx:390: stride length shown in cm with " m" suffix → divide by 100 like Training.tsx:297.
12. low — pages/Training.tsx:371 (+Recovery.tsx:310): empty range replaces page incl. range buttons → keep controls.
13. low — App.tsx:71: single error boundary above Layout, never resets → boundary around <Outlet/> keyed by pathname.
14. low — pages/Training.tsx:940: Virtuoso without computeItemKey → expanded state follows index.
15. low — pages/Settings.tsx:106: "Sleep target" setting saved but never used → decision.

Cut for space: dead Demo.tsx/Button.tsx/useGarminCSVImport/useEnrichedAnomalies/useTheme; stale EnrichedAnomalyPoint/WeeklyLoadItem types; duplicated DayButton(3)/fmtDate(5)/STRENGTH_TYPES/KG_TO_LB/activityLabel/DigestCard/Spinner(3); Recovery fetches unused useSleepCorrelations.
