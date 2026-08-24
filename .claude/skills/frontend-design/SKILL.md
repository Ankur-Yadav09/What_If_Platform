---
name: whatif-ui-designer
description: Designs and generates UI for What-If Studio, an industrial platform built on FastAPI + React 19 + TypeScript + Vite, styled entirely with hand-rolled CSS custom properties (no UI/chart library). Produces pages, panels, tables, and status/metric components consistent with the existing teal-accented, card-based design in frontend/src/theme/theme.css. Use this skill whenever the user asks to design, build, create, redesign, improve, or style any What-If Studio page, tab, panel, or component - including phrasings like "design the X page", "create UI for X", "build a component for X", "make the X look better", "redesign X" - even when the app isn't named explicitly if the conversation context is clearly about its frontend, layout, CSS, or visual polish.
disable-model-invocation: true
---

# What-If Studio UI Designer

You are designing frontend UI for **What-If Studio**, an
industrial process-simulation platform. The goal is UI that reads as one
coherent, restrained, data-dense product - closer to an industrial SCADA/
BI tool than a consumer app - and that fits the stack exactly as it exists
today, not a nicer stack you'd prefer.

## What this stack looks like

- **Frontend**: React 19 + TypeScript + Vite, `react-router-dom`,
  `@tanstack/react-query`, `axios`.
- **No UI or charting library** - no MUI, AntD, Tailwind, shadcn,
  Bootstrap, styled-components, Recharts, Chart.js, or D3. Every chart is
  hand-rolled inline SVG (see `LineChart.tsx`, `ScatterChart.tsx`,
  `MiniHistogram.tsx`, `MiniBoxplot.tsx`). Do not introduce one unless the
  user explicitly asks for a stack migration.
- **No icon library** - no Lucide, no Heroicons, no icon fonts. The app
  uses plain emoji as icon props/content (`"🎯"`, `"🔍"`, `"🟢"/"🟡"/"🔴"`
  for status grading). Match this - suggest an emoji, not an `<svg>` icon
  or a CDN script tag.
- **Styling**: one global stylesheet, `frontend/src/theme/theme.css`,
  using CSS custom properties on `:root`, plus a handful of reusable
  classes (`.card`, `.status-card`, `.callout`, `.pill`, `.badge`,
  `button.chip`, `.metric-value`, `.caption`, `.step-badge`/`.step-heading`,
  `.section-banner`). New components should reuse these classes and
  variables, not invent parallel ones, unless the existing set genuinely
  has no fit.
- **Structure**: `pages/<Feature>/<Feature>Page.tsx` composes React Query
  calls into `api/<domain>.ts` (thin axios wrappers) with shared
  components from `components/`. Cross-page state lives in small
  `localStorage`-backed Contexts in `state/`.

## Before you design: check what already exists

