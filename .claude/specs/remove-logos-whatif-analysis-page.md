# Spec: Remove Logos from What-If Analysis Page

## Overview
The What-If Analysis page (`/what-if/dashboard`, `DashboardPage.tsx`) and
every component it composes prefixed nearly every section/card heading,
toggle label, button label, and search placeholder with a decorative emoji
"logo" (📊, 🎯, 🏷️, 🕐, 🔎, 🔧, 📈, 🔍, ⚡, 📋, 🗓️, 📥, plus per-metric-type
icons on individual KPI tiles). This spec removes those decorative icons
across the whole page, leaving plain text. It does **not** touch the
app-wide sidebar branding (`Sidebar.tsx`'s "SoftSense AI" mark) — that was
a different, unrelated element covered in an earlier (now superseded)
reading of this request; say so explicitly if that should still change too.

**Final scope (superseding the original draft's narrower scope boundary)**:
after two rounds of follow-up correction, the intent turned out to be
"strip every decorative icon on this page," not "keep functional-looking
ones." The 🚀 Compute button icon and the 📥 Export button icons — originally
drafted as kept, status-adjacent icons — were removed too, as was
`KpiCardsRow.tsx`'s `iconFor()` function that gave each KPI tile a
metric-type icon (🌡️ temp, 🧭 pressure, 💧 flow, ⚡ power, ⚙️ speed, 📉 loss,
🏷️ fallback) — that function is now deleted entirely, not just its call
site. The only emoji still intentionally present anywhere on this page are:
🔒 (the "Simulation overrides are locked" callout — a genuine access-state
indicator, never flagged for removal) and the direction/grade indicators
that are also functional, not decorative: ▲/▼ expand-collapse carets, the
▲/▼/– KPI change-direction glyph, ⏳ "Recalculating…", ↺ "Reset All", and
🟢/🟡/🔴 R² grade dots in `components/KpiCard.tsx`.

## Depends on
None — purely UI text/prop edits to existing components already used on
this page.

## Backend changes
No backend changes.

## Frontend changes

- **Modify**: `frontend/src/components/SectionBanner.tsx`
  - Make the `icon` prop optional (`icon?: string`) and render the
    `<span className="icon">` only when `icon` is provided. This component
    is shared with Feature Selection and Preprocess pages (which still
    pass an icon) — the prop must stay backward compatible for them.

- **Modify**: `frontend/src/pages/WhatIf/DashboardPage.tsx`
  - Both `<SectionBanner icon="📊" title="What-If Analysis" .../>` calls
    (the gate-not-ready early return, and the main render) — drop the
    `icon="📊"` prop.
  - `<h3>🎯 Target Section</h3>` → `<h3>Target Section</h3>`
  - `<h3>🏷️ Tag Source</h3>` → `<h3>Tag Source</h3>`
  - `<h3>🕐 Baseline Process Snapshot</h3>` → `<h3>Baseline Process Snapshot</h3>`
  - Compute button label — drop the `🚀 ` prefix from
    `` `🚀 Compute What-If Scenario (...)` ``

- **Modify**: `frontend/src/pages/WhatIf/BaselineValuesPanel.tsx`
  - Toggle button label `{open ? '▲' : '▼'} 🔎 Baseline Process Values at
    Selected Timestamp` → drop `🔎 ` only, keep the `▲`/`▼` caret.

- **Modify**: `frontend/src/pages/WhatIf/SimulationOverridesPanel.tsx`
  - Both `<h3>🔧 Simulation Overrides</h3>` occurrences (the empty-tags
    early return and the main render) → `<h3>Simulation Overrides</h3>`.
  - "Filter tags by name…" placeholder — drop its `🔍 ` prefix.

- **Modify**: `frontend/src/pages/WhatIf/ActualVsEstimatedTable.tsx`
  - `<h3>📈 Actual vs Estimated Scenario Output</h3>` → drop `📈 `.
  - "Filter parameters…" placeholder — drop its `🔍 ` prefix.
  - "Export Baseline vs Simulation Matrix" button — drop its `📥 ` prefix.

- **Modify**: `frontend/src/pages/WhatIf/ValidationFiltersPanel.tsx`
  - `<h4>🔍 Correlated Historical Validation Sets</h4>` → drop `🔍 `.
  - Collapsible `<summary>🔍 Validation Filters — ...</summary>` → drop `🔍 `.
  - "Find a tag column…" placeholder — drop its `🔍 ` prefix.
  - "Export Unified Comparison & Historical Validation Data" button — drop
    its `📥 ` prefix.

- **Modify**: `frontend/src/pages/WhatIf/TagSourcePanel.tsx`
  - `SOURCE_LABEL` map: drop the leading emoji from each value —
    `'⚡ Tag Source: Wizard Mapping'` → `'Tag Source: Wizard Mapping'`,
    `'📋 Tag Source: Config Sheet'` → `'Tag Source: Config Sheet'`,
    `'🏷️ Dynamic Tag Selection'` → `'Dynamic Tag Selection'`.

- **Modify**: `frontend/src/pages/WhatIf/TargetSectionSelector.tsx`
  - Label `🎯 Target Section (compute this section and everything upstream
    of it)` → drop `🎯 `.

- **Modify**: `frontend/src/pages/WhatIf/TimestampSelector.tsx`
  - Selected-snapshot trigger label `🗓️ {displayLabel}` → drop `🗓️ `.

- **Modify**: `frontend/src/pages/WhatIf/KpiCardsRow.tsx`
  - Toggle button label `{open ? '▲' : '▼'} 📊 Key Performance Indicators
    (...)` → drop `📊 `, keep the `▲`/`▼` caret.
  - "Filter KPIs…" placeholder — drop its `🔍 ` prefix.
  - Delete the `iconFor(tag)` function entirely (not just its call site) —
    it's dead code once its only caller stops using it. Update
    `WhatIfKpiCard`'s tile label from `{iconFor(kpi.tag)} {kpi.tag...}` to
    just `{kpi.tag.replace(/_/g, ' ')}`.

No component's props/behavior change beyond `SectionBanner`'s `icon`
becoming optional — everything else is a text-literal edit or (for
`iconFor`) a dead-function removal.

## Persistence / data changes
No persistence changes.

## Files to change
- `frontend/src/components/SectionBanner.tsx`
- `frontend/src/pages/WhatIf/DashboardPage.tsx`
- `frontend/src/pages/WhatIf/BaselineValuesPanel.tsx`
- `frontend/src/pages/WhatIf/SimulationOverridesPanel.tsx`
- `frontend/src/pages/WhatIf/ActualVsEstimatedTable.tsx`
- `frontend/src/pages/WhatIf/ValidationFiltersPanel.tsx`
- `frontend/src/pages/WhatIf/TagSourcePanel.tsx`
- `frontend/src/pages/WhatIf/TargetSectionSelector.tsx`
- `frontend/src/pages/WhatIf/TimestampSelector.tsx`
- `frontend/src/pages/WhatIf/KpiCardsRow.tsx`

## Files to create
No new files in the implementation itself. Test infrastructure was
bootstrapped as part of `/test-feature` (first frontend tests in the
repo): `frontend/vitest.config.ts`, `frontend/src/test/setup.ts`, and one
colocated `<Component>.test.tsx` per file above.

## New dependencies
No new runtime dependencies. Dev/test dependencies added by
`/test-feature`'s bootstrap: `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`.

## Rules for implementation
- Text-only edits — don't restructure any component's layout or logic
  while doing this, beyond `SectionBanner.icon` becoming optional and
  `iconFor` being deleted as dead code.
- Confirm `SectionBanner`'s other 6 call sites (Feature Selection,
  Preprocess pages) are unaffected — they must keep rendering their icon
  exactly as before.
- Leave a heading element in place even with no icon (don't collapse
  `<h3>Title</h3>` into something else) — only the emoji prefix goes.

## Definition of done
- [x] Visiting `/what-if/dashboard` (both the locked/gate state and the
  unlocked state) shows no emoji next to "What-If Analysis," "Target
  Section," "Tag Source," "Baseline Process Snapshot," "Baseline Process
  Values at Selected Timestamp," "Simulation Overrides," "Actual vs
  Estimated Scenario Output," "Correlated Historical Validation Sets," or
  "Key Performance Indicators" — verified via `vitest` component tests for
  every file above (10 files, 18 tests, all passing); **manual browser
  confirmation at `/what-if/dashboard` itself is still outstanding**
- [x] Tag Source's three source-mode labels (Wizard/Config/Historian) show
  no leading emoji — verified via test
- [x] The "Compute What-If Scenario" button and both "Export ..." buttons
  show no emoji — verified via test
- [x] Individual KPI tiles show no per-metric-type icon (🌡️🧭💧⚡⚙️📉🏷️) for
  any tag, including temp/pressure/flow-named ones — verified via test
- [x] 🔒 (locked callout), ▲/▼ carets, the KPI change-direction glyph, ⏳,
  ↺, and the 🟢/🟡/🔴 R² grade dots are still present, unchanged — covered
  by existing test assertions plus manual code review
- [x] Feature Selection and Preprocess pages' section banners still show
  their icons unchanged — verified via test and via `/code-review`
  (confirmed all 6 other `SectionBanner` call sites unaffected)
- [ ] No console errors/warnings introduced in the browser dev tools —
  **not yet checked; requires running the app in a browser**
