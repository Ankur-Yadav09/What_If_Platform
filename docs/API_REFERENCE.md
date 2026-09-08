# API Reference

Every route this backend exposes, in one table, with its request/response shape and the service
function it calls. For *how a request flows through the layers* see
[`ARCHITECTURE.md`](./ARCHITECTURE.md) §5 (one request traced end-to-end); for *when the frontend
calls each one* see [`flow.md`](./flow.md); for the algorithms behind Model Config's three
heaviest screens see [`MODEL_CONFIG_METHODS.md`](./MODEL_CONFIG_METHODS.md).

All routes are mounted under `/api` (`backend/app/main.py`). All routes except case CRUD
(`POST /api/what-if/cases`, `GET /api/what-if/cases`) and job polling (`GET /api/jobs/{id}`) accept
`case_id` — as a query param defaulting to `"default"` everywhere, except `POST /api/what-if/cases/{case_id}/open`
where it's a path param. See [`flow.md`](./flow.md) §3a for how the frontend stamps this
automatically. Routes are enforced case-valid by the `require_valid_case_id` dependency
(`backend/app/api/deps.py`), which 404s on an unknown `case_id` — this re-check runs on every
request, not just at case creation.

Long-running operations (feature selection, training) return a `job_id` (`202 Accepted`) instead of
a result; poll `GET /api/jobs/{id}` until `done: true`. Everything else responds synchronously.

---

## Jobs

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/jobs/{job_id}` | — | `JobStatusResponse` | `status`: `pending`\|`running`\|`done`\|`error`. `result` populated only when `status == done`. 404 if `job_id` unknown. |

`JobStatusResponse`: `id, status, progress: dict, error: str|None, done: bool, result: Any|None`

---

## Datasets (`backend/app/services/dataset_service.py`)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `/api/datasets/upload` | multipart: `file`, `dataset_name?`, `plant?`, `unit?` | `DatasetSummary` (201) | Excel/CSV upload. |
| GET | `/api/datasets` | — | `DatasetListResponse` | |
| GET | `/api/datasets/{name}/preview` | — | `DatasetPreview` | `shape`, `columns`, first-N `head` rows. |
| DELETE | `/api/datasets/{name}` | — | 204 | |

`DatasetSummary`: `name, uploaded_at, rows, cols, plant?, unit?, status="Ready"`
`DatasetPreview`: `name, shape: [rows, cols], columns, head: list[dict]`

---

## Preprocess (`backend/app/services/preprocess_service.py`, `project_service.py`)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/preprocess/{dataset_name}/stats` | — | `FeatureStatsResponse` | Per-column summary stats. |
| GET | `/api/preprocess/{dataset_name}/correlation-matrix` | — | `CorrelationMatrixResponse` | |
| GET | `/api/preprocess/{dataset_name}/correlation-matrix/export` | — | `.xlsx` file | `Content-Disposition: attachment`. |
| GET | `/api/preprocess/{dataset_name}/feature-detail?column=` | — | `FeatureDetailResponse` | Histogram/boxplot/skew/kurtosis for one column. |
| POST | `/api/preprocess/clean` | `BasicCleaningRequest` | `CleaningResponse` | Manual cleaning knobs (missing rows/cols, duplicates, NZV, imputation, outliers, domain filters). |
| POST | `/api/preprocess/automated` | `AutomatedCleaningRequest` | `CleaningResponse` | One-click cleaning with fixed heuristics. |
| POST | `/api/preprocess/apply` | `ApplyPreprocessingRequest` | `ApplyPreprocessingResponse` | Finalizes X/Y split → creates a **project** (`project_id`). |
| GET | `/api/projects` | — | `list[ProjectSummary]` | |

`ApplyPreprocessingRequest`: `dataset_name, x_cols, y_cols, imputation_method="Mean", outlier_method="None", domain_filters?, split_method="random", test_size?, stratify_bins=0`
`ApplyPreprocessingResponse` / `ProjectSummary`: `project_id, dataset_name, x_cols, y_cols, n_train, n_test` (+`created_at, config` on `ProjectSummary`)
`CleaningResponse`: `new_dataset_name, before_rows, after_rows, before_cols?, after_cols, action_log?, step_log?`

---

## Feature Selection (`backend/app/services/feature_selection_service.py`)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `/api/feature-selection/jobs` | `FeatureSelectionRequest` | `JobIdResponse` (202) | Async — poll `/api/jobs/{id}`. |

`FeatureSelectionRequest`: `dataset_name, y_cols, x_cols?, top_k=10, enabled_methods?, corr_threshold=0.85, vif_threshold=10.0, per_target=false, process_aware=false`
`process_aware=true` restricts each Y's candidate X's to columns appearing *before* it in the
dataset's original column order (upstream-only, for process-flow-ordered datasets). See
`MODEL_CONFIG_METHODS.md` for what the consensus methods themselves compute.

