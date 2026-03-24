# PulseEngine Frontend Design Review

> Last updated: March 2026 — full UI audit after Phase 6 complete.

---

## What's Working Well

- **Dark theme** — `#050505` base with layered card elevations creates real depth; contrast is excellent throughout
- **Status color system** — teal/amber/coral applied consistently and semantically across MetricCard, StatusBadge, gauges, limiting factor cards
- **Typography trio** — Barlow Condensed (display), DM Sans (body), IBM Plex Mono (metrics) is well-chosen and purposeful
- **ReadinessArcGauge + ACWRGauge** — genuinely polished custom SVG components with animated fill
- **Entry animations on Today page** — stagger delays add real polish to the morning command center
- **Spacing discipline** — 4px/8px/12px/16px/20px grid maintained throughout
- **Mobile layout** — responsive grid, bottom tab bar, safe-area insets all correct

---

## Issues & Fixes

### 1. Styling approach is fragmented (HIGH)

`Today.tsx` uses locally-defined `Card()`, `Chevron()`, `SectionLabel()` helper functions with inline styles.
`Recovery.tsx` and `Training.tsx` use a mix of Tailwind classes and inline style objects. This makes the
codebase risky to refactor and produces subtle visual inconsistencies.

**Fix:** Extract `ExpandableSection`, `Button`, `SectionLabel`, `Chevron` as shared components.
All pages should use `ExpandableSection` for collapsible rows.

---

### 2. No shared Button component (HIGH)

Buttons are styled `<button>` elements, `<div onClick>` elements, and `<NavLink>` — each styled
independently. Hover, disabled, and loading states are implemented differently (or not at all) per usage.

**Fix:** Create `Button.tsx` with variants (primary, secondary, ghost), sizes (sm/md/lg), and
loading/disabled states. Standardize all interactive controls onto it.

---

### 3. Animations are incomplete (MEDIUM)

Entry animations exist only on Today page. Collapsible sections show/hide with no transition.
Skeletons disappear instantly with no fade-out when data loads.

**Fix:**
- Use CSS `max-height` transition in `ExpandableSection` for smooth enter/exit (~250ms)
- Add `opacity` + `translateY` fade-out to skeleton → content transitions
- Add stagger entry animations (`animate-fade-in delay-*`) to Training, Recovery, Insights page sections

---

### 4. Interactive states are incomplete (MEDIUM)

- No `:focus-visible` ring on expandable buttons, sparkline buttons, or clickable cards — keyboard nav is broken
- Many hover states use inline `onMouseEnter`/`onMouseLeave` JS handlers instead of CSS/Tailwind `hover:` variants
- Some clickable `<div>` elements are missing `cursor-pointer`, `role="button"`, `tabIndex={0}`

**Fix:** Add `focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50` to all
interactive elements. Migrate hover state handlers to Tailwind `hover:` classes where possible.

---

### 5. Empty/error states are generic (MEDIUM)

`NoDataState` shows `📡 No data yet` everywhere regardless of context. First-run vs no-data-in-range
vs device-not-connected are meaningfully different situations.

**Fix:** Pass context-specific messages to `NoDataState` at each call site:
- Today: "Connect a device to see your dashboard" → renders `ConnectDevicesPanel` (already done)
- Training: "No workouts found in this date range"
- Recovery: "No sleep data found — check your date range"
- Insights: "Sync at least a week of data to unlock trends and anomalies"

---

### 6. Anomaly feed has no visual priority (MEDIUM)

All anomaly cards in the Insights feed render at identical visual weight. A `|z| > 3` anomaly
and a `|z| = 2.1` anomaly look the same.

**Fix:** Add left-border accent keyed to z-score severity:
- `|z| ≥ 3.0` → coral (`--status-alert`) border
- `|z| ≥ 2.5` → amber (`--status-caution`) border
- `|z| < 2.5` → subtle default border

---

### 7. Correlation cards are visually indistinguishable (MEDIUM)

The three correlation cards (HRV↔Recovery, Strain↔Next-Day, Sleep↔Battery) share identical styling.
They blur together on a quick scan.

**Fix:** Give each a metric-specific color accent on the top border or left border:
- HRV ↔ Recovery → teal (`--status-excellent`)
- Strain ↔ Next-Day → amber (`--status-caution`)
- Sleep ↔ Battery → blue (`--brand`)

---

### 8. Settings page needs visual grouping (MEDIUM)

All sections — sync status, device management, preferences, and danger actions — have the same
visual density with no grouping. Danger actions (delete account) have no visual separation from
normal settings.

**Fix:** Add section headers with `SectionLabel` and subtle section dividers. Group into:
1. **Devices & Sync** — Whoop, Garmin, manual sync
2. **Data Overview** — stats table
3. **Preferences** — theme, sleep target
4. **Account** — password change, data export, delete account (danger zone with alert tint)

---

### 9. ReadinessArcGauge glow is too subtle (LOW)

The radial glow (`opacity: 6–8%`) is barely perceptible. Doesn't reinforce the score's status color.

**Fix:** Increase glow opacity to ~18–22% and switch the score/badge area to use
`filter: drop-shadow()` on the SVG progress arc for a sharper, more localized glow effect.

---

## Implementation Tracking

| # | Change | Status |
|---|--------|--------|
| 1 | Write FRONTEND_DESIGN.md | ✅ Done |
| 2 | Create Button, ExpandableSection, SectionLabel shared components | ✅ Done |
| 3 | Refactor Today.tsx to use shared components | ✅ Done |
| 4 | Fix animation system (collapsible transitions + skeleton fade-out) | ✅ Done |
| 5 | Add focus states + keyboard nav to all interactive elements | ✅ Done |
| 6 | Add severity accents to Insights anomaly feed | ✅ Done |
| 7 | Differentiate correlation cards in Recovery + Insights | ✅ Done |
| 8 | Add visual grouping to Settings page | ✅ Done |
| 9 | Increase ReadinessArcGauge glow visibility | ✅ Done |
