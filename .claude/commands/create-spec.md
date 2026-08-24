---
description: Create a spec file and feature branch for a new What-If Platform feature
argument-hint: "Feature name e.g. scenario comparison export"
allowed-tools: Read, Write, Glob, Bash(git:*)
---

You are a senior developer spinning up a new feature for What-If Studio.
Always follow the rules in CLAUDE.md.

User input: $ARGUMENTS

## Step 1 — Check working directory is clean

Run `git status` and check for uncommitted, unstaged, or untracked files.
If any exist, stop immediately and tell the user to commit or stash changes
before proceeding. DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments

From $ARGUMENTS extract:

1. `feature_title` — human readable title in Title Case
   - Example: "Scenario Comparison Export"

2. `feature_slug` — git and file safe slug
   - Lowercase, kebab-case, only a-z, 0-9 and -, max 40 characters
   - Example: `scenario-comparison-export`

3. `branch_name` — format: `feature/<feature_slug>`

If you cannot infer these from $ARGUMENTS, ask the user to clarify before
proceeding.

## Step 3 — Check branch name is not taken

Run `git branch` to list existing branches. If `branch_name` is already
taken, append a number: `feature/scenario-comparison-export-01`, etc.

## Step 4 — Switch to main and pull latest

```
git checkout main
git pull origin main
```

## Step 5 — Create and switch to the feature branch

```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase

Read before writing the spec:
- `CLAUDE.md` — architecture and conventions summary
- `README.md`, `docs/ARCHITECTURE.md`, `docs/flow.md` — full detail on
  layering, the persistence bridge, and What-If Studio's screen/engine
  behavior; read `docs/flow.md` if the feature touches anything
  case-related or engine-dispatch-related
- `config/settings.py` — existing path/threshold/hyperparameter constants,
  so the spec doesn't invent a new constant that duplicates one
- Relevant existing files under `backend/app/api/routes/`,
  `backend/app/schemas/`, `backend/app/services/`, `src/`, and
  `frontend/src/pages/` / `frontend/src/api/` for the area this feature
  touches
- All files in `.claude/specs/` — avoid duplicating an existing spec

## Step 7 — Write the spec

Generate a spec document with this exact structure:

---
# Spec: <feature_title>

## Overview
One paragraph: what this feature does, why it's needed, and where it fits
in What-If Studio (a new tab/section, a change to an existing scenario
flow, a Model Config pipeline addition, etc.).

## Depends on
Existing routes/services/pages/tables this feature builds on. State "None"
if it's fully additive.

## Backend changes
For each new or modified route:
- `METHOD /api/...` — description — sync or job-manager-backed
  (`backend/app/jobs/manager.py`) if long-running
- Which `schemas/<feature>.py` Pydantic models are new/changed
- Which `services/<feature>_service.py` functions are new/changed, and
  what `src/...` logic they call
- Whether it needs `case_id: str = Query("default")` and how it uses it

If no backend changes: state "No backend changes".

## Frontend changes
- New/modified pages under `pages/<Feature>/`
- New/modified `api/<domain>.ts` wrappers
- New shared components (must reuse `components/` and `theme.css` — no
  new UI/chart library)
- Any new cross-page state needed in `state/` (Context + localStorage)

If no frontend changes: state "No frontend changes".

## Persistence / data changes
Any new SQLite table or column in `dashboard.db`, new Excel sheet in the
What-If workbook, new pickle/model artifact location. Cross-check against
`src/whatif/engine.py` and the `whatif_model_selection` bridge table if
this touches model selection — don't add a second cross-reference between
What-If Studio and the embedded pipeline; that bridge is intentionally
narrow. If none: state "No persistence changes".

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip or npm packages. If none: state "No new dependencies".

## Rules for implementation
Project-specific constraints Claude must follow. Always include:
- Respect layering: `src/` never imports FastAPI/React; routes stay thin
  and delegate to a service
- Raw parameterized SQL only (no ORM) for any `dashboard.db` access
- All new constants/paths/thresholds go in `config/settings.py`, not
  hardcoded inline
- No new UI/charting library — hand-rolled CSS via `theme.css` custom
  properties, custom SVG for any chart
- Case isolation: rely on the existing `ActiveCaseContext` +
  `api/client.ts` interceptor on the frontend; don't hand-thread `case_id`
  through props/query strings where that's already handled
- Long-running work goes through `job_manager` and is polled via
  `useJobPolling`, not made synchronous
- Each What-If config section's "Save" persists immediately via its own
  `commit_*` service function (reload workbook, swap in its sheet,
  rewrite all 8 sheets) — don't invent a separate commit step

## Definition of done
A specific, testable checklist. Each item must be verifiable by running
the app (`uvicorn backend.app.main:app --reload --port 8010` +
`npm run dev` in `frontend/`) — this repo has no automated test suite yet,
so phrase items as manual verification steps, not "tests pass."
---

## Step 8 — Save the spec

Save to: `.claude/specs/<feature_slug>.md`

## Step 9 — Report to the user

Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<feature_slug>.md
Title:     <feature_title>
```

Then tell the user:
"Review the spec at `.claude/specs/<feature_slug>.md` then enter Plan Mode
with Shift+Tab twice to begin implementation."

Do not print the full spec in chat unless explicitly asked.
