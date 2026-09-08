# Config Reference — `config/settings.py`

`config/settings.py` is the single source of truth for every constant, path, and default used
across the platform — per its own module docstring, no module at a lower layer (`src/`,
`backend/app/`) should hard-code a value that belongs here (CLAUDE.md). This doc groups every
setting by what it controls and notes which ones are actually live vs. legacy leftovers, so you
know where to look before hardcoding something new and what's safe to ignore.

Import direction is one-way: `config.settings ← src.* ← backend.app.*`.

---

## Storage paths

| Setting | Default | Used for |
|---|---|---|
| `DB_PATH` | `"dashboard.db"` | SQLite file — `datasets`, `model_registry`, `whatif_model_selection`, `whatif_cases` (see [`DATA_SCHEMA.md`](./DATA_SCHEMA.md) §1). |
| `MODEL_DIR` | `"saved_models"` | Root of the model-development pipeline's saved experiments (`saved_models/<case_id>/<model_name>/...`). Created on import via `os.makedirs(MODEL_DIR, exist_ok=True)`. |

## Experiment tracking (MLflow)

| Setting | Default | Notes |
|---|---|---|
| `MLFLOW_TRACKING_URI` | `"sqlite:///mlflow.db"` | Separate SQLite file from `DB_PATH` — MLflow logs params/metrics/artifacts for every training run *alongside* `model_registry`, not instead of it. Browse with `mlflow ui --backend-store-uri sqlite:///mlflow.db`. |
| `MLFLOW_EXPERIMENT_NAME` | `"soft-sensor-training"` | |

## Data pipeline

