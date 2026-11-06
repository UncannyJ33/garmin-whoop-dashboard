# Logic-review fixes
Backend 1-5 and frontend 6-11 all fixed. Extra: ApiTest.tsx `d?.score` (compiler flagged after item 8).
Item 5: CSV stride now cm via `_stride_cm` (round 1dp). Item 5b: training.py docstring 204 claim removed (route never returns 204).
Item 9: removed redundant ['workouts'] invalidation; kept garmin-status (not covered by helper).
Item 10: useLocalToday date added to readiness/today, limiting-factors, load-ratio keys (prefixes unchanged).
Skipped: Showcase mock stride (Phase 4), anomaly_cache recompute (Phase 6).
Verification: pytest 942 passed, ruff clean, bash -n OK, typecheck+build pass. Dist output untracked/ignored.
