# Batch B2 (frontend) report
Commits: 03964e8, plus second commit (see git log).
Fixed: H5 H6 H9 M18 M20 M22 M23 M24 M25 M29 M39 L4 L5 L6 L7 L38 L39 L42 L44 L57 L58 L59 L60(types relocated only; backend model already exists: CSVImportResponse/UploadResponse) L70 L75 L76 L77 L78 L79 (Settings+ConnectDevicesPanel; Onboarding copy left for Phase 4)
Skipped: L40 (decision: empty-range NoDataState), L72 (block no longer duplicated after Garmin Personal API swap), L71 (optional chartDefaults, not done), L74 (instructed).
Notes: Insights DayButton now shares the memo'd component (hover colour differs slightly). invalidateWorkoutQueries now also invalidates sleep/trends/insights/recovery on import (was incomplete). useTrainingLoadRatio typed T|null. L38 covers Training/Recovery secondary queries.