| Setting | Default | Notes |
|---|---|---|
| `TEST_SIZE` | `0.2` | Default train/test split fraction (`preprocess_service.apply_preprocessing`'s `test_size` param overrides per-request; this is the fallback). |
| `RANDOM_STATE` | `42` | Split/shuffle seed, for reproducibility. |

## Model architecture (DAE encoder/decoder/predictor hidden sizes)

| Setting | Default |
|---|---|
| `ENCODER_HIDDEN_1` | `128` |
| `ENCODER_HIDDEN_2` | `64` |
| `DECODER_HIDDEN_1` | `64` |
| `DECODER_HIDDEN_2` | `128` |
| `PREDICTOR_HIDDEN_1` | `32` |
| `PREDICTOR_HIDDEN_2` | `16` |

## Training defaults (initial values on the Build Model form)

| Setting | Default | Notes |
|---|---|---|
| `DEFAULT_LATENT_DIM` | `5` | DAE bottleneck size. |
| `DEFAULT_DROPOUT_RATE` | `0.2` | |
| `DEFAULT_MASKING_RATIO` | `0.10` | DAE denoising — fraction of inputs randomly masked during training. |
| `DEFAULT_EPOCHS` | `150` | |
| `DEFAULT_LR` | `0.001` | |
| `DEFAULT_WEIGHT_TO_PRED` | `5.0` | Loss-term weight favoring the prediction head over reconstruction in the DAE's combined loss. |
| `DEFAULT_BATCH_SIZE` | `128` | |
| `AUTO_TRAIN_MAX_EPOCHS` | `1000` | Ceiling for auto-train mode (trains until `AUTO_TRAIN_TARGET_R2` or this cap). |
| `AUTO_TRAIN_TARGET_R2` | `0.80` | |
| `DEFAULT_EARLY_STOP_PATIENCE` | `20` | Epochs without validation improvement before stopping. |
| `DEFAULT_LR_PATIENCE` | `10` | Epochs without improvement before LR is halved. |

## What-If simulator

| Setting | Default | Notes |
|---|---|---|
| `MAX_SWEEP_POINTS` | `500` | Cap on sweep/what-if grid resolution. |
| `TREND_EPSILON` | `1e-5` | Minimum delta treated as a real change (vs. floating-point noise) when computing trend direction. |

## What-If Analysis module — file-based paths (`src/whatif/paths.py`)

Kept deliberately separate from `MODEL_DIR`/`DB_PATH` above — this is a different, Excel/pickle-based
persistence world shared with the standalone `Scripts/` reference app, not the `dashboard.db` /
`saved_models` world. See [`DATA_SCHEMA.md`](./DATA_SCHEMA.md) §3 for the full case-scoped directory
layout these resolve into.

| Setting | Default | Notes |
|---|---|---|
| `WHATIF_DATA_DIR` | `"Data"` | |
| `WHATIF_RESULTS_DIR` | `"Results"` | |
| `WHATIF_MODEL_DIR` | `"Results/Model"` | Dedicated Kalman filter `.pkl` files. |
| `WHATIF_CONFIG_FILE` | `"Data/Config_file.xlsx"` | The 8-sheet config workbook — see `DATA_SCHEMA.md` §2. |
| `WHATIF_TRAINING_WORKBOOK` | `"Data/DMC_Screen_tags_data.xlsx"` | Historian training-data workbook. |
| `WHATIF_HISTORIAN_FILE` | `"Results/Raw_data_plus_simulated_data.xlsx"` | Dashboard's date/timestamp/baseline source. |

All resolved to absolute, repo-root-anchored paths by `src/whatif/paths.py` (never `os.getcwd()`-relative — see that module's docstring for why) and case-scoped via `_case_dir()`.

## Feature Selection scoring (`AI Feature Discovery` / consensus feature selection)

See [`MODEL_CONFIG_METHODS.md`](./MODEL_CONFIG_METHODS.md) for what each method actually computes;
this is just the tunable weights/thresholds behind those computations.

**Component weights** (of the Final Score; sum to 1.0 — Feature Quality is excluded, folded into
upstream preprocessing / the VIF gate instead):

| Setting | Default |
|---|---|
| `FS_WEIGHT_SELECTION_FREQ` | `0.30` |
| `FS_WEIGHT_PREDICTIVE_STRENGTH` | `0.50` |
| `FS_WEIGHT_STABILITY` | `0.20` |

**Predictive Strength sub-weights** (5 active scoring methods; must sum to 1.0):

| Setting | Default | Method |
|---|---|---|
| `FS_PS_CORR_WEIGHT` | `0.20` | Target Correlation — fast, linear. |
| `FS_PS_MI_WEIGHT` | `0.25` | Mutual Information — non-linear dependencies. |
| `FS_PS_PERM_WEIGHT` | `0.30` | Permutation Importance — robust, model-agnostic; highest weight. |
| `FS_PS_MRMR_WEIGHT` | `0.15` | mRMR — relevance minus redundancy with already-selected features. |
| `FS_PS_EN_WEIGHT` | `0.10` | Elastic Net — regularization-based, sparse/stable. |

**Multi-Y scaling**: `FS_MULTI_Y_PS_SCALE = 0.08` — each extra Y target softens PS recommendation
thresholds by this fraction, capped at 4 extra targets (32% max softening).

**Recommendation tier thresholds** (VIF is still a hard gate for Highly Recommended; FQ itself was
removed from the Final Score, and its now-unused quality thresholds were deleted from config):

| Setting | Default | Tier / role |
|---|---|---|
| `FS_HIGHLY_REC_MIN_FINAL` | `70.0` | Highly Recommended — min Final Score. |
| `FS_HIGHLY_REC_MIN_PRED_STRENGTH` | `65.0` | Highly Recommended — min Predictive Strength. |
| `FS_HIGHLY_REC_MAX_VIF` | `10.0` | Hard gate — VIF above this disqualifies Highly Recommended regardless of score. |
| `FS_RECOMMENDED_MIN_FINAL` | `50.0` | Recommended — min Final Score. |
| `FS_RECOMMENDED_MIN_PRED_STRENGTH` | `45.0` | Recommended — min Predictive Strength. |
| `FS_CONSIDER_MIN_FINAL` | `35.0` | Consider — min Final Score. |
| `FS_WEAK_MAX_PRED_STRENGTH` | `30.0` | Weak — max Predictive Strength (below this, flagged weak). |

**Stability bootstrap** (repeated-subsample selection-frequency scoring):

| Setting | Default |
|---|---|
| `FS_STABILITY_RUNS` | `20` |
| `FS_STABILITY_SAMPLE_FRAC` | `0.80` |
| `FS_STABILITY_MAX_ROWS` | `3000` (bootstrap subsampling capped at this many rows, for speed on large datasets) |

## Evaluation / grading thresholds

| Setting | Default | Notes |
|---|---|---|
| `R2_EXCELLENT` | `0.85` | R² at/above this grades a trained model "Excellent". |
| `R2_GOOD` | `0.75` | R² at/above this (and below excellent) grades "Good". |

---

## Legacy / unused — do not extend

`PAGE_TITLE`, `PAGE_LAYOUT`, `SIDEBAR_STATE`, `NAVIGATION_OPTIONS`, `NAVIGATION_ICONS`, and
`THEME_CSS` were Streamlit-era UI constants with zero references anywhere in the repo (not even
`Scripts/`) and were removed from `config/settings.py`. The frontend's own theme lives in
`frontend/src/theme.css` per CLAUDE.md's "no UI library, hand-rolled CSS" convention.
