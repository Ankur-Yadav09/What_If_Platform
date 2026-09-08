# Troubleshooting / Runbook

Known, previously-observed failure modes on this platform — what they look like, why they happen,
and what actually fixes them (as opposed to what looks like a fix but only narrows the window).
Not a general FastAPI/React debugging guide — just the gotchas specific to this codebase's design.

---

## `PermissionError` / `WinError 5` (Access Denied) writing `Config_file.xlsx`

**Symptom**: a config-section "Save" (or `/config/save`, `/config/upload`) intermittently fails
with a Windows `PermissionError`/`WinError 5`, even though the file was readable moments before.

**Cause**: `what_if_service.py::_atomic_write_bytes()` writes config via temp-file-then-`os.replace()`
to avoid a concurrent reader seeing a partial write. On Windows, `os.replace()` can fail if the
destination is transiently locked — confirmed on this codebase's dev machine to be **Windows
Defender's real-time on-write scan** of the freshly-written temp file (not OneDrive, not Excel,
though either of those can also hold a lock in principle). This is a real, observed failure, not
hypothetical.

**Mitigation already in place**: `_atomic_write_bytes()` retries `os.replace()` up to 15 times with
backoff capped at 2.4s/attempt (~28s total budget) before giving up and surfacing the error.

**The durable fix** (not just a wider retry window): add a Windows Defender exclusion for this
repo's `Data/`/`Results/` folders — Windows Security → Virus & threat protection → Manage settings
→ Exclusions, or as Administrator: `Add-MpPreference -ExclusionPath "<repo path>"`.

