# What-If Studio — Exact Module Flow

This is a screen-by-screen, request-by-request walkthrough of the What-If Studio module: every page, every backend call it makes, and exactly how a scenario gets computed. For the general codebase layering (routes→schemas→services→src, frontend page→api→component), see [`ARCHITECTURE.md`](./ARCHITECTURE.md). For setup/run instructions, see [`README.md`](./README.md).

---

## 1. Navigation map

```
Sidebar → "What-If Studio" group
├── Welcome                /what-if/overview     → WhatIfOverviewPage (OverviewPage.tsx)
├── What-If Setup          /what-if/case-setup    → WhatIfSetupPage.tsx
│   ├── System Config      (tab 0, default)       → SystemConfigTab.tsx
│   ├── Model Config       (tab 1)                → ModelConfigTab.tsx
│   └── What-If Config     (tab 2)                → WhatIfConfigTab.tsx
└── What-If Analysis       /what-if/dashboard     → DashboardPage.tsx
```

`What-If Setup` always opens on **System Config**, regardless of how you navigated there (no "resume where I left off" auto-jump — that was removed deliberately, see §8).

---

## 2. Persistence model

What-If Studio has **no server-side session**, but it does have real per-**case** isolation (a "case" is an isolated scenario setup for the one YANPET_OLF1 plant — not a different plant). Every screen reads from and writes to whichever case is currently active; switching cases changes what every screen shows.

| What | Where | Written by | Case-scoped? |
|---|---|---|---|
| Case registry | `dashboard.db`'s `whatif_cases(case_id TEXT PRIMARY KEY, name, created_at, last_opened_at)` | `POST /api/what-if/cases` (create), `POST /api/what-if/cases/{id}/open` (touch `last_opened_at`) | — (this *is* the case list) |
| Plant config (8 sheets, see below) | `Data/<case_id>/Config_file.xlsx` (flat `Data/Config_file.xlsx` for the `"default"` case) | Every section's own "Save" action (§7), the bulk "Save Configuration to Server" button, or workbook upload | ✅ |
| Training/historian workbook | `Data/<case_id>/DMC_Screen_tags_data.xlsx` | "Advanced: train dedicated Kalman filter models" upload | ✅ |
| Dedicated Kalman models | `Results/<case_id>/Model/kalman_filter_model_{parameter}.pkl` + matching scalers | The training subprocess (`Scripts/Model_development_and_static_whatif_testing_updated.py`), run as a background job | ✅ |
| Kalman training accuracy report | `Results/<case_id>/Model/Model_accuracy_summary.csv` | Same training subprocess | ✅ |
| Soft Sensor experiments (any algorithm) | `saved_models/<case_id>/<model_name>/` + `dashboard.db`'s `model_registry` table | The Soft Sensor "Build Model" page (reused inside Model Development) | ✅ |
| **The one bridge**: which experiment is "Selected for What-If Analysis" per parameter | `dashboard.db`'s `whatif_model_selection(parameter, model_name, selected_at, case_id)` | Experimentation & Model Selection's "Use for What-If Analysis" action | ✅ |
| Uploaded datasets, preprocessing projects (`artifacts/<project_id>/`) | `dashboard.db`'s `datasets` table (`UNIQUE(case_id, name)`), `artifacts/<case_id>/<project_id>/` | Soft Sensor "Connect Data" / Feature Selection's "Final Apply" | ✅ |

`"default"` is a real `case_id`, not a placeholder — every path function (`src/whatif/paths.py`) and case-scoped store (`src/persistence/model_store.py`) resolves it to the original flat layout (`Data/Config_file.xlsx`, `Results/Model/`, `saved_models/<model_name>/`) with zero migration, so everything that existed before case isolation shipped kept working unchanged as "Default Case." See **§3a** for exactly how the active case is chosen and threaded through every request.