---

## Training (`backend/app/services/training_service.py`)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `/api/training/jobs` | `TrainingRequest` | `{"job_id": str}` (202) | 422 if `project_id`/`algorithm` invalid. |

`TrainingRequest`: `project_id, algorithm, hyperparameters: dict = {}`
`algorithm` ∈ `ALGORITHMS = ("DAE", "Random Forest", "XGBoost", "LightGBM", "LSTM", "Kalman Filter")` (`backend/app/schemas/training.py`).

---

## What-If Studio — Cases (`backend/app/services/whatif_case_service.py`)

Undecorated by `require_valid_case_id` — case creation/listing has no case to validate yet, and
`cases_open` validates via `whatif_case_service.open_case()` → `database.get_case()` (404 if unknown).

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/what-if/cases` | — | `CasesListResponse` | |
| POST | `/api/what-if/cases` | `CreateCaseRequest {name}` | `WhatIfCase` | |
| POST | `/api/what-if/cases/{case_id}/open` | — | `WhatIfCase` | `case_id` is a **path** param here, not query. Updates `last_opened_at`. |

`WhatIfCase`: `case_id, name, created_at, last_opened_at`

---

## What-If Studio — Config / Wizard / Model Status (`what_if_service.py`)

All take `case_id` as a query param (default `"default"`).

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/what-if/config/status` | — | `ConfigStatusResponse` | Whether PI mapping / model details sheets exist and their row counts. |
| GET | `/api/what-if/config/pi-mapping` | — | `RowsResponse` | |
| POST | `/api/what-if/config/upload` | multipart `file` | `ConfigStatusResponse` | Upload a full config workbook (all 8 sheets) at once. |
| GET | `/api/what-if/wizard/detected-counts` | — | `DetectedCountsResponse` | Max CGC/PRC/ERC/furnace stage counts detected from historian tags. |
| POST | `/api/what-if/wizard/generate-mapping` | `GenerateMappingRequest` | `GenerateMappingResponse` | Wizard: generate PI-mapping rows from stage counts. |
| PUT | `/api/what-if/config/mapping` | `MappingRowsRequest {rows}` | `RowsResponse` | Commit PI mapping sheet. |
| GET / PUT | `/api/what-if/config/model-mapping` | `MappingRowsRequest` (PUT) | `ModelMappingResponse` (GET) / `RowsResponse` (PUT) | GET also returns `historian_tags`. |
| GET / PUT | `/api/what-if/config/formulas` | `MappingRowsRequest` (PUT) | `RowsResponse` | First-principle formula rows. |
| POST | `/api/what-if/config/formulas/validate` | `FormulaValidateRequest {formula}` | `FormulaValidateResponse` | Parses/validates a formula string; returns referenced `variables`. |
| POST | `/api/what-if/config/export` | `ConfigExportRequest` | `.xlsx`/`.csv` file | Download-only — does **not** persist. `format: "xlsx"\|"csv"`. |
| GET / PUT | `/api/what-if/config/section-order` | `MappingRowsRequest` (PUT) | `RowsResponse` | |
| GET / PUT | `/api/what-if/config/mv-dv-cv-taglist` | `MappingRowsRequest` (PUT) | `RowsResponse` | |
| GET / PUT | `/api/what-if/config/constraints` | `MappingRowsRequest` (PUT) | `RowsResponse` | `bump_linked_to_max` / `abort_if_exceeds` rules — see `flow.md` §6. |
| GET / PUT | `/api/what-if/config/user-inputs` | `MappingRowsRequest` (PUT) | `RowsResponse` | |
| GET / PUT | `/api/what-if/config/column-order` | `MappingRowsRequest` (PUT) | `RowsResponse` | |
| GET / PUT | `/api/what-if/config/target-section` | `TargetSectionRequest` (PUT) | `TargetSectionResponse` | `active_scope` = upstream sections + target in process-flow order; `excluded_sections` = downstream sections hidden by current scope. |
| POST | `/api/what-if/config/save` | `ConfigSaveRequest` | `ConfigStatusResponse` | **The** single-shot persistence endpoint — all 8 sheets in one call. Each section's own PUT above also persists immediately per CLAUDE.md; this is the "save everything" variant. |
| GET | `/api/what-if/config/correlation-matrix` | — | `CorrelationMatrixResponse` | Correlation matrix over the case's training data. |
| GET | `/api/what-if/models/accuracy-summary` | — | `AccuracySummaryResponse` | Per-parameter accuracy rows (empty/`available=false` if nothing trained yet). |
| POST | `/api/what-if/training-data/upload` | multipart `file` | `TrainingDataUploadResponse` | Upload historian training data workbook; reports `sheets_found`/`missing_sheets`. |
| GET | `/api/what-if/models/status` | — | `ModelStatusResponse` | Readiness check before training — `can_train`, `train_blockers`, per-tag presence. |
| POST | `/api/what-if/models/train` | — | `TrainModelsResponse {job_id}` (202) | Kicks off `Scripts/Model_development_and_static_whatif_testing_updated.py` as a subprocess — see CLAUDE.md "Things that look wrong but aren't". |