Always open `frontend/src/theme/theme.css` and 1-2 existing components
under `frontend/src/components/` (start with `KpiCard.tsx`,
`StatusCard.tsx`, `SectionBanner.tsx`, `Callout.tsx`, `DataTable.tsx` -
pick whichever are closest to what's being designed) before generating
anything new. Consistency matters more than novelty here.

Specifically reuse:
- **CSS variables** from `theme.css` - `--primary`, `--accent`, `--canvas`,
  `--bg-page`, `--bg-subtle`, `--border`, `--text-main`, `--text-caption`,
  `--text-faint`, `--radius`, and the semantic pairs `--info-bg`/
  `--info-text`, `--success-bg`/`--success-text`, `--warning-bg`/
  `--warning-text`, `--error-bg`/`--error-text`.
- **Existing component classes** - `.card`, `.status-card`, `.callout.*`,
  `.pill.*`, `.badge.*`, `button.chip`/`button.chip.active`,
  `.metric-value`, `.caption`, `.data-table-scroll`/`.scroll-rows-5`
  (fixed-height scrollable tables with a sticky header), `.sticky-col`
  (frozen first column), `.table-compact` (dense spreadsheet-style grids).
- **Existing components** - don't rebuild a KPI tile, status card, tab
  strip, stepper, dropdown, or chart type that already exists in
  `components/`; import and reuse it, or extend its props if it's close
  but not quite there.

If the relevant files aren't available and the request is non-trivial,
ask the user to point you at the closest existing page rather than
inventing a look from scratch.

## The What-If Studio design language

This is what's actually in `theme.css` today - use these values directly,
don't reinvent a palette:

**Palette:**
- Canvas (page background): `#f2f5f8` (`--canvas`)
- Card/surface background: `#ffffff` (`--bg-page`), subtle fill
  `#eaeff4` (`--bg-subtle`)
- Border: `#dbe2e9` (`--border`)
- Text: near-navy `#152230` (`--text-main`), muted `#5c6b7a`
  (`--text-caption`), faint `#8a97a5` (`--text-faint`)
- Primary/accent: teal `#0e7c86` (`--primary`/`--accent`), lighter teal
  `#139aa6` (`--primary-light`), secondary indigo `#4a54c4` (`--secondary`)
- Semantic pairs (background/text): info `#e3f2f2`/`#0e7c86`, success
  `#e6f5eb`/`#2f9e58`, warning `#fbf0dd`/`#c98a1a`, error `#fce9e7`/`#c0392b`
- Section-coded badges already exist for plant sections (`.badge.cgc`,
  `.prc`, `.erc`, `.furnace`, `.quench`, `.cold`) - reuse these for any
  new plant-section tagging rather than inventing new colors.

**Radius:** `--radius` (10px) for cards/status-cards/section-banners, 8px
for buttons/tables, 6-9px for smaller chips/badges/callouts. Pills are
fully rounded (`border-radius: 999px`).

**Shadows:** none, by design (`.card`/`.status-card` explicitly set
`box-shadow: none`). Structure comes from the 1px border + subtle bg-fill
contrast, not elevation. Don't add shadows to new components.

**Typography:** system font stack (already set on `body`), no custom
font import. Headings are weight 700 with slightly negative letter
spacing. Numeric KPI values use `.metric-value` (1.6rem/700). Secondary
text uses `.caption` (0.87rem, `--text-caption`).

**Layout patterns:**
- Card-based composition, generous but not excessive whitespace - this
  is a data-dense industrial tool, not a marketing page. Favor
  information density over the airy fintech look.
- `.section-banner` (dark teal gradient, `--banner-from` -> `--banner-to`)
  introduces a major step/tab, e.g. "🎯 Target Variable Selection" - one
  per page/major section, not per card.
- `.step-heading` + `.step-badge` for numbered wizard-style steps within
  a page (Preprocess, Feature Selection, Train all use this pattern).
- Tables: use `DataTable.tsx` or the raw `<table>` styling in `theme.css`
  (zebra via `tr:hover`, sticky header via `.data-table-scroll`/
  `.scroll-rows-5`, frozen first column via `.sticky-col`, dense grids via
  `.table-compact`) rather than a new table implementation.
- Forms: label above input, existing flat-bordered `select`/`input`
  styling from `theme.css` - don't add custom input chrome.
- Status/grade indicators: emoji (`🟢`/`🟡`/`🔴` for R²-style grading,
  `.pill.draft`/`.active`/`.info`/`.crit` for lifecycle state) rather than
  a new iconography.

## Charts: hand-rolled inline SVG

There's no charting library. For a new chart, look at the closest
existing one first (`LineChart.tsx` for trends, `ScatterChart.tsx` for
actual-vs-predicted, `MiniHistogram.tsx`/`MiniBoxplot.tsx` for compact
distribution views) and extend that pattern - same axis-drawing approach,
same color usage (`--primary` for the main series, semantic colors for
threshold/anomaly bands) - rather than introducing a new charting
approach or library.

## Output structure

When fulfilling a design request, structure your response like this:

### 1. Short UI plan (2-5 bullets)
Name the key sections/components and any notable UX decisions. Keep it
tight - orientation, not a spec document.

### 2. The code
- **Component/page file(s)** - full `.tsx`, following the existing
  `pages/<Feature>/<Feature>Page.tsx` or `components/<Name>.tsx`
  structure. Use real prop names/types, not placeholders, inferring them
  from the relevant `api/<domain>.ts` response shape when the user's
  asking to render real data.
- **CSS additions** (only if `theme.css`'s existing classes genuinely
  don't cover it) - append to `theme.css` using existing variable names;
  scope any new class narrowly and note why nothing existing fit.
- No JS/CSS framework setup, no new dependency - this app doesn't have
  one and isn't getting one for a UI request.

Put each file in its own fenced code block with a path comment
(`// frontend/src/components/Foo.tsx`).

### 3. Integration note (1-3 lines)
Which page/route renders it, what `api/<domain>.ts` call or prop shape it
expects, whether it needs a new entry in `state/` for cross-page state or
a new route in `routes.tsx`.

## What to avoid

- **Any new UI/chart/icon library** - MUI, AntD, Tailwind, Recharts, D3,
  Lucide, or anything similar. This is a deliberate, repeated project
  convention, not an oversight.
- **Inventing new colors** - every color should trace back to a
  `theme.css` variable or an existing semantic pair. If a genuinely new
  semantic meaning is needed, add one variable to `:root` and use it,
  don't hardcode a hex value inline.
- **Shadows/gradients beyond what exists** - the one gradient in the app
  is `.section-banner`; don't add a second visual language.
- **Consumer-app airiness** - this is an industrial monitoring tool used
  by process engineers; favor density (compact tables, tight KPI rows)
  over generous marketing-page whitespace.
- **Mobile-first assumptions** - this app is used on desktop/plant-floor
  displays; horizontal-scroll tables (`.data-table-scroll`) are the
  existing answer to "too many columns," not a responsive stacked layout.

## Handling ambiguity

If a request is under-specified ("design the results tab"), make
reasonable assumptions grounded in what similar existing tabs do, and
state them up front in the UI plan - one line each. Ask only when the
answer genuinely changes the output (e.g. "Is this a new tab in the
existing Tabs strip, or a separate page under a new route?").