**The training subprocess is case-aware too, by reusing existing script logic, not by rewriting it.** `Scripts/Model_development_and_static_whatif_testing_updated.py` already supported a `PLANT_NAME` environment variable (originally for multi-plant deployments: prefer `Data/<PLANT_NAME>/` / `Results/<PLANT_NAME>/`, else fall back to the flat layout). `_run_training_subprocess()` (`what_if_service.py`) sets `PLANT_NAME=<case_id>` for any non-default case, so training reads/writes that case's own folders with no script changes at all. The script reads exactly one config file — `Config_file.xlsx`, the same file What-If Setup's UI reads/writes — there is no separate "just-uploaded config snapshot" file to keep in sync.

**`Config_file.xlsx`'s 8 sheets** (`src/whatif/config_io.py`):

| Sheet | Frontend editor | Purpose |
|---|---|---|
| `PI_generalised_Name` | `PiTagMappingEditor.tsx` | Master PI tag dictionary: raw tag → readable name → Section |
| `Model details` | `ModelMappingEditor.tsx` | Each Predicted Parameter's Section + up to 8 Input Parameters |
| `Section Order` | `SectionOrderEditor.tsx` | Plant's process-flow order (e.g. Furnace→Quench→CGC→PRC→ERC→Cold) |
| `MV_DV_CV_taglist` | `MvDvCvTagListEditor.tsx` | Optional prioritized input-tag list (Manipulated/Disturbance/Controlled variables) |
| `Constraints` | `ConstraintsEditor.tsx` | Generic bump/abort rules (`Linked Parameter`/`Action`) |
| `user inputs` | `UserInputsEditor.tsx` | Tags exposed as Simulation Overrides, with default value + allowed range |
| `display_column_order` | `ColumnOrderEditor.tsx` | Preferred column order for the results table/CSV export |
| `Target Section` | (a single-cell sheet) | The currently active Target Section (see §6) |

---

## 3. Welcome (`/what-if/overview`, `OverviewPage.tsx`)

- **Quick Actions**:
  - **+ New Case** — reveals a name field; submitting calls `createCase(name)` → `POST /api/what-if/cases` (server sanitizes the name to a folder-safe `case_id`, `os.makedirs()`s blank `Data/<case_id>/` + `Results/<case_id>/Model/` folders — no files copied/templated), sets it active, invalidates every case-scoped query (§3a), and navigates to What-If Setup showing a genuinely blank config.
  - **⏩ Switch / Resume Case** — reveals a picker (`GET /api/what-if/cases`, most-recently-opened first). Selecting one calls `openCase(caseId)` → `POST /api/what-if/cases/{id}/open` (bumps `last_opened_at`), sets it active, invalidates the same queries, and navigates to What-If Setup.
