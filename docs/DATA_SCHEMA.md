# Data & Storage Schema

Where every piece of persistent state lives, in one place: the `dashboard.db` SQLite tables, the
8-sheet `Config_file.xlsx` workbook, and the on-disk model/dataset layout. For *how* config sections
get read/written over HTTP see [`API_REFERENCE.md`](./API_REFERENCE.md); for the one deliberate
cross-reference between the two persistence worlds see CLAUDE.md ("the one deliberate bridge") and
`whatif_model_selection` below.

Everything here is **case-scoped** (see [`flow.md`](./flow.md) §2/§3a): `case_id="default"` resolves
to the original flat, pre-case-isolation layout unchanged; any other `case_id` nests under a
`<case_id>` subfolder (or a `case_id` column, for SQLite tables). Path resolution lives in
`src/whatif/paths.py`; model-file resolution in `src/persistence/model_store.py::case_model_dir()`.

---

## 1. `dashboard.db` (SQLite, `config/settings.py::DB_PATH`)

Bootstrapped by `src/data/database.py::init_db()`, called on every backend startup. Schema
migrations are additive-only (`_ensure_column()` — idempotent `ALTER TABLE ADD COLUMN`) except the
one-time `datasets` table rebuild described below; nothing is ever dropped or rewritten destructively.

### `datasets`
Uploaded datasets, serialized as Parquet BLOBs — lets users switch datasets without re-uploading.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `name` | TEXT | Display name; unique **within a case**, not globally. |
| `upload_time` | TEXT | `YYYY-MM-DD HH:MM:SS` |
| `num_rows`, `num_cols` | INTEGER | |
| `data` | BLOB | `DataFrame.to_parquet()` output, after `_sanitize_for_parquet()` (object columns coerced to numeric or string). |
| `plant`, `unit` | TEXT, nullable | Connect Process Data page metadata. |
| `case_id` | TEXT, default `"default"` | `UNIQUE(case_id, name)` — same filename can exist independently in two cases. |

Rebuilt once from an original schema with a globally-unique `name` (SQLite can't `ALTER` a UNIQUE
constraint in place) — `_migrate_datasets_case_scoping()` reconstructs the table with
`UNIQUE(case_id, name)` and backfills every existing row as `case_id='default'`, so no data moves for
existing installs. Guarded to run only once (checks whether `case_id` already exists).

### `model_registry`
One row per trained/saved model-development experiment.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `model_name` | TEXT | Matches the `saved_models/<case_id>/<model_name>/` folder name. |
| `algorithm` | TEXT | One of `training.py::ALGORITHMS`. |
| `created_at` | TEXT | |
| `dataset_name` | TEXT | |
| `x_cols`, `y_cols` | TEXT (JSON array) | |
| `avg_r2`, `avg_rmse`, `avg_mae` | REAL | Test-set metrics. |
| `train_r2`, `train_rmse`, `train_mae` | REAL, nullable | Train-set metrics, added later alongside test metrics so overfitting is visible without a leakage-prone live recompute. `NULL` on older rows, shown as "—". |
| `file_path` | TEXT | |
| `case_id` | TEXT, default `"default"` | |

### `whatif_model_selection` — **the bridge table**
Records which `model_registry` experiment is "Selected for What-If Analysis" for a given predicted
parameter. `src/whatif/engine.py::predict_and_update_with_soft_sensor_model()` checks this before
falling back to a dedicated Kalman filter — this is the *only* cross-reference between What-If
Studio and its embedded model-development pipeline (CLAUDE.md). Don't add others.

| Column | Type | Notes |
|---|---|---|
| `parameter` | TEXT | Originally the sole PRIMARY KEY (single-column, pre-case-isolation). |
| `model_name` | TEXT NOT NULL | |
| `selected_at` | TEXT NOT NULL | |
| `case_id` | TEXT, default `"default"` | |

One row per `(case_id, parameter)` is enforced in **application code**
(`set_model_selection()`: explicit `DELETE` then `INSERT`), not a composite primary key — the table
already shipped with a single-column `parameter` PK and SQLite can't cheaply change a PK on an
existing table.