**Related**: `_load_config()`'s read path also opens `Config_file.xlsx` a lot — What-If Setup's
initial load fires `config/status`, `wizard/detected-counts`, `config/model-mapping`, and
`models/status` in parallel, each independently opening the workbook. That many concurrent opens
can collide with an in-flight upload's `os.replace()` and resurface the same class of error. It's
cached read-only (invalidated the instant the file's mtime changes) specifically to reduce this.

If you ever see this on a *different* file than `Config_file.xlsx`, the same root cause (AV/sync
scanning a freshly-written file) almost certainly applies — check whether that write path goes
through `_atomic_write_bytes()` or a raw `open()`/`to_excel()` call.

---

## `pd.ExcelFile` file-handle leaks lock `Config_file.xlsx` persistently

**Symptom**: uploads/replacements of `Config_file.xlsx` fail with a *persistent* (not transient)
`WinError 5`, not clearing after a few seconds.

**Cause**: `pd.ExcelFile(path)` does not reliably release its Windows file handle just because the
object goes out of scope — release depends on Python's cyclic GC running, since `ExcelFile`/openpyxl
hold circular references to each other. `src/whatif/config_io.py::load_all_config()` is called on
*every* What-If Studio config/wizard endpoint (hit constantly by React Query's refetch-on-focus and
wizard actions), so a missing explicit close leaks a handle almost continuously.

**Fix already in place**: `load_all_config()` opens with `with pd.ExcelFile(path) as xl:` to force
an explicit close. If you add a new reader of this (or any other) workbook, use the same `with`
pattern — don't rely on refcounting to close it.

---

## A submitted job never finishes / stays `pending`

**Cause candidates, in order of likelihood**:
1. **Only 2 concurrent job slots.** `job_manager.py`'s `JobManager` wraps a `ThreadPoolExecutor(max_workers=2)`.
   If two long jobs (training, feature selection) are already running, a third submitted job sits
   `pending` until a slot frees up — this is not a bug, it's the configured concurrency.
2. **The backend restarted.** Job state (`JobManager._jobs`) is an **in-memory dict** — nothing is
   persisted. A backend restart silently drops every in-flight/completed job; polling
   `GET /api/jobs/{id}` afterward returns 404 (`"Job '{id}' not found"`), not a resumed job. The
   frontend has to re-submit.
3. **The wrapped function is actually hung** (e.g. a training run stuck in a bad loop) — since
   exceptions are caught and surfaced via `job.error` (see `manager.py::_run`'s `except Exception`),
   a truly hung thread won't show as `error`; it'll just never reach `done`. Check backend process
   CPU/logs directly.

If this ever needs to survive multi-process/multi-worker deployment or backend restarts, the fix is
swapping the in-memory dict for Redis (or similar) behind the same `submit()`/`get()` interface —
already anticipated in `manager.py`'s module docstring, not yet implemented.

---

## `models/train` (dedicated Kalman training) fails or produces nothing

`POST /api/what-if/models/train` runs `Scripts/Model_development_and_static_whatif_testing_updated.py`
as a **subprocess** (`_run_training_subprocess()` in `what_if_service.py`) — this is real production
code despite living under `Scripts/` (CLAUDE.md's one exception to that folder being read-only).

**Where to look on failure**: the job's `result` (via `GET /api/jobs/{id}` once `done`) includes
`returncode`, `stdout_tail`, `stderr_tail` (last 8000 chars each), `pkl_count`, `all_present`, and
`raw_sim_present` — this is the subprocess's own diagnostic output, not a wrapped/summarized error.
Check `stderr_tail` first.

**How case scoping works here**: the script predates case isolation and still resolves paths via
its own `PLANT_NAME` env var (multi-plant support it already had). The backend sets
`PLANT_NAME=<case_id>` for any non-default case (left unset for `"default"`, which keeps the flat
layout). If a non-default case's training reads/writes the wrong folder, check that `PLANT_NAME`
actually reached the subprocess — `_run_training_subprocess()` copies `os.environ` and adds it
explicitly.

**"Training required" but you just trained**: `models/status`'s `training_required` flag mirrors the
Streamlit reference's gate — training is only considered "required" when *neither* the historian
file (`Raw_data_plus_simulated_data.xlsx`) *nor* a full set of model `.pkl` artifacts exist yet. If
training apparently succeeded (`returncode == 0`) but `models/status` still shows blockers, check
`pkl_count`/`all_present` in the job result against `required_kalman_tags()` — likely the workbook's
`Model details` sheet lists a predicted parameter the run didn't actually produce a model for.

---

## `404 Unknown case_id '<x>'` on a request that used to work

**Cause**: every case-scoped router carries `Depends(require_valid_case_id)`
(`backend/app/api/deps.py`), which re-checks `case_id` against the `whatif_cases` SQLite table on
**every request** — not just at case creation. This closes a path-traversal gap (an unvalidated
`case_id` straight from the query string could resolve outside `Data/`/`Results/` via
`os.path.join`), but it also means a case that was deleted, or a `case_id` typo, 404s immediately
rather than silently falling through to `"default"`.

If the frontend is sending a stale case id (e.g. `ActiveCaseContext`'s `localStorage` value
outliving the case's deletion), the fix is on the frontend side — re-sync from
`GET /api/what-if/cases` — not in this dependency.

---

## Uploaded config workbook is silently missing a section after upload

**Cause**: `config_io.py::load_all_config()` matches sheet names *tolerantly* (case/spacing
normalized — `_norm_name()` strips everything but `[a-z0-9]`), but it still requires the sheet to
be recognizable as one of the known field mappings. A sheet named something unrecognized (typo
beyond what normalization tolerates, e.g. a stray extra word) is silently ignored — not an error,
just absent from the resulting `WhatIfConfig`, and that section falls back to an empty DataFrame.

**Debug it** by checking `xl.sheet_names` against `_SHEET_TO_FIELD` / `match_sheet_to_field()` in
`src/whatif/config_io.py` — if a sheet's normalized name doesn't match any of the recognized
patterns (including the special-cased PI/MV-DV-CV fuzzy matches), rename it in the source workbook
rather than expecting the app to guess harder.

**Also check**: `Constraints`' max-value column has two known spellings (`"Max vlaue"` — the
historical misspelling — and `"Max value"`). If a workbook uses a third spelling, `constraints_max_col()`
falls back to the misspelled default and every constraint lookup against the corrected name will
come up empty. Fix by renaming the column to one of the two recognized spellings.

---

## Debug checklist for "the scenario dashboard shows wrong/stale numbers"

1. **Is `case_id` what you think it is?** Every dashboard call is case-scoped; confirm the active
   case pill in the UI matches the case whose config you edited.
2. **Config caching**: `_load_config()`'s read cache invalidates on the workbook's mtime changing —
   if a write happened through a path other than `_atomic_write_bytes()` (shouldn't happen, but
   worth ruling out), the cache could still be serving a pre-write copy.
3. **Model selection vs. Kalman fallback**: per-parameter dispatch order is plugin → Selected Soft
   Sensor experiment (`whatif_model_selection` bridge) → dedicated Kalman filter → baseline (see
   `flow.md` §6). A parameter showing unexpected values after retraining a Soft Sensor model is
   often still pointed at an *older selected* experiment, or has no selection and is silently on
   the Kalman/baseline fallback — check `GET /api/what-if/experiments` for what's actually selected.
4. **Constraints firing unexpectedly**: `bump_linked_to_max`/`abort_if_exceeds` rules apply *around*
   each engine step, not just at the end — a `constraint_hit: true` with a value that "looks fine"
   is often a *linked* parameter's constraint, not the parameter being displayed. Check
   `constraint_message` for which parameter/rule actually fired.
