---
description: Commit, push, create PR, merge, and clean up after a What-If Platform feature is complete
allowed-tools: Read, Bash
---

## Step 0 — Check gh CLI is available and authenticated

```bash
gh --version
gh auth status
```

If either fails, stop immediately and say:
"GitHub CLI (`gh`) is not installed or not authenticated. Install it and
run `gh auth login`, or run /ship-feature again once that's done."
Do not fall back to any other merge mechanism.

## Step 1 — Identify current branch

```bash
git branch --show-current
```

Store this as CURRENT_BRANCH. If it's `main`, stop immediately and say:
"You're on main — /ship-feature must be run from a feature branch."

## Step 2 — Generate commit message

Run:
```bash
git diff --staged
git diff
git log main..HEAD --oneline
```
Read `.claude/specs/` to find the spec matching the current feature (by
slug matching the branch name after `feature/`), for context.

Generate a Conventional Commit message:
- feat: new feature
- fix: bug fix
- chore: config or tooling
- docs: documentation only

Rules:
- Lowercase, no period at the end, under 72 characters
- Describes what changed from a user/operator's point of view, not which
  file was touched

Good: "feat: add scenario comparison export to CSV"
Bad: "feat: added export function to whatif_service.py"

## Step 3 — Commit

Review what's about to be staged before running `git add` broadly —
`dashboard.db`, `mlflow.db`, anything under `Results/`/`saved_models/`/
`Data/`, and any `.env`-style file should generally NOT be committed unless
the feature specifically changes tracked fixtures. Stage specific files by
name rather than `git add -A`/`git add .` unless you've checked
`git status` and confirmed everything listed is meant to be committed.

```bash
git add <specific files>
git commit -m "<generated-message>"
```
Report: "Committed — <message>"

## Step 4 — Push to feature branch

```bash
git push -u origin CURRENT_BRANCH
```
Report: "Pushed — CURRENT_BRANCH"

## Step 5 — Create PR via gh CLI

```bash
gh pr create --title "<title>" --base main --head CURRENT_BRANCH --body "<body>"
```

Title: plain English feature name, no conventional-commit prefix.
Example: "Add scenario comparison export"

Body:
```markdown
## What this PR does
<one paragraph from the spec's Overview section, or a summary of the diff
if no spec exists>

## Changes
<bullet list of every file changed with a one-line description each>

## Definition of done
<copy the Definition of done checklist from the spec, mark every item [x]
that's actually been verified manually — this repo has no automated test
suite, so don't claim [x] for anything not actually run>

## How to test
1. Backend: `uvicorn backend.app.main:app --reload --port 8010`
2. Frontend: `cd frontend && npm run dev` (http://localhost:5173)
3. <specific steps from the spec to verify this feature, including which
   case_id/tab/screen to use>
```

Report: "PR created — <PR URL>"

## Step 6 — Merge PR via gh CLI

```bash
gh pr merge CURRENT_BRANCH --squash --delete-branch
```
This merges and deletes the remote branch in one step.

Report: "PR merged to main, remote branch deleted"

## Step 7 — Switch to main and pull

```bash
git checkout main
git pull origin main
```
Report: "Switched to main — up to date"

## Step 8 — Delete local feature branch

```bash
git branch -d CURRENT_BRANCH
```
Use `-d` (not `-D`) so git refuses if the branch has unmerged commits —
if it refuses, stop and report why rather than force-deleting.

Report: "Local branch deleted"

## Final summary

Print:
```
/ship-feature complete
- Committed — <message>
- Pushed — <branch>
- PR created and merged
- Remote branch deleted
- Switched to main
- Local branch deleted
Next: run /create-spec for the next feature
```

## Rules

- Never commit directly to main
- Always use squash merge
- Always delete both remote and local branch after merge
- If `gh` is not installed/authenticated, stop at Step 0 — do not attempt
  any other merge mechanism
- Never proceed to merge if PR creation fails
- Never use `git add -A`/`git add .` without having reviewed `git status`
  first — this repo has local DB files (`dashboard.db`, `mlflow.db`) and
  generated artifacts that generally shouldn't be committed per-feature
