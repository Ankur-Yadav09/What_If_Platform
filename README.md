# SoftSense AI — Soft Sensor + What-If Studio (FastAPI + React)

An end-to-end industrial AI platform with two modules under one React app:

- **Soft Sensor Module** — upload process data, clean it, run intelligent feature selection, train a model (Denoising Autoencoder or a classic ML baseline), and evaluate predictions.
- **What-If Studio** — configure a plant's process-flow/tag structure and predictive models, then simulate hypothetical process scenarios against them: override any input tag, instantly see the predicted effect on a config-derived set of KPIs and compressor power/constraint limits, and validate against historical data. Each predicted parameter can be driven by either a dedicated Kalman filter trained inside What-If Studio itself, or by any Soft Sensor experiment explicitly marked "Selected for What-If Analysis" — see [Key Features](#what-if-studio-details) and [`flow.md`](./flow.md) for the full detail.

The FastAPI backend and React frontend are self-contained. `Scripts/` also contains standalone legacy Streamlit **What-If Analysis** apps (and their generalized `_updated` counterparts) — read-only functional reference material the What-If Studio module was ported from, never imported by the backend, and not required to run this app. The one exception is `Model_development_and_static_whatif_testing_updated.py`, which the backend genuinely invokes as a subprocess to train dedicated Kalman filter models — see [Notes for whoever picks this up](#notes-for-whoever-picks-this-up).

For the exact, screen-by-screen flow of What-If Studio (every tab, every backend call, the model-dispatch order), see **[`flow.md`](./flow.md)**. For the general codebase architecture, see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## Project Structure

```
Soft_Sensor_and_What_If_Platform/
├── backend/                # FastAPI app
│   └── app/
│       ├── main.py         # App entry point, CORS, router registration
│       ├── api/routes/     # One router per feature area (datasets, preprocess, feature_selection, training, predict, overview, jobs, what_if)
│       ├── services/       # Business logic — wraps src/ for the API layer
│       ├── schemas/        # Pydantic request/response models
│       ├── jobs/           # Background job manager (polling-based long-running tasks)
│       └── core/config.py  # CORS origins, re-exports of config.settings
├── frontend/                # React + TypeScript + Vite app
│   └── src/
│       ├── pages/
│       │   ├── Overview/        # Whole-app landing page ('/')
│       │   ├── SoftSensor/       # Soft Sensor module's own overview + ExperimentHistoryPage (also reused inside What-If Studio)
│       │   ├── Upload/, Preprocess/, FeatureSelection/, Train/, Predict/   # Soft Sensor workflow pages
│       │   └── WhatIf/          # What-If Studio: Welcome (OverviewPage.tsx), What-If Setup (WhatIfSetupPage.tsx → SystemConfigTab/ModelConfigTab/WhatIfConfigTab), What-If Analysis (DashboardPage.tsx) + their sub-components
│       ├── components/      # Shared UI components (tables, charts, stepper, etc.) — no UI/chart library, all hand-rolled
│       ├── api/             # Axios client + typed API calls (one file per backend domain, incl. whatIf.ts, overview.ts, cases.ts) — client.ts auto-attaches the active case_id to every What-If/Soft-Sensor request
│       └── state/           # React context for active dataset/project/What-If target section/active case
├── src/                     # Framework-agnostic core logic (imported by the backend, no FastAPI/React/Streamlit imports)
│   ├── data/                # SQLite dataset versioning + preprocessing pipeline + model_registry + whatif_model_selection (case-scoped, see flow.md) + whatif_cases (case registry)
│   ├── feature_selection/   # 12-method consensus feature selection engine
│   ├── models/              # IndustrialDAE (PyTorch) + wrapper interfaces
│   ├── training/            # Training loops (DAE, sklearn, LSTM, Kalman)
│   ├── evaluation/          # RMSE / MAE / R² / MAPE metrics
│   ├── persistence/         # Model save/load (saved_models/)
│   ├── simulation/          # Orphaned generic sweep helper — unrelated to What-If Studio, kept for backward compatibility
│   └── whatif/              # What-If Studio engine: config_io (8-sheet schema), historian, engine (dependency-graph + Kalman/plugin/soft-sensor dispatch), wizard, model_status, kpi (config-derived KPI list), plants/ (physics plugin)
├── Scripts/                 # Standalone legacy Streamlit What-If apps (and their generalized _updated versions) — READ-ONLY reference for src/whatif/, not run by this app, EXCEPT Model_development_and_static_whatif_testing_updated.py, which is the live dedicated-Kalman-training script, actually invoked as a subprocess
├── Data/                    # What-If Studio inputs: Config_file.xlsx (8 sheets), DMC_Screen_tags_data.xlsx, MV_DV_CV taglist.xlsx
├── Results/                 # What-If Studio inputs/outputs: Model/*.pkl (trained Kalman models+scalers), Model_accuracy_summary.csv, historian workbook
├── config/settings.py       # Single source of truth for paths, thresholds, hyperparameter defaults (incl. WHATIF_* paths)
├── docs/                    # Supplementary technical docs
├── sample_data/             # A sample dataset you can upload to try the Soft Sensor module end-to-end
├── flow.md                  # Screen-by-screen, request-by-request walkthrough of the What-If Studio module
└── requirements.txt          # Python dependencies (backend + src, incl. CoolProp/nfoursid for What-If Studio)
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm

---

## 1. Backend setup (FastAPI)

From the root of this folder:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

uvicorn backend.app.main:app --reload --port 8010
```

- On first run, `dashboard.db` (SQLite) and `saved_models/` are created automatically — no manual setup needed for the Soft Sensor module.
- **What-If Studio** needs its input files already in place: `Data/Config_file.xlsx`, `Data/DMC_Screen_tags_data.xlsx`, `Results/Model/*.pkl` (trained Kalman models + scalers), and `Results/Raw_data_plus_simulated_data.xlsx` (historian). These ship with this repo already populated; retraining or reconfiguring them is fully wired into the UI (Model Config's Build Model / Advanced sections) — see [What-If Studio Details](#what-if-studio-details) below and [`flow.md`](./flow.md).
- The API is served at `http://localhost:8010`, with routes under `/api/*` (e.g. `http://localhost:8010/api/health`, `/api/what-if/*`).
- **Run this from the repo root**, not from inside `backend/` — `config.settings` and `src/whatif/paths.py` use paths relative to the repo root.

## 2. Frontend setup (React + Vite)

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

- Opens at `http://localhost:5173`.
- The dev server proxies `/api` requests to `http://localhost:8010` (see `frontend/vite.config.ts`) — make sure the backend is running first.
- The backend's CORS allow-list only includes `http://localhost:5173` (see `backend/app/core/config.py`). If you run the frontend on a different port, add it there.

## 3. Try it out

**Soft Sensor Module:**
1. Open `http://localhost:5173`.
2. Go to **Soft Sensor Module → Connect Process Data** → **Upload New Dataset** and upload `sample_data/Data_DAE.xlsx` (or your own `.xlsx`/`.csv`).
3. Walk through **Preprocessing** → **Feature Selection** → **Train Model** → **Predict** in order — the sidebar/stepper follows this flow.

**What-If Studio:**
1. Go to **What-If Studio → Welcome** — Quick Actions (**+ New Case** creates a blank, isolated case; **⏩ Switch / Resume Case** lists every existing case and reopens one), configuration-readiness tiles for whichever case is active, and Resources (User Guide/FAQ/sample config download). A "Case: `<name>` · Switch" pill in the sidebar footer keeps the active case visible and switchable from any page.
2. Go to **What-If Setup**, which opens on **System Config** (Process Flow Order → PI Tag Mapping → Input Tag Configuration); saving each section auto-advances to the next.
3. Switch to **Model Config**: its **Model Development** tab is a 5-phase, freely-revisitable workflow (Connect Data → Data Health → Model Definition → AI Feature Discovery → Build Model, reusing the Soft Sensor pages verbatim) for producing candidate models; its **Experimentation & Model Selection** tab lists every experiment grouped by Predicted Parameter — mark one "Selected for What-If Analysis" per parameter (parameters with none fall back to a dedicated Kalman filter, trainable from the "Advanced" section there).
4. Optionally fill in **What-If Config** (Constraints, User Inputs, Results Layout — all optional).
5. Go to **What-If Analysis**: pick a Target Section, tag source, and historical timestamp, optionally override input tags, then **Compute What-If Scenario** to see KPI deltas, the actual-vs-estimated table, and (optional) historical validation filters.

See [`flow.md`](./flow.md) for the exact, detailed version of this walkthrough.

## Production build (frontend)

```bash
cd frontend
npm run build
```

Outputs static files to `frontend/dist/`, which can be served by any static file host (or behind the FastAPI app / a reverse proxy) — point it at the same backend API.

---

## Key Features

### Soft Sensor Module

- **Dataset versioning** — every upload is persisted (SQLite + Parquet); switch between historical versions at any time.
- **12-method consensus feature selection** — correlation, F-test, mutual information, RF/XGBoost/LightGBM importance, Lasso/Elastic Net, RFE/SFS/SBS, PCA loadings — with a confidence-scored recommendation (Highly Recommended / Recommended / Consider / Weak) and full per-feature reasoning.
- **Model training** — Denoising Autoencoder (PyTorch) plus Random Forest, XGBoost, LightGBM, LSTM, and Kalman Filter baselines, with auto-train mode and live loss curves.
- **Prediction & evaluation** — RMSE / MAE / R² / MAPE per target, actual-vs-predicted charts, residual analysis.

### What-If Studio Details

- **Config-driven dependency-graph engine** — the prediction order comes from a dependency graph built off the `Model details` sheet (topologically sorted), not a hardcoded sequence; generic `Constraints`-sheet rules (`bump_linked_to_max` / `abort_if_exceeds`) replace what used to be hardcoded per-plant logic.
- **Section scoping** — a Target Section (e.g. "PRC") scopes a run to that section and everything upstream of it in the Process Flow Order, hiding downstream parameters/tags throughout the UI.
- **Plant Configuration Wizard** — answer a few plant line-up questions (CGC/PRC/ERC stage counts, furnace count) and the PI tag mapping is auto-generated and filtered from the master tag dictionary.
- **Model Development + Experimentation & Model Selection** — train candidate models via the reused Soft Sensor pipeline (any of DAE/Random Forest/XGBoost/LightGBM/LSTM/Kalman Filter — Kalman Filter no longer requires a Sequential Split project, though a Random/Stratified Split is a real accuracy tradeoff for it), compare every experiment for a Predicted Parameter side-by-side, mark one "Selected for What-If Analysis" per parameter, and permanently delete any unwanted experiment (🗑️ Delete — removes its saved files, registry row, and any What-If selection pointing at it). `src/whatif/engine.py::predict_and_update_with_soft_sensor_model()` uses the selected one automatically during a scenario run; a parameter with no selection falls back to a dedicated Kalman filter trained from Model Config's "Advanced" section (`Scripts/Model_development_and_static_whatif_testing_updated.py`, run as a background job, case-aware via a reused `PLANT_NAME` env var).
- **Scenario simulation** — override any input tag within its safe operating range and run the full graph (Kalman filter / Soft Sensor model / plant-physics plugin, whichever applies per parameter) for a single historical snapshot in one call.
- **KPI comparison** — a config-derived set of key performance indicators (`src/whatif/kpi.py::derive_kpi_tags()` — every predicted + constrained parameter, plus any the plant plugin declares) shown actual-vs-estimated, plus a full parameter comparison table with change highlighting.
- **Constraint awareness** — a hard operating constraint (e.g. `CGC_5TH_STG_DISCH_PRES`) short-circuits the simulation with a clear message if tripped, driven entirely by the `Constraints` sheet.
- **Historical validation** — filter the historian by the same config-derived tag set to cross-check a scenario against similar past operating snapshots, and export CSV.
- **Case isolation** — every case gets its own config workbook, dedicated Kalman models, and Soft Sensor experiment selections, modeled on the legacy Streamlit app's multi-plant folder structure; switch cases from the Welcome page or the sidebar's case pill without losing any other case's setup.
- Business logic lives in `src/whatif/` — a from-scratch, Streamlit-free port of the reference Streamlit scripts' generalized pipeline (see `flow.md` and each module's docstrings for what changed and why). Config changes (Process Flow Order, PI Tag Mapping, Model Mapping, etc.) persist to the active case's `Config_file.xlsx` immediately on each section's own Save action — there's no separate "commit" step required.

## Notes for whoever picks this up

- `src/` has no FastAPI, React, or Streamlit imports — it's plain Python and can be tested/extended independently of any UI layer. This includes `src/whatif/`.
- All constants (paths, thresholds, hyperparameter defaults) live in `config/settings.py` — check there before hardcoding anything, including the `WHATIF_*` path constants.
- Long-running operations (feature selection, training, What-If's own Kalman-model retraining) run as background jobs polled via `/api/jobs/{id}` — see `backend/app/jobs/manager.py` and the frontend's `useJobPolling` hook. What-If Studio's config/dashboard endpoints are otherwise synchronous (a scenario run is fast enough not to need this).
- `src/simulation/what_if.py` is an older, unrelated generic sweep helper — it predates and is not used by What-If Studio; don't confuse the two when navigating the codebase.
- `Scripts/` (the legacy Streamlit What-If apps, including the `_updated` versions) is read-only reference material and must not be modified — it stays in sync with nothing else in this repo and is kept only so `src/whatif/` can be checked against it. **The one exception**: `Model_development_and_static_whatif_testing_updated.py` is not reference material — it's the actual dedicated Kalman-training implementation, invoked as a subprocess by `what_if_service.py::_run_training_subprocess()` (`PLANT_NAME=<case_id>` env var makes it case-aware, reusing its own pre-existing multi-plant folder resolution). It gets bug-fixed like any other production file when needed.
- `dashboard.db`'s `whatif_model_selection` table is the **only** deliberate bridge between the Soft Sensor module's persistence (`saved_models/`, `model_registry`) and What-If Studio's (`Config_file.xlsx`, `Results/Model/*.pkl`) — see `ARCHITECTURE.md` §4 and `flow.md` for exactly how and why. Don't casually add more cross-references between the two; that bridge was added narrowly and on purpose.
- Every What-If config section (Process Flow Order, PI Tag Mapping, Model Mapping, MV/DV/CV Tag List, Constraints, User Inputs, Column Order, Target Section) persists to the active case's `Config_file.xlsx` the moment its own "Save" action is used — each `commit_*` service function reloads the current on-disk config, swaps in just its own sheet, and rewrites the whole workbook via a shared `_write_all_sheets()` helper, so a per-section save can never clobber another section's data.
- **Cases give real per-case isolation**, modeled on the legacy Streamlit app's multi-plant folder structure: each case gets its own `Data/<case_id>/Config_file.xlsx`, `Results/<case_id>/Model/*.pkl`, and `saved_models/<case_id>/` — including the Soft Sensor `model_registry`/`whatif_model_selection` bridge, so Experiment History and "Selected for What-If Analysis" are also case-scoped. `case_id` defaults to `"default"`, which resolves to the original flat file layout unchanged — nothing that existed before case isolation shipped needed to move. Isolation goes further than just the model layer: uploaded datasets (`dashboard.db`'s `datasets` table, `UNIQUE(case_id, name)`) and Feature Selection's `artifacts/<project_id>/` projects are case-scoped too, so a brand-new case's Connect Data/Data Health/Feature Discovery genuinely starts blank rather than seeing every other case's uploads. See `flow.md` §2/§3a for the full mechanism.
