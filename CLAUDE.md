# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SoftSense AI — an industrial AI platform built around one product, **What-If Studio**, on a FastAPI backend: configure a plant's process-flow/tag structure and predictive models, then simulate hypothetical scenarios — override input tags, see predicted KPI/constraint effects, validate against history.

What-If Studio's own Model Config tab embeds a full model-development pipeline (upload process data, preprocess, run consensus feature selection, train a model — Denoising Autoencoder or classic ML — evaluate predictions) to produce the candidate models a scenario run can select from. This used to ship as a separate "Soft Sensor Module" with its own sidebar entry and landing page; it has neither anymore. Its pages (`pages/Upload/`, `Preprocess/`, `FeatureSelection/`, `Train/`, `SoftSensor/ExperimentHistoryPage.tsx`) are reused only as embedded tabs — their old standalone routes (`/upload`, `/preprocess`, `/soft-sensor-overview`, etc.) were dead code and have been removed from `routes.tsx`; `SoftSensor/OverviewPage.tsx` and `Predict/PredictPage.tsx`, which had no other callers, were deleted.

Full detail lives in these docs — **read them, don't re-derive this from source**:
- [`README.md`](./README.md) — setup, run instructions, project structure, feature list.
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — layering (routes→schemas→services→src, frontend page→api→component), the one persistence bridge between What-If Studio and its embedded pipeline, a full request trace.
- [`docs/flow.md`](./docs/flow.md) — What-If Studio screen-by-screen: every tab, every backend call, the engine's per-parameter model-dispatch order (plugin → Selected Soft Sensor experiment → Kalman filter → baseline).
- [`docs/MODEL_CONFIG_METHODS.md`](./docs/MODEL_CONFIG_METHODS.md) — deep, implementation-level reference for Model Definition, AI Feature Discovery, and Build Model: what each method/algorithm computes and why.
- [`docs/API_REFERENCE.md`](./docs/API_REFERENCE.md) — every REST route in one table: method, path, request/response schema, which service it calls.
- [`docs/DATA_SCHEMA.md`](./docs/DATA_SCHEMA.md) — `dashboard.db` tables, the 8-sheet `Config_file.xlsx` workbook, and the on-disk `Data/`/`Results/`/`saved_models/` layout.
- [`docs/CONFIG_REFERENCE.md`](./docs/CONFIG_REFERENCE.md) — every constant/threshold/path in `config/settings.py`, grouped by what it controls.
- [`docs/TROUBLESHOOTING.md`](./docs/TROUBLESHOOTING.md) — known, previously-observed failure modes (Windows file-lock errors, stuck jobs, case-scoping 404s) and their actual fixes.

## Commands

Backend (run from repo root, not `backend/` — paths in `config/settings.py` and `src/whatif/paths.py` are root-relative):

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8010
```

Frontend (separate terminal):

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api -> localhost:8010
npm run build     # tsc -b && vite build -> frontend/dist/
npm run lint       # oxlint
```

There is no test suite (Python or JS) in this repo currently — don't assume `pytest`/`npm test` exist. There is no Python lint config either; match existing style by hand.

## Architecture essentials

**Three layers, one direction of imports:** `frontend/` (React+TS+Vite) → HTTP → `backend/app/` (FastAPI) → plain function calls → `src/` (framework-agnostic core) → SQLite/pickles/Excel.

`src/` must never import FastAPI, React, or Streamlit — it's plain, independently testable Python. All web concerns live in `backend/app/`; all browser concerns in `frontend/src/`.

**Backend pattern for every feature:** `api/routes/<feature>.py` (thin, one service call) → `schemas/<feature>.py` (Pydantic) → `services/<feature>_service.py` (orchestration/business wiring) → `src/...` (actual logic). Long-running work (training, feature selection, What-If's Kalman retraining) goes through `backend/app/jobs/manager.py` (`ThreadPoolExecutor`-backed `job_manager`), polled via `GET /api/jobs/{id}` (frontend's `useJobPolling` hook). Fast operations (predict, What-If scenario compute) respond synchronously.

**Frontend pattern:** `pages/<Feature>/<Feature>Page.tsx` composes React Query calls into `api/<domain>.ts` (thin typed wrappers around `api/client.ts`'s axios instance) with shared hand-rolled components from `components/`. Cross-page state (active dataset/project, What-If's active case/target section) lives in small `localStorage`-backed Contexts in `state/`. **No UI or charting library** — everything is hand-rolled CSS (`theme.css` custom properties) and custom SVG charts; follow this convention for new pages, don't introduce MUI/AntD/Tailwind/a chart lib.

**The one deliberate bridge between What-If Studio and its embedded pipeline:** `dashboard.db`'s `whatif_model_selection(parameter, model_name, selected_at, case_id)` table records which model-development experiment (from `model_registry`/`saved_models/`) is "Selected for What-If Analysis" for a given predicted parameter. `src/whatif/engine.py::predict_and_update_with_soft_sensor_model()` checks it before falling back to a dedicated Kalman filter. Don't add other cross-references between their otherwise-separate persistence — this bridge is intentionally narrow.

**Case isolation:** What-If Studio (and the model-development pipeline's pages reused inside it) support multiple isolated "cases," modeled on the legacy Streamlit app's multi-plant folders. `case_id` defaults to `"default"`, which resolves to the pre-case-isolation flat layout unchanged. Every What-If/Soft-Sensor-adjacent route takes `case_id: str = Query("default")`; the frontend's `ActiveCaseContext` + `api/client.ts` request interceptor stamp `?case_id=...` onto every relevant request automatically, so individual pages/components don't need to know cases exist. See `flow.md` §2/§3a before touching anything case-related.

**What-If's engine dispatch** (`src/whatif/engine.py::whatif_analysis()`): builds a dependency graph from the `Model details` config sheet, topologically sorts it, and for each predicted parameter tries in order: plant-physics plugin (`src/whatif/plants/`) → Selected Soft Sensor experiment → dedicated Kalman filter (`Results/<case_id>/Model/*.pkl`) → baseline value. Generic `Constraints`-sheet rules (`bump_linked_to_max`/`abort_if_exceeds`) apply around each step — there is no hardcoded per-plant logic left in the engine itself. Full detail in `flow.md` §6.

## Things that look wrong but aren't

- `Scripts/` (legacy Streamlit apps, incl. `_updated` versions) is **read-only reference material**, kept in sync with nothing else in the repo, never imported by the backend — do not modify it. **Exception:** `Scripts/Model_development_and_static_whatif_testing_updated.py` is live production code, invoked as a subprocess by `what_if_service.py::_run_training_subprocess()` (case-scoped via a reused `PLANT_NAME` env var) — it does get bug-fixed when needed.
- All paths/thresholds/hyperparameter defaults belong in `config/settings.py` — check there before hardcoding a value, including the `WHATIF_*` path constants.
- Every What-If config section persists immediately on its own "Save" action (each `commit_*` service function reloads the on-disk workbook, swaps in just its own sheet, rewrites all 8 sheets via `_write_all_sheets()`) — there's no separate "commit" step, and a per-section save can't clobber another section's data.