---

## What-If Studio — Dashboard (scenario compute)

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| POST | `/api/what-if/dashboard/tag-options` | `TagOptionsRequest` | `TagOptionsResponse` | `source`: `"wizard"`\|`"config"`\|`"historian"` — which layer the tag list came from. Also returns per-tag `limits`. |
| GET | `/api/what-if/dashboard/dates` | — | `DatesResponse` | Available historian dates for this case. |
| GET | `/api/what-if/dashboard/timestamps?date=` | — | `TimestampsResponse` | Timestamps available for one date. |
| GET | `/api/what-if/dashboard/baseline?timestamp=&tags=` | — | `BaselineResponse` | `tags` is comma-separated; actual historian values at `timestamp` for those tags. |
| POST | `/api/what-if/dashboard/compute` | `WhatIfScenarioRequest` | `WhatIfScenarioResponse` | **The core simulation call** — runs `src/whatif/engine.py::whatif_analysis()`. Synchronous. |
| POST | `/api/what-if/dashboard/validation-filter` | `ValidationFilterRequest` | `ValidationFilterResponse` | Filters historian rows by per-tag min/max/values criteria; returns matching rows + `match_count`. |
| POST | `/api/what-if/dashboard/export-csv` | `WhatIfExportCsvRequest` | `.csv` file | Client sends back the rows it already has (no server recompute). |

`WhatIfScenarioRequest`: `timestamp, overrides: [{parameter, value}], write_actual_vs_estimated_xlsx=false, target_section?`
`WhatIfScenarioResponse`: `constraint_hit: bool, constraint_message?, rows: [{parameter, actual, estimated, change}], kpis: [{tag, actual, estimated, change}]`
`ValidationFilterRequest`: `filters: {tag: {min?, max?, values?}}, target_section?` → `ValidationFilterResponse: {rows, match_count}`

---

## What-If Studio — Experiments (Experimentation & Model Selection tab)

Moved here from the old standalone Soft Sensor Module's `overview.py` — see CLAUDE.md.

| Method | Path | Request | Response | Notes |
|---|---|---|---|---|
| GET | `/api/what-if/experiments` | — | `ExperimentsOverviewResponse` | All datasets + all saved-model experiments for the case, each experiment's `selected_for` list of parameters. |
| POST | `/api/what-if/experiments/select` | `SelectModelRequest {parameter, model_name}` | `ExperimentsOverviewResponse` | Writes `whatif_model_selection` — **the** bridge table (CLAUDE.md). 400 on invalid selection. |
| POST | `/api/what-if/experiments/clear-selection` | `ClearSelectionRequest {parameter}` | `ExperimentsOverviewResponse` | |
| DELETE | `/api/what-if/experiments/{model_name}` | — | `ExperimentsOverviewResponse` | Deletes a saved-model experiment (registry entry + `.pkl`). |

`SavedModelSummary`: `name, saved_at, input_dim, output_dim, algorithm?, dataset_name?, avg_r2?, avg_rmse?, avg_mae?, train_r2?, train_rmse?, train_mae?, x_cols, y_cols, selected_for: [parameter, ...]`

---

## Request/response conventions worth knowing

- **Case scoping**: nearly every route resolves paths through `src/whatif/paths.py` using `case_id`;
  `"default"` reads/writes the original flat `Data/`/`Results/` layout unchanged (pre-case-isolation
  compatibility).
- **Config section endpoints are symmetric**: each config section (`pi-mapping`, `model-mapping`,
  `formulas`, `section-order`, `mv-dv-cv-taglist`, `constraints`, `user-inputs`, `column-order`,
  `target-section`) follows `GET` (read current rows) / `PUT` with `MappingRowsRequest{rows}` (commit
  — persists immediately, no separate commit step per CLAUDE.md).
- **Downloads vs. persistence**: `/config/export` and `/dashboard/export-csv` only ever return a
  file — they never write to the on-disk config/state. `/config/save` and every section's own `PUT`
  are the persistence paths.
- **Errors**: validation failures mostly surface as FastAPI's default 422 (Pydantic) or an explicit
  `HTTPException` (400 for an invalid model selection, 404 for an unknown job/case, 422 for an
  invalid `project_id`/`algorithm` pair in training).