- **Current case** line + **Current Case** card: shows the active case's name and readiness; its button navigates straight to `/what-if/dashboard` if fully ready, otherwise to `/what-if/case-setup` — no case switch, just a shortcut within the already-active case.
- **Configuration Status** tiles: Process Flow Order, PI Tag Mapping, Model Mapping, Trained Models — each backed by `GET /api/what-if/config/status` / `GET /api/what-if/models/status`, both automatically scoped to the active case (§3a).
- **Resources**: User Guide and FAQ (in-page, auto-scrolls into view when opened), and "Sample Configuration" (downloads the current case's 8-sheet workbook via `POST /api/what-if/config/export`).
- A "📁 `<case name>` · Switch" pill in the sidebar footer (`Sidebar.tsx`) is visible on every page, so switching cases doesn't require returning to Welcome.

## 3a. How the active case gets threaded through every request

There is exactly one thing tracked app-wide: *which case is active*. Everything else in §2's table is derived from it.

- **Backend**: every What-If route/service function, plus the Soft-Sensor `overview`/`training`/`predict`/`datasets`/`preprocess`/`feature-selection`/`projects` routes that touch `model_registry`/`saved_models`/`whatif_model_selection`/`datasets`/`artifacts/`, takes a `case_id: str = Query("default")` parameter, threaded straight through to `src/whatif/paths.py`, `src/persistence/model_store.py`, and `src/data/database.py`. `src/whatif/engine.py`'s Soft-Sensor bridge (`predict_and_update_with_soft_sensor_model()`) and `src/whatif/model_status.py::required_kalman_tags()` are scoped the same way, so a scenario run in one case can never read another case's models or experiment selections.
- **Frontend**: `frontend/src/state/ActiveCaseContext.tsx` holds `activeCaseId` (persisted in `localStorage`), provided at the app root in `main.tsx` (not nested under What-If Studio — the Soft Sensor pages reused inside it are case-scoped too). A request interceptor in `frontend/src/api/client.ts` reads that `localStorage` key directly (interceptors run outside React) and stamps `?case_id=...` onto every request whose URL starts with `/what-if/`, `/overview`, `/training/`, `/predict/`, `/datasets`, `/preprocess`, `/projects`, or `/feature-selection` — so no individual page or `api/*.ts` wrapper function needs to know a case system exists at all. `ActiveDatasetContext.tsx`/`ActiveProjectContext.tsx` namespace their own `localStorage` key by case too (default case keeps the original bare key), so the "currently connected dataset"/"currently active project" pointers are also genuinely per-case, not just the underlying data.
- **Case CRUD**: `frontend/src/api/cases.ts` (`listCases`/`createCase`/`openCase`) → `backend/app/services/whatif_case_service.py` → `src/data/database.py`'s `whatif_cases` table functions (`sanitize_case_id`, `create_case`, `list_cases`, `get_case`, `touch_case_opened`).

---

## 4. What-If Setup (`/what-if/case-setup`, `WhatIfSetupPage.tsx`)

Three top-level tabs, each with its own ✓ checkmark computed from a readiness signal (not tied to whether the tab is "optional" — see the table below):

| Tab | Checkmark condition |
|---|---|
| System Config | Process Flow Order has ≥2 distinct sections **and** PI Tag Mapping is present |
| Model Config | At least one Predicted Parameter is mapped **and** every parameter has a model (Kalman or Selected experiment) |
| What-If Config | At least one of Constraints / User Inputs / Results Layout has data (all three are optional, so this is an OR, not an AND) |

Below the tabs: **"💾 Save Configuration to Server"** (writes the entire in-memory 8-sheet state at once — `POST /api/what-if/config/save`) and **"📥 Download Current Configuration"** (client-side export, same 8 sheets, as `Config_file.xlsx`).

### 4a. System Config (`SystemConfigTab.tsx`) — 3 sub-tabs

1. **Process Flow Order** — `SectionOrderEditor.tsx` (`GET/PUT /api/what-if/config/section-order`) + `TargetSectionSelector.tsx` beneath it. Saving auto-advances to PI Tag Mapping.
2. **PI Tag Mapping** — an optional "🧙 Generate from plant line-up" wizard (`PlantConfigWizard.tsx` → `POST /api/what-if/wizard/generate-mapping`, using detected stage counts from `GET /api/what-if/wizard/detected-counts`) feeding a preview grid, plus the always-present `PiTagMappingEditor.tsx` (`GET/PUT /api/what-if/config/pi-mapping`, normalized via `src/whatif/wizard.py::normalize_pi_df`). Saving auto-advances to Input Tag Configuration.
3. **Input Tag Configuration (MV/DV/CV)** — `MvDvCvTagListEditor.tsx` (`GET/PUT /api/what-if/config/mv-dv-cv-taglist`). Saving here (the last sub-tab) advances the **outer** tab strip to Model Config.

Every row-scoped editor (PI Tag Mapping, MV/DV/CV, Model Mapping) hides rows outside the active Target Section's upstream scope — except a row you're actively editing right now, which always stays visible even if its new Section value falls outside scope (`useTouchedRowIndices.ts`), so a row never appears to vanish mid-edit.

### 4b. Model Config (`ModelConfigTab.tsx`) — 2 tabs

**Model Development** — a single clickable stepper (`ModelDevelopmentStepper.tsx`, not a second tab strip) drives 5 phases, freely revisitable in any order:

1. **Connect Data** — reuses `UploadPage.tsx` verbatim (Soft Sensor's own page, `hideStepper` suppresses its standalone stepper here).
2. **Data Health** — reuses `PreprocessPage.tsx`, plus a What-If-specific Correlation Matrix section (`CorrelationMatrixView.tsx` → `GET /api/what-if/config/correlation-matrix`, Pearson correlation over the training workbook).
3. **Model Definition** — `ModelMappingEditor.tsx` (`GET/PUT /api/what-if/config/model-mapping`): maps each Predicted Parameter to a Section and its input tags. Each row's 8 input dropdowns are scoped to *that row's own* chosen Section (`modelInputOptionsForSection()` in `caseSetupHelpers.ts`) — a row with no Section gets the complete unfiltered tag list. Starts collapsed to just "In 1"; "+ Add Input" reveals more, up to 8, without hiding columns a workbook already has data in.
4. **AI Feature Discovery** — reuses `FeatureSelectionPage.tsx` verbatim. Its in-progress state (target/candidate columns, pathway, method selections, the running/last job id) is saved to `localStorage` keyed by case+dataset, restored synchronously on mount (not via a `useEffect`, to avoid a React Strict Mode double-invoke race that would otherwise clobber the restore with stale defaults) — so switching to Build Model and back no longer resets it to "select Y feature."
5. **Build Model** — reuses `TrainPage.tsx` verbatim; finishing jumps to the Experimentation & Model Selection tab. Kalman Filter training is no longer blocked on the project's split method — it originally required a Sequential Split project (state-space identification assumes consecutive time steps), but now also runs on a Random/Stratified Split project on request; that's a real accuracy tradeoff the user is opting into, not a bug.

**Experimentation & Model Selection** — reuses `ExperimentHistoryPage.tsx` (Soft Sensor's own page) as the model-selection surface:
- One flat table (not one per parameter) with a "Group by Predicted Parameter (Y)" filter dropdown; a multi-output model contributes one row per parameter it predicts.
- Columns: Experiment ID, Algorithm, X Features (expandable chip list, not a clipped ellipsis), Train/Test R²/RMSE/MAE, Trained At, a "Use for What-If Analysis" action, and a **🗑️ Delete** action.
- Clicking "Use for What-If Analysis" calls `POST /api/overview/select-model` (`{parameter, model_name}`) — validated server-side that the model actually predicts that parameter, then upserted into `whatif_model_selection` (primary-keyed by `parameter`, so selecting a new experiment for the same parameter automatically replaces the old one). The ✓ "Selected for What-If Analysis" pill is clickable to `POST /api/overview/clear-selection`.
- Clicking 🗑️ Delete calls `DELETE /api/overview/models/{model_name}` after a confirmation that names how many parameters it's used for and whether it's currently selected — the backend removes its `saved_models/` folder, its `model_registry` row, and any `whatif_model_selection` row pointing at it, so nothing is left dangling.
- Below that, a collapsed **"Advanced: train dedicated Kalman filter models"** section: `TrainingDataUpload.tsx` (`POST /api/what-if/training-data/upload`) + `ModelStatusPanel.tsx` (`GET /api/what-if/models/status`, gated "Train" button → `POST /api/what-if/models/train`, a background job running `Scripts/Model_development_and_static_whatif_testing_updated.py`), which also surfaces `AccuracySummaryPanel.tsx` (`GET /api/what-if/models/accuracy-summary`, reading `Model_accuracy_summary.csv`) once training has run. This whole section is the fallback path for any parameter with no Selected experiment.

### 4c. What-If Config (`WhatIfConfigTab.tsx`) — 3 sub-tabs, all optional

1. **Constraints** — `ConstraintsEditor.tsx` (`GET/PUT /api/what-if/config/constraints`). Saving advances to User Inputs.
2. **User Inputs** — `UserInputsEditor.tsx` (`GET/PUT /api/what-if/config/user-inputs`). Saving advances to Results Layout.
3. **Results Layout** — `ColumnOrderEditor.tsx` (`GET/PUT /api/what-if/config/column-order`).

---

## 5. What-If Analysis (`/what-if/dashboard`, `DashboardPage.tsx`)

A single flowing page (deliberately not tabbed), gated behind `gateReady` (PI Tag Mapping + Model Mapping present, and every parameter has a model — Kalman or Selected experiment). In order:

1. **🎯 Target Section** (`TargetSectionSelector.tsx`) — re-pickable here without redoing setup; scopes everything below to that section + upstream.
2. **🏷️ Tag Source** (`TagSourcePanel.tsx`) — resolves via `POST /api/what-if/dashboard/tag-options`: `config` source (the `user inputs` sheet's tags, used as-is) or `wizard`/`historian` source (a `MultiSelectDropdown` to manually pick tags to override).
3. **🕐 Timestamp & Baseline** — `TimestampSelector.tsx` (`GET /api/what-if/dashboard/dates` → `GET /api/what-if/dashboard/timestamps`, defaults to the most recent) + a collapsed `BaselineValuesPanel.tsx` (`GET /api/what-if/dashboard/baseline`, fetched only when expanded).
4. **🔧 Simulation Overrides** (`SimulationOverridesPanel.tsx`) — one numeric input per active tag, validated against its boundary range (config sheet limits, or historical min/max fallback); shows an active-count badge and a "↺ Reset All" button. An override that fails validation is silently dropped (kept at baseline), never sent.
5. **🚀 Compute What-If Scenario** — `runScenario()` → `POST /api/what-if/dashboard/compute` (see §6 for what happens server-side). On success, the page auto-scrolls to the results.
6. **Results** (only after a successful compute):
   - A warning `Callout` if a hard constraint aborted the run.
   - **📊 Key Performance Indicators** (`KpiCardsRow.tsx`) — one card per KPI tag (from `derive_kpi_tags()`, see §6), actual vs. estimated with a colored delta.
   - **📈 Actual vs Estimated Scenario Output** (`ActualVsEstimatedTable.tsx`) — every parameter, with CSV export.
   - **🔍 Validation Filters** (`ValidationFiltersPanel.tsx`, collapsed by default) — `POST /api/what-if/dashboard/validation-filter` to cross-check against similar historical snapshots by min/max range per tag, with a combined CSV export (`POST /api/what-if/dashboard/export-csv`).

---

## 6. The engine's per-parameter dispatch (`src/whatif/engine.py::whatif_analysis()`)

This is what actually runs on `POST /api/what-if/dashboard/compute`, called from `what_if_service.run_scenario()`:

1. Load the plant physics plugin (`src/whatif/plants/yanpet_olf1_formulas.py`, auto-imported unless one is passed in) — declares `OWNED_PARAMETERS`, `SKIP_PARAMETERS`, `HOOKS`, `SIMULATION`/`BULK_SIMULATION`, `KPI_PARAMETERS`.
2. Resolve the active scope: `filter_model_details_by_section()` restricts `Model details` rows to the Target Section + everything upstream (§4a's Section Order sheet).
3. Build a dependency graph from the scoped `Model details` (`Predicted parameter` → its `Input parameter_*` columns) and topologically sort it (`build_dependency_graph`, `topological_execution_order` — cycle-tolerant).
4. Apply every user override up front to every historian column it names (not just declared "Input parameter" columns — physics hooks often read raw tags directly).
5. Walk the execution order. For each parameter `y_col`, in order:
   - Skip it if the plugin marks it `SKIP_PARAMETERS`.
   - Apply any generic `bump_linked_to_max` constraint + user overrides on its raw inputs (`apply_leaf_overrides_and_constraints`).
   - **If it's plugin-owned or a "First principle" (non-data-model) parameter** → run the plugin's `SIMULATION`/`BULK_SIMULATION` function for it, or leave it at baseline if none is registered.
   - **Otherwise**, try in order:
     1. `predict_and_update_with_soft_sensor_model(y_col, row, case_id)` — looks up `whatif_model_selection` **scoped to the active case** for `y_col`; if a Soft Sensor experiment is selected, loads it from `saved_models/<case_id>/` (`src/persistence/model_store.py::load_model_from_disk`), validates its `x_cols` are all present in the row, scales/predicts/inverse-scales, writes the result. Raises `LookupError` if no selection exists (for this case) or a required column is missing.
     2. On `LookupError` → `predict_and_update_with_kalman(y_col, row, ...)` — loads `Results/<case_id>/Model/kalman_filter_model_{y_col}.pkl` + its two scalers, steps the (already-fitted) Kalman filter one more time with no measurement, writes the inverse-scaled result. Raises `FileNotFoundError` if the artifacts don't exist.
     3. On `FileNotFoundError` → keep the baseline value, logged (never raised to the caller).
   - Apply any user override on the parameter's own value (this wins over whatever was just predicted).
   - Check `abort_if_exceeds` constraints — if tripped, the whole run stops here, the parameter's value becomes the constraint's `Remark` message, and `constraint_hit`/`constraint_message` are set on the response.
   - Fire any plugin `HOOKS["after:<param>"]` registered for this parameter.
6. After the loop, a safety-net pass fires any hook whose trigger parameter never actually appeared in the execution order (e.g. misspelled in `Model details`), so its outputs aren't silently frozen at baseline.
7. KPIs are derived fresh every call via `src/whatif/kpi.py::derive_kpi_tags()` — the order-preserving union of every Predicted Parameter, every Constraints-sheet parameter, and the plugin's `KPI_PARAMETERS`, with `KPI_REPLACEMENTS` substitution applied last (no hardcoded KPI tag list) — then reordered by `kpi.apply_preferred_order()` against the same "Results Layout" `display_column_order` sheet used for the main results table, so a KPI you've put first there (e.g. `DMCTF_feed`) renders first in the KPI cards too, not just in the parameter table.

`src/whatif/model_status.py::required_kalman_tags(model_details_df, case_id)` mirrors step 5's dispatch for the "is everything ready" gate: a parameter is only required to have Kalman `.pkl` artifacts if it has **no** `whatif_model_selection` entry for the active case and isn't a non-data-model/simulation parameter.

---

## 7. Config persistence write path

Every `commit_*` service function in `backend/app/services/what_if_service.py` (Section Order, PI Mapping, Model Mapping, MV/DV/CV, Constraints, User Inputs, Column Order, Target Section) does the same thing on save:

1. Load the **current** on-disk config (`_load_config()`, mtime-cached).
2. Snapshot all 8 sheets' current rows via `_cfg_rows(cfg)` (the same shape each `get_*` endpoint already returns).
3. Replace **only** the one sheet being saved with the new rows.
4. Write all 8 sheets back to `Config_file.xlsx` in one atomic call (`_write_all_sheets()`, shared with the bulk `save_config()` endpoint).

This means every individual "Save" button persists immediately and independently — no separate "commit" step is needed, and a per-section save can never clobber another section's data. Every sheet is written with its full expected column set even when empty (`_rows_to_df()` falls back to `config_io`'s column constants), so a fully-cleared sheet (e.g. a brand-new case, which starts with none of the 8 sheets present) still round-trips cleanly through `config_io.load_all_config()`.

---

## 8. Design decisions worth knowing

- **Case isolation is folder-per-case, modeled on the legacy Streamlit app's multi-plant structure** (see §2/§3a) — but only the config/model layer is per-case, not the plant physics itself (still one plugin, `yanpet_olf1_formulas.py`, shared by every case). `"default"` is a real case, not a special code path — every case-aware function defaults to it and it resolves to the pre-case-isolation flat file layout unchanged.
- **What-If Setup always opens on System Config.** An earlier "jump to the first incomplete section" default was removed because it silently skipped straight to Model Config whenever System Config was already done, which read as inconsistent/confusing.
- **Model Development is intentionally non-linear.** Its stepper is fully clickable in any order (not a gated wizard) — rebuilding a model, revisiting feature selection, or re-mapping a parameter never requires walking through every step again.
- **Experimentation & Model Selection is explicitly not a model registry.** No versioning, no rollback, no lifecycle states — just "which one experiment, if any, is currently selected per parameter." Selecting a different experiment never deletes the previous one — every past experiment stays visible for comparison until explicitly removed via the 🗑️ Delete action.
- **Dedicated Kalman training is case-aware by env-var reuse, not by a rewritten script.** `Scripts/Model_development_and_static_whatif_testing_updated.py` predates case isolation and still can't be taught to read a `case_id` directly without changing it (which would break it as reference material for `src/whatif/`) — so the backend instead sets the `PLANT_NAME` env var the script already understood for multi-plant deployments, pointing its existing folder-resolution logic at `Data/<case_id>/`/`Results/<case_id>/` for free.
