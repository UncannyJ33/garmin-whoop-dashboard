# Batch B4 report
Done: L49 (SyncState = running|success|error; SyncStatusItem additionally allows API-only never_synced), M26 (WeeklyDigestMetricsResponse Pydantic + TypedDict in analytics; key order/JSON unchanged), M30, M31 (Severity Literal in analytics/Pydantic/TS), TS mirrors of B3 Literals (Recommendation, PrimarySource, SleepDebtTrend, AnomalyDirection, TrendDirection, AcwrZone, AcwrTrend), L63 (DateRangeParams, 11 routes in readiness/recovery/sleep/training/trends/workouts; all identical required start/end).
L63 note: ordering check lives in DateRangeParams.validated() called in the route body, so 401/422 precedence is unchanged.
Frontend fallout from tighter unions (dead comparisons removed, behaviour same): Insights.tsx 'insufficient_data' checks (never produced), Recovery.tsx 'declining' sleep_debt_trend branch (never produced). Demo.tsx: severity 'poor' check -> constant 'caution'; mock trend_direction 'increasing' -> 'improving' (invalid value; demo-only).
LATENT BUG (not fixed): Recovery.tsx sleep_debt_trend 'worsening' renders text-moderate; the removed 'declining' branch was clearly meant to be 'worsening' -> text-poor.
Step 0: account.py formatting diff restored.
Tests 941 passed; ruff clean; typecheck + build clean.