### `whatif_cases`
Case registry — folder-per-case isolation modeled on the legacy Streamlit app's multi-plant
structure, applied here to isolated scenario setups for one plant rather than different plants.

| Column | Type | Notes |
|---|---|---|
| `case_id` | TEXT PRIMARY KEY | Sanitized (`[^A-Za-z0-9_-]` → `_`) folder-safe id, used directly as the `Data/<case_id>` / `Results/<case_id>` folder name. |
| `name` | TEXT NOT NULL | User-typed display name. |
| `created_at`, `last_opened_at` | TEXT NOT NULL | `last_opened_at` bumped by `touch_case_opened()` on `POST /api/what-if/cases/{case_id}/open`. |

Seeded with one row (`case_id="default", name="Default Case"`) on first `init_db()`.

---

## 2. `Config_file.xlsx` — the 8-sheet What-If config workbook

Loaded in one shot by `src/whatif/config_io.py::load_all_config()` into a `WhatIfConfig` dataclass
(field-per-sheet), passed explicitly into `engine.py::whatif_analysis()` rather than re-read from
disk per call. Sheet-name matching is **tolerant of spacing/casing** (`_norm_name()` strips
everything but `[a-z0-9]`) — e.g. `"PI_Generalised_Name"`, `"pi generalised name"`, and
`"PiGeneralisedName"` all resolve to the same field. Two sheets sometimes present on real workbooks,
`process_param_stats` and `Model details_copy`, are recognized-but-ignored.

Written back out by `_write_all_sheets()` (called from every `commit_*` service function) — every
section persists immediately on its own "Save," per CLAUDE.md; there's no separate commit step.

