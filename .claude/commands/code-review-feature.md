---
description: Runs parallel security and quality code review for a specific
  What-If Platform feature. Pass the spec slug as argument
  e.g. /code-review-feature scenario-comparison-export
allowed-tools: Bash(git diff), Bash(git diff --staged), Agent
---

Run the full code review pipeline for the feature specified in $ARGUMENTS.

If no argument is provided, stop immediately and say:
"Please provide a spec slug. Usage: /code-review-feature <spec-slug>
e.g. /code-review-feature scenario-comparison-export"

## Pre-flight Check

Before invoking any subagents, collect the diff:
- Run `git diff` for unstaged changes
- Run `git diff --staged` for staged changes
- Combine both into a single diff

If both are empty, stop immediately and say:
"No changes detected. Implement the feature before running code review."

---

## Step 1: Parallel Review

Invoke both subagents simultaneously with the same context:

**whatif-security-reviewer** receives:
- The combined diff from the pre-flight check
- Spec file for context: `.claude/specs/$ARGUMENTS.md` (if it exists)
- Source directories to reference as needed: `backend/app/`, `src/`,
  `config/settings.py`
- Instruction: Review only the changed code for security vulnerabilities
  (see the agent's own checklist — path/case_id handling, SQL injection,
  deserialization, input validation, secrets). Do not comment on quality
  or style.

**whatif-quality-reviewer** receives:
- The combined diff from the pre-flight check
- Spec file for context: `.claude/specs/$ARGUMENTS.md` (if it exists)
- Source directories to reference as needed: `backend/app/`, `src/`,
  `frontend/src/`, `config/settings.py`
- Instruction: Review only the changed code for architecture-layering
  violations, config discipline, UI-convention adherence, and
  maintainability. Do not comment on security concerns.

Both subagents must run in parallel. Do not wait for one to finish before
starting the other.

If the spec file at `.claude/specs/$ARGUMENTS.md` does not exist, proceed
anyway using only the diff and CLAUDE.md for context, but note in the final
report that no spec was found for this slug.

---

## Step 2: Unified Report

Once both subagents have completed, combine their findings into a single
unified report. De-duplicate overlapping findings — if both agents flagged
the same line for different reasons, merge them into one finding with both
perspectives noted.

Structure the combined report as:
```
Code Review Report — $ARGUMENTS

Security Findings
[whatif-security-reviewer output]

Quality Findings
[whatif-quality-reviewer output]

Combined Action Plan
Ordered checklist of everything that needs to be fixed, prioritized:
[Security findings that are actually exploitable, first]
[Layering violations second]
[Everything else last]

Overall Verdict
APPROVED — ready to commit
APPROVED WITH SUGGESTIONS — can commit, address suggestions in a follow-up
CHANGES REQUESTED — must fix before committing, see action plan above
```

---

## Step 3: Ask for Approval

After presenting the unified report, ask:

"Do you want me to implement the action plan now?"

Wait for explicit user confirmation before making any changes. Do not
touch any files until the user approves.

---

## Rules

- Do NOT edit any files before user approval
- Do NOT start one reviewer before the other — both must run in parallel
- Do NOT skip the pre-flight diff check
- If either subagent fails or returns no output, report it and do not
  present a partial review as complete
