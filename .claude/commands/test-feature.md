---
description: Writes and runs tests for a specific What-If Platform feature.
  Pass the spec slug as argument e.g. /test-feature scenario-comparison-export
allowed-tools: Agent, Bash(git diff), Bash(git diff --staged)
---

Run the full testing pipeline for the feature specified in $ARGUMENTS.

If no argument is provided, stop immediately and say:
"Please provide a spec slug. Usage: /test-feature <spec-slug>
e.g. /test-feature scenario-comparison-export"

If `.claude/specs/$ARGUMENTS.md` does not exist, stop immediately and say:
"Spec file not found at .claude/specs/$ARGUMENTS.md. Please check the spec
slug and try again."

This repo currently has no test suite — no pytest config, no vitest config.
whatif-test-writer bootstraps whichever side(s) it touches the first time
it runs; expect that on this feature's first pass.

---

## Step 0: Determine scope

Read the spec file and run `git diff` + `git diff --staged` to see which
files actually changed. Classify the feature's scope as one of:
- **backend-only** — only files under `backend/app/` or `src/` changed
- **frontend-only** — only files under `frontend/src/` changed
- **both**

Only invoke the writer/runner steps below for the side(s) in scope.

---

## Step 1: Write Tests

Invoke the **whatif-test-writer** subagent (once per side in scope, can run
in parallel if both) with:

- Spec file to base tests on: `.claude/specs/$ARGUMENTS.md`
- The combined diff from Step 0, so it knows exactly which
  routes/services/`src` modules or pages/components/`api` wrappers changed
- Side to cover: backend and/or frontend, per Step 0's scope
- Output location:
  - backend: `tests/backend/test_$ARGUMENTS.py`
  - frontend: colocated `<Component>.test.tsx` next to each changed
    component/page
- Instruction: Write tests based on what the spec says the feature SHOULD
  do. Do NOT derive test logic from reading the implementation line-by-line.
  Cover happy paths, validation errors, case_id isolation, and (frontend)
  loading/error states and user interactions. Bootstrap pytest/vitest
  config first if it's missing for that side.

Wait for whatif-test-writer to fully complete and confirm the test file(s)
have been written before proceeding to Step 2.

---

## Step 2: Run Tests

Once whatif-test-writer has finished, invoke the **whatif-test-runner**
subagent (once per side in scope) with:

- Test file(s) to execute (exactly what was written in Step 1, nothing more)
- Spec file for context: `.claude/specs/$ARGUMENTS.md`
- Source to analyze against when diagnosing failures: the same files
  identified in Step 0
- Run command:
  - backend: `python -m pytest tests/backend/test_$ARGUMENTS.py -v`
  - frontend: `npx vitest run <path>` (from `frontend/`)
- Instruction: Run ONLY the specified test file(s). Do NOT run the full
  suite. Classify each failure as bug / missing feature / test issue /
  environment issue.

---

## Handoff Rules

- Do NOT start Step 2 until Step 1 is fully complete for that side
- Do NOT attempt to fix any code regardless of what the test results show
- Do NOT run any tests beyond the file(s) written in Step 1
- If whatif-test-writer reports it could not write the test file, stop and
  report the reason — do NOT proceed to Step 2 for that side

---

## Final Output

After all subagents complete, produce a combined summary:

### Testing Pipeline Report — $ARGUMENTS

**Scope**
backend / frontend / both (from Step 0)

**Bootstrap changes**
Any test-tooling config created for the first time (pytest added to
requirements.txt, vitest added to frontend/package.json, etc.), or "none".

**Step 1 — Tests Written**
List each test written with a one-line description of which spec
requirement it validates.

**Step 2 — Test Results**
Mirror whatif-test-runner's structured report(s).

**Verdict**
One of:
- Ready for code review — all tests pass
- Needs fixes — list the failing tests and their root causes