| Sheet (canonical) | `WhatIfConfig` field | Columns | Purpose |
|---|---|---|---|
| `PI_Generalised_Name` | `pi_names_df` | `Pi_tags, Generalized Description, Section` | Maps raw historian PI tag names → human-readable labels, grouped by process section. |
| `Model details` | `model_details_df` | `Predicted parameter, Section, Input parameter_1..8, model type` | One row per predicted parameter: its inputs and whether it's a `"Data model"` (trained soft-sensor/Kalman) or `"First principle"` (plugin/formula) row. Blank/NaN `model type` defaults to a data model. |
| `Constraints` | `constraints_df` | `Parameter, user input value, Max vlaue*, UOM, Remark, Linked Parameter, Action` | Generic `bump_linked_to_max` / `abort_if_exceeds` rules applied around each engine step — see `flow.md` §6. `Action` selects which rule. |
| `display_column_order` | `display_order_df` | `Sr.no, Preferred columns` | Dashboard table column ordering. |
| `user inputs` | `user_inputs_df` | `Parameter, Value, Lower Limit, Upper Limit, Remark` | Default/override values for scenario input parameters. |
| `Section order` | `section_order_df` | `Sr.no, Section` | The plant's process-flow sequence — drives `Target Section` scoping (upstream sections computed at or before the target only). |
| `MV_DV_CV_taglist` | `mvdvcv_df` | `Name, GeneralizedDescription, Section, Type` | Alternative/prioritized input-tag source for Model Mapping (MV=manipulated, DV=disturbance, CV=controlled variable). |
| `Formulas` | `formulas_df` | `Predicted parameter, Formula` | One row per First-principle parameter computed from a user-typed math expression (Model Definition's Formula Editor) instead of a hardcoded plant plugin — evaluated by `src/whatif/formula_eval.py`. |
| `Target Section` | scalar `target_section` (not a DataFrame field) | single cell, or a `Target Section` column | Which section the current case setup is scoped up to. Empty/missing ⇒ no scoping (all sections active). |

\* `Constraints`' max-value column has two spellings seen on real workbooks: the historical
`"Max vlaue"` (misspelled) and a corrected `"Max value"`. `constraints_max_col()` resolves whichever
is actually present at read time — neither reading nor writing code hardcodes one variant.

**Backward compatibility**: `Section order`, `Target Section`, and `MV_DV_CV_taglist` are a later
addition to an originally 5-sheet schema (the older shape had no process-flow concept — every
predicted parameter was always computed). All three default to empty/`None` rather than raising on
an older-shaped workbook, and section-scoping in `engine.py` is a no-op when they're absent.

---

## 3. On-disk layout (`config/settings.py` path constants, resolved case-scoped by `src/whatif/paths.py`)

```
<repo root>/
├── dashboard.db                                  # §1 above
├── saved_models/<case_id>/<model_name>/          # model-development pipeline experiments (flat saved_models/<model_name>/ for case_id="default")
│   ├── model.pth | model.pkl                     # PyTorch (DAE/LSTM) or pickled sklearn/xgboost/lightgbm/Kalman estimator
│   ├── scaler_x.pkl / scaler_y.pkl                # fitted StandardScalers
│   ├── columns.pkl                                # {"x_cols": [...], "y_cols": [...]}
│   └── metadata.pkl                               # {name, saved_at, input_dim, output_dim, model_type, x_cols, y_cols}
├── Data/<case_id>/                                # What-If Studio config + training inputs (flat Data/ for "default")
│   ├── Config_file.xlsx                           # §2 above
│   └── DMC_Screen_tags_data.xlsx                  # historian training-data workbook (WHATIF_TRAINING_WORKBOOK)
└── Results/<case_id>/                             # What-If Studio outputs (flat Results/ for "default")
    ├── Model/                                     # dedicated Kalman filter .pkl files, one per non-selected/non-plugin predicted parameter (WHATIF_MODEL_DIR)
    ├── Raw_data_plus_simulated_data.xlsx           # historian + simulated data, dashboard's date/timestamp/baseline source (WHATIF_HISTORIAN_FILE)
    └── Actual_vs_estimated_what_if_<suffix>.xlsx   # optional per-request scenario output (unique suffix per request — never the fixed name, to avoid concurrent-request overwrites)
```

`case_id="default"` always resolves to the flat, un-nested form of each path above (no `Model_selection`
migration needed for pre-existing installs); any other `case_id` nests one level under
`Data/`, `Results/`, and `saved_models/`. A brand-new case starts with **empty** `Data/<case_id>` and
`Results/<case_id>/Model` folders — nothing is copied or templated from another case (`paths.py::new_case_dirs()`).

### Model type → saved file, by algorithm

| `model_type` (in `metadata.pkl`) | Weight file | Wrapper class |
|---|---|---|
| `DAE` | `model.pth` (PyTorch state dict + `input_dim`/`latent_dim`/`output_dim`) | `DAEWrapper` |
| `LSTM` | `model.pth` (state dict + `input_size`/`hidden_size`/`n_layers`/`output_size`/`dropout`/`window_size`) | `LSTMWrapper` |
| `Random Forest`, `XGBoost`, `LightGBM`, `Kalman Filter` | `model.pkl` (pickled estimator) | `SklearnWrapper` |

Loading a model with no `model_type` key in `metadata.pkl` defaults to `"DAE"` (backward compat with
models saved before multi-algorithm support existed).

---

## 4. How the pieces connect

```
Model Config pipeline (Upload → Preprocess → Feature Selection → Train)
        │  writes                                   │ writes
        ▼                                            ▼
   datasets (SQLite)                          model_registry (SQLite)  +  saved_models/<name>/ (disk)
                                                            │
                                                            │  "Selected for What-If Analysis"
                                                            ▼
                                          whatif_model_selection (SQLite) ── the bridge ──┐
                                                                                            │
What-If Studio config (Config_file.xlsx, §2)                                              │
        │                                                                                  │
        ▼                                                                                  ▼
  src/whatif/engine.py::whatif_analysis()  ──►  per predicted parameter, tries in order:
        plant-physics plugin  →  Selected Soft Sensor experiment (via the bridge above)  →
        dedicated Kalman filter (Results/<case_id>/Model/*.pkl)  →  baseline value
```
