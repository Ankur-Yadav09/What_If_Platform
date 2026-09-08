# Model Config — Methods & Algorithms Reference

This is a deep, implementation-level reference for the three most algorithm-heavy screens inside
**What-If Setup → Model Config → Model Development**: **Model Definition**, **AI Feature Discovery**,
and **Build Model**. It explains *what each method computes and why*, not just which button calls which
endpoint — for the screen-by-screen click path see [`flow.md`](./flow.md) §4b, and for the general
routes→schemas→services→src layering see [`ARCHITECTURE.md`](./ARCHITECTURE.md).

All the logic described here lives in framework-agnostic `src/` modules (no FastAPI/React), wired up by
thin `backend/app/services/*.py` orchestrators — see each section's "Where this lives" line.

---

## 0. How the three screens fit together

```
Connect Data → Data Health → Model Definition → AI Feature Discovery → Build Model
                                     ↑                                        │
                                     └──────────── "Configure Model" ─────────┘
```

- **Model Definition** (`ModelMappingEditor.tsx`) declares *what* needs a model: one row per Predicted
  Parameter, each either a **Data model** (needs a trained soft-sensor / Kalman model) or a
  **First principle** row (computed by a plant-physics plugin or a typed math formula — never trained).
- **AI Feature Discovery** (`FeatureSelectionPage.tsx`) picks *which input tags* (X) best predict a given
  Predicted Parameter (Y), for Data-model rows only.
- **Build Model** (`TrainPage.tsx`) trains an actual model on the chosen X/Y set and one of 6 algorithms,
  then saves it as an "experiment" that Experimentation & Model Selection can mark **"Selected for
  What-If Analysis."**

The stepper is non-linear by design — see `flow.md` §8 — and "Configure Model →" on a Model Definition
row pre-fills the target Y for both later steps (`activeTargetY` in `ModelConfigTab.tsx`).

---

## 1. Model Definition

**Where this lives:** `ModelMappingEditor.tsx` (frontend) · `GET/PUT /api/what-if/config/model-mapping`
· `what_if_service.py::get_model_mapping()` / `commit_model_mapping()` (backend) · the `Model details`
sheet of `Config_file.xlsx`, schema in `src/whatif/config_io.py`.

### 1.1 Row shape

Each row maps one **Predicted Parameter** to:
- a **Section** (which stage of the plant process-flow it belongs to — see `Section Order` sheet),
- up to **8 Input Parameters** (`Input parameter_1..8` — a fixed-column schema, `INPUT_COLS` in the
  frontend, `config_io.INPUT_PARAMETER_COLUMNS` in the backend),
- a **model type**: blank or `"Data model"` (the default) vs. `"First principle"`.

`isDataModelRow()` (frontend) / `config_io._is_data_model()` (backend) both apply the exact same rule:
blank or `"Data model"` → goes through the AI Feature Discovery / Build Model pipeline; anything else
(`"First principle"`) → has no trainable model at all. Its value at scenario-compute time instead comes
from `src/whatif/plants/yanpet_olf1_formulas.py`'s `SIMULATION`/`BULK_SIMULATION` functions, or — if the
row has a saved **Formula** — a typed math expression (§1.3). The What-If engine (`engine.py`) skips
Kalman/Soft-Sensor prediction for these rows entirely (see `flow.md` §6).

### 1.2 Section scoping of the input dropdowns

Each row's 8 input dropdowns are scoped to *that row's own* chosen Section via
`modelInputOptionsForSection()` (`caseSetupHelpers.ts`) — only tags belonging to that Section or a
Section upstream of it (per `Section Order`) are offered, so a row can't accidentally pull an input from
a downstream stage that hasn't happened yet. A row with no Section set gets the full unfiltered tag list.
A row you're actively editing stays visible even if you change its Section mid-edit
(`useTouchedRowIndices.ts`, `flow.md` §4a) — it never appears to vanish.

### 1.3 First-Principle formulas (`FormulaEditor.tsx`)

**Where this lives:** `src/whatif/formula_eval.py` · `GET/PUT /api/what-if/config/formulas` ·
`what_if_service.py::get_formulas()` / `commit_formulas()` / `validate_formula()`.

A First-Principle row can optionally carry a typed arithmetic **Formula** instead of relying purely on
the plant plugin. The formula string is **never** run through Python's `eval()`/`exec()` — that would let
a saved formula execute arbitrary code. Instead:

1. `ast.parse(expr, mode="eval")` parses it into an AST.
2. `_walk_check()` walks every node and rejects anything outside an explicit whitelist:
   - binary ops: `+ - * / % ** //`
   - unary ops: `+x`, `-x`
   - functions: `sqrt, log, log10, log2, exp, abs, min, max, pow, round` (mapped straight to
     `math`/builtin equivalents)
   - variable names (resolved against the historian row at evaluate time) and numeric literals.
3. `validate_formula(expr)` runs this check with no data (syntax/whitelist only — lets the UI flag a bad
   formula immediately, before any row is available).
4. `evaluate_formula(expr, variables)` runs the same check plus substitutes `variables` (a dict of
   tag→value) to produce the actual number at scenario-compute time.
5. `extract_variable_names(expr)` pulls out every variable name referenced — `commit_formulas()`
   auto-writes these into that row's own `Input parameter_1..8` cells (truncated to 8,
   `_sync_formula_inputs()` in `what_if_service.py`), the same way `ModelConfigTab.tsx`'s
   `withSyncedInputs()` does for a Data-model row's AI-selected X features — so `engine.py`'s dependency
   graph (built purely off those 8 cells) schedules the row after whatever it reads, without the user
   re-typing anything.

Any parse error or non-whitelisted construct raises `FormulaError`, surfaced back to the editor as a
validation message.

### 1.4 "Configure Model →" hand-off

Clicking **Configure Model** on a Data-model row (`onConfigureModel` in `ModelConfigTab.tsx`) sets
`activeTargetY` to that row's Predicted Parameter and jumps the stepper to AI Feature Discovery, which
locks its target-Y picker to that value (`lockedTargetY`). Accepting a trained model there
(`handleAccept()`) does two things atomically:
1. `POST /api/what-if/experiments/select` — marks that experiment **"Selected for What-If Analysis"**
   for this parameter (the one bridge described in `ARCHITECTURE.md` §4).
2. `withSyncedInputs()` writes the accepted model's X columns back into this row's own
   `Input parameter_1..8` cells and calls `commitModelMapping()` — so Model Definition always reflects
   exactly what the selected model actually consumes, without a second manual save.

A row counts as **"Model Ready"** purely by having a Selected experiment (`findSelectedModel()`) — there
is no separate client-side "accepted" flag to fall out of sync.

---

## 2. AI Feature Discovery

**Where this lives:** `src/feature_selection/auto_selector.py` (~1,900 lines, all the actual math) ·
`backend/app/services/feature_selection_service.py` (job wrapper + JSON serialization) ·
`POST /api/feature-selection/jobs` (background job, polled via `GET /api/jobs/{id}`) ·
`FeatureSelectionPage.tsx` / `RankingMatrix.tsx` / `FeatureSelectionResults.tsx` / `FinalApply.tsx`
(frontend).

This is a **consensus feature-selection engine**: instead of trusting one scoring method, it runs 5
statistically-independent methods, combines their opinions into one weighted score per feature, cross-
checks that score for redundancy and stability, and emits a plain-English "why" for every feature.

### 2.1 The 5 core scoring methods

All 5 run over the same cleaned `X_df`/`y_df` (`_safe_fill()` mean-imputes NaNs, `_drop_constant_cols()`
drops zero-variance columns first). Each yields a `MethodResult`: a raw score per feature, a 0–1
normalized score (`_normalize_scores()` — min-max), and its own top-`k` selection.

| # | Method (`method_id`) | Category | What it measures | Implementation |
|---|---|---|---|---|
| 1 | **Target Correlation** (`target_correlation`) | Supervised | Linear association with each target | Pearson `r` between each X and each Y; averaged `\|r\|` across all Y targets when multi-output. Also records the majority sign (pos/neg) per feature. |
| 2 | **Mutual Information** (`mutual_information`) | Supervised | Non-linear statistical dependency with each target | `sklearn.feature_selection.mutual_info_regression`, averaged across targets (`random_state=42` for reproducibility) |
| 3 | **mRMR** (`mrmr`) | Advanced Filter | Maximum Relevance, Minimum Redundancy | Greedy selection: relevance = mean MI(X, each Y); redundancy = mean MI(candidate, already-selected X's). At each step picks the feature maximizing `relevance − redundancy`. MI (not Pearson) is used for the redundancy term specifically to catch **non-linear** redundancy between two sensors that are functionally equivalent but not linearly correlated. Score = rank position (first picked = `top_k`, decreasing). |
| 4 | **Permutation Importance** (`permutation_importance`) | Feature Importance | Model-agnostic drop in predictive power when a feature is shuffled | Trains one `RandomForestRegressor(n_estimators=50, max_features=0.5)` **per Y target** (not on averaged Y — averaging first would dilute a feature that's a specialist for only one target), runs `sklearn.inspection.permutation_importance` (5 repeats) on each, negative importances clipped to 0, then averaged across targets. Sampled to at most 5,000 rows for speed. Skipped automatically above 100 features. |
| 5 | **Elastic Net** (`elasticnet`) | Intrinsic | Regularized coefficient magnitude (L1+L2) | `ElasticNetCV` (single-Y) or `MultiTaskElasticNetCV` (multi-Y), both CV-tuned for `alpha`, fit on `StandardScaler`-scaled X. Score = `\|coefficient\|`; a feature is flagged "selected" if its coefficient exceeds `1e-8` (i.e. wasn't zeroed out by the L1 penalty). |

A method that throws an exception is caught and recorded as a **failed** `MethodResult` (all-zero scores,
`success=False`) — it's excluded from every downstream aggregate rather than crashing the whole run.

### 2.2 Non-voting structural analyses (informational, don't affect ranking)

- **Correlation Matrix** — X–X Pearson correlation (`corr_matrix`), used only by the multicollinearity
  dedup pass (§2.4) and the UI's Correlation Matrix view.
- **VIF (Variance Inflation Factor)** — for each feature, regress it on all the others (`Ridge` when
  `n_features ≥ 0.5·n_rows`, else closed-form least squares) and compute `VIF = 1/(1−R²)`, capped at
  9999. Skipped entirely above 80 features (performance). `VIF_Level`: High (>10), Moderate (>5), Low
  otherwise. VIF is the **sole data-health gate** for "Highly Recommended" (§2.5) — Feature Quality
  (below) is computed but no longer gates recommendation directly, since missing-value/variance issues
  are expected to be handled upstream in Data Health preprocessing.
- **Target correlation table** — raw signed Pearson `r` per feature × per target, shown in the UI and fed
  into per-feature reasoning.

### 2.3 Composite scores

Four scores are computed per feature and combined into one **Final Score**:

**Predictive Strength (0–100)** — a weighted blend of the 5 core methods' *normalized* scores:

```
target_correlation      0.20
mutual_information      0.25
permutation_importance  0.30
mrmr                    0.15
elasticnet              0.10
```
(`FS_PS_*_WEIGHT` in `config/settings.py`.) If a method failed, its weight is redistributed
proportionally across the methods that did succeed, so PS always lands on a true 0–100 scale regardless
of which methods ran. If *no* core method succeeded, every feature gets a neutral PS of 50.

**Selection Frequency (0–100%)** — the fraction of the 5 core methods whose own top-`k` list included
this feature.

**Feature Quality (0–100)** — `0.50·VIF_score + 0.30·Missing_score + 0.20·Variance_score`, each a
step-function bucketing of the raw value (e.g. VIF ≤5→100, ≤10→80, ≤20→50, ≤30→20, else 0). Retained as a
displayed diagnostic and as the VIF gate's input, but excluded from Final Score by weight
(`FS_WEIGHT_FEATURE_QUALITY = 0.00` — kept in config only for import compatibility).

**Stability Score (0–100)** — bootstrap-resampling robustness check, independent of the 5 core methods
above (uses only 3, chosen for philosophical diversity — Target Correlation, Mutual Information, Elastic
Net — deliberately *not* Permutation Importance, since it tends to agree with Corr+MI and would inflate
apparent stability):
1. Run `FS_STABILITY_RUNS` (20) bootstrap iterations, each resampling `FS_STABILITY_SAMPLE_FRAC` (80%)
   of up to `FS_STABILITY_MAX_ROWS` (3,000) rows, with replacement.
2. In each run, all 3 methods select their own top-`k`; a feature needs ≥60% of the 3 methods' votes
   (`ceil(3 × 0.6) = 2`) to score any points that run, weighted by rank (`(k−rank)/k`).
3. Average each feature's per-run score over all runs → 0–100.

Any exception anywhere in this computation falls back to a flat 50.0 for every feature rather than
failing the whole pipeline.

**Final Score** (the number features are ranked by):
```
adjusted_freq = SelectionFreq × max(PredictiveStrength, 25) / 100      ← dampens a weak feature's
                                                                            frequency bonus so it can't
                                                                            rank high purely by appearing
                                                                            in many top-k lists
FinalScore = 0.30 × adjusted_freq + 0.50 × PredictiveStrength + 0.20 × StabilityScore
```
(`FS_WEIGHT_SELECTION_FREQ / FS_WEIGHT_PREDICTIVE_STRENGTH / FS_WEIGHT_STABILITY` in
`config/settings.py`.)

An informational-only **Average Rank** is also computed (mean rank position across all successful
methods, 1 = always top) — shown to users but never fed into FinalScore.

### 2.4 Multicollinearity de-duplication

After the initial consensus ranking, `_dedup_multicollinear()` runs a second pass: for every pair of
Recommended/Highly-Recommended features whose X–X Pearson `|r|` exceeds the configured
`corr_threshold` (default 0.85), it keeps the one with the higher FinalScore and downgrades the other to
**"Consider"**, stamping a `MulticollinearWith` note. Pairs are resolved greedily from the highest `|r|`
down, so the most redundant pairs get resolved first.

### 2.5 Recommendation buckets

`_assign_recommendation()` sorts every feature into one of 4 buckets using FinalScore, Predictive
Strength, VIF, and raw correlation — thresholds in `config/settings.py` (`FS_HIGHLY_REC_*`,
`FS_RECOMMENDED_*`, `FS_CONSIDER_MIN_FINAL`, `FS_WEAK_MAX_PRED_STRENGTH`):

1. **Weak Feature floor** — `|corr| < 0.05` and PS < 50, or PS below `FS_WEAK_MAX_PRED_STRENGTH` (30) →
   always "Weak Feature," regardless of FinalScore. (This floor is intentionally *not* scaled down for
   multi-Y datasets — a genuinely weak feature stays weak.)
2. **Highly Recommended** — FinalScore ≥ 70, PS ≥ 65 (scaled, see below), **and** VIF < 10.
3. **Recommended** — FinalScore ≥ 50, PS ≥ 45 (scaled).
4. **Consider** — FinalScore ≥ 35.
5. Otherwise → **Weak Feature**.

For multi-Y datasets, the PS thresholds for buckets 2–3 scale down gently (`FS_MULTI_Y_PS_SCALE = 0.08`
per extra target, capped at 4 extra targets) — a feature only needs to be moderately predictive of *each*
of several targets, not exceptionally predictive of every one.

### 2.6 Per-target vs. combined mode

- **Combined** (`run_auto_feature_selection`) — all Y columns scored together in one pass; each method
  averages its score across targets. Simple, but a feature that's a specialist for one target among many
  can get averaged away.
- **Per-target** (`run_per_target_auto_selection`, **preferred for multi-Y**) — runs the entire pipeline
  above *independently* for each Y column, then aggregates:
  - **Coverage Ratio** replaces Selection Frequency: the fraction of targets that recommended the
    feature (Highly Recommended or Recommended).
  - **Predictive Strength** is the mean PS **only over the targets that actually recommended the
    feature** — targets that rejected it don't dilute its score for the targets that need it.
  - Feature Quality and Stability are computed once, globally, over the shared X/y.
  - The union of every target's Highly-Recommended/Recommended features becomes `union_features`;
    Consider-only features not already in that union become `optional_union`. A `feature_target_map`
    records which specific targets recommended each feature (surfaced in the UI).
  - Deduplication (§2.4) runs once on the aggregate, not once per target.

### 2.7 Process-Aware Feature Selection

An optional scoping pass (`feature_selection_service.py::run_feature_selection_job`, `process_aware`
flag) that restricts candidate X columns to those appearing **before** the target Y in the dataset's
original (upstream→downstream) column order — a proxy for "don't let a downstream tag predict an
upstream one," matching the plant's actual process-flow direction. It only changes which columns are
*eligible* before scoring starts; it never touches the scoring/ranking math itself. In per-target mode
each target gets its own restricted candidate list; in combined mode all targets share the columns
upstream of the earliest-positioned selected target.

### 2.8 Per-feature reasoning

`_generate_reasoning()` renders a markdown card per feature: a score-component table (Final/PS/FQ/
Stability/Selection-Frequency/Avg-Rank), a bullet list of ✅/🔵/⚠️/🔴 tagged observations (consensus level,
predictive strength, permutation-importance strength, mRMR redundancy, VIF, target correlation, quality,
stability), which methods selected vs. rejected it, and a closing "Business Interpretation" paragraph
tailored to its bucket (e.g. Highly Recommended features that pass mostly via model-based methods despite
weak linear correlation get a note that their signal is likely non-linear).

### 2.9 Final Apply

`FinalApply.tsx` takes the resolved feature set (recommended ∪ any manually toggled features from
`ManualVariableSelection.tsx`) and hands the X/Y column selection to a new **project** — the persisted
train/test split + fitted scalers Build Model actually trains against (§3.4).

---

## 3. Build Model

**Where this lives:** `src/training/{trainer,train_sklearn,train_lstm,train_kalman}.py` (the 4 trainer
functions) · `src/models/{architecture,wrappers}.py` (model classes) · `src/evaluation/metrics.py` ·
`src/persistence/model_store.py` · `backend/app/services/training_service.py` (dispatch + persistence
orchestration, background job) · `backend/app/services/project_service.py` (the train/test split
artifacts) · `TrainPage.tsx` / `algorithmFields.ts` (frontend).

### 3.1 The 6 algorithms

All 6 share one contract: `fit` on `StandardScaler`-scaled X and Y, `predict_scaled()` returns predictions
still in *scaled* space (the caller inverse-transforms with `scaler_y`), and every wrapper exposes a
`model_type` string — so the What-If engine, Experimentation & Model Selection, and Predict can treat any
of them identically without knowing whether the underlying framework is PyTorch or sklearn.

#### DAE — Denoising Autoencoder (`IndustrialDAE`, PyTorch)

A **multi-task** network with one shared latent code feeding two heads:

```
Encoder   : input_dim → 128 → 64 → latent_dim         (BatchNorm+ReLU+Dropout after 1st layer)
Decoder   : latent_dim → 64 → 128 → input_dim          (reconstructs all sensor features)
Predictor : latent_dim → 32 → 16 → output_dim           (predicts the target KPI(s) from the same code)
```
(hidden sizes are `ENCODER_HIDDEN_1/2`, `DECODER_HIDDEN_1/2`, `PREDICTOR_HIDDEN_1/2` in
`config/settings.py` — 128/64/64/128/32/16 by default.)

**Training objective:** `total_loss = MSE(reconstruction) + weight_to_pred × Huber(prediction)`. The
denoising step (`_apply_masking()`) randomly zeroes a `masking_ratio` fraction of each training sample's
features *before* the forward pass — the network must reconstruct the clean input from a corrupted
version, which forces the encoder to learn a latent representation robust to missing/noisy sensor
readings (a very real industrial condition), rather than a code that only works on the exact input it
saw. Validation uses clean (unmasked) data.

**Training loop details:**
- Adam optimizer, `ReduceLROnPlateau` scheduler (halves LR after `lr_patience` epochs with no
  improvement in validation prediction loss).
- Best-checkpoint tracking: the model state with the lowest validation prediction loss is snapshotted
  every epoch and restored at the end, regardless of where training actually stops.
- **Patience early stopping** (applies in both modes): stop if val-pred-loss hasn't improved for
  `patience` epochs.
- **Auto-Train mode**: instead of a fixed epoch count, trains up to `AUTO_TRAIN_MAX_EPOCHS` (1000),
  checking every 10 epochs whether `avg_R² > AUTO_TRAIN_TARGET_R2` (0.80) **and** `avg_MAE ≤ best_MAE_so_
  far` — stopping the moment both hold.

#### Random Forest / XGBoost / LightGBM (tree ensembles, `train_sklearn.py`)

All three are wrapped for multi-output regression: `RandomForestRegressor` supports multi-output
natively; `XGBRegressor`/`LGBMRegressor` are wrapped in `sklearn.multioutput.MultiOutputRegressor` (one
independent model fit per target column). Random Forest squeezes single-output `y` to 1-D before fitting
(sklearn convention) and the prediction is reshaped back to 2-D afterward so the scaler's
`inverse_transform` always receives a consistent shape.

Key hyperparameters exposed (`ALGO_FIELDS`/`ALGO_DEFAULTS` in `algorithmFields.ts`):
- **Random Forest**: `n_estimators` (300), `max_depth` (0 = unlimited/`None`), `min_samples_split` (2),
  `max_features` (`sqrt`/`log2`/`None`).
- **XGBoost**: `n_estimators` (300), `max_depth` (6), `learning_rate` (0.1), `subsample` (0.8),
  `colsample_bytree` (0.8), `eval_metric="rmse"` fixed.
- **LightGBM**: `n_estimators` (300), `max_depth` (6), `learning_rate` (0.05), `num_leaves` (31),
  `subsample` (0.8).

#### LSTM (`LSTMPredictor`, PyTorch, `train_lstm.py`)

A sequence-to-value LSTM (`input_size → hidden_size` recurrent layers → a small `hidden_size→32→
output_size` head reading only the **last** timestep's hidden state). Because the pipeline doesn't
guarantee chronologically-ordered rows for every project, each flat feature row is **tiled**
`window_size` times into a synthetic constant-valued sequence (`np.stack([X]*window_size, axis=1)`) — a
"steady-state" assumption that keeps `predict_scaled(X)` working on any `(N, F)` array regardless of
whether temporal order is meaningful for that dataset. Trained with Adam + `ReduceLROnPlateau` + best-
checkpoint + patience early stopping, same shape as the DAE loop, using `HuberLoss` for the (single)
prediction objective (no reconstruction term — LSTM has no decoder).

Hyperparameters: `hidden_size` (64), `n_layers` (2), `window_size` (1), `dropout_rate` (0.2), `epochs`
(100), `lr` (0.001), `batch_size` (64), `patience` (20).

#### Kalman Filter (`train_kalman.py`)

The only algorithm that does genuine **state-space system identification** rather than curve-fitting:
1. **Subspace identification** — `nfoursid.NFourSID` builds Hankel matrices over *consecutive* time steps
   of the (scaled) training rows and recovers a discrete linear state-space model `(A, B, C, D)` via
   `subspace_identification()` → `system_identification(rank=...)`. This is why a Kalman-Filter project
   **must** come from a Sequential Split (§3.2) — Hankel matrices are meaningless over shuffled rows.
2. **One independent NFourSID/Kalman pair per target column** — mirrors how the legacy reference script
   (`Scripts/Model_development_and_static_whatif_testing_updated.py`) repeats the same identification
   block once per predicted parameter.
3. **Prediction** steps an `nfoursid.kalman.Kalman` filter row-by-row over the input sequence with
   `y=None` (no measurement update — a pure a-priori projection from the identified dynamics), reading
   back the `"filtered"` output column. `process_noise`/`measurement_noise` shape the filter's noise
   covariance block matrix (top-left block = measurement noise, bottom-right = process noise).

Hyperparameters: `process_noise` (Q, 1e-4), `measurement_noise` (R, 1e-2), `num_block_rows` (NFourSID
Hankel depth, 10), `rank` (state-space order, 2).

Wrapped in the same `SklearnWrapper` used by the tree ensembles (`model_type="Kalman Filter"`) — nothing
downstream needs to know it isn't a plain sklearn estimator.

### 3.2 Train/test split & scaling (`src/data/preprocessing.py::split_and_scale`)

Two split strategies, selected per project:
- **Sequential** — first `(1 − test_size)` fraction of rows → train, the remainder → test, **no
  shuffling**. Required in spirit for Kalman Filter (state-space identification assumes consecutive time
  steps) — training is no longer hard-blocked on this, but choosing Random/Stratified for a Kalman
  project is a real accuracy tradeoff the user opts into (`flow.md` §4b).
- **Random / Stratified** — `sklearn.train_test_split`, optionally stratified by quantile-binning the
  first Y column into `stratify_bins` equal-frequency bins (`pd.qcut`) so the test set's target
  distribution mirrors the train set's; falls back to a plain random split if binning fails.

Two independent `StandardScaler`s (`scaler_x`, `scaler_y`) are fit **only on the training partition** and
used to transform both train and test — the standard "no test-set leakage into scaling" rule. Both
scalers are persisted alongside the model (§3.4) since every prediction path (What-If's soft-sensor
dispatch, Build Model's evaluation, Predict) needs to scale inputs and inverse-scale outputs identically
to training.

### 3.3 Evaluation metrics (`src/evaluation/metrics.py`)

Per target column: **RMSE**, **MAE**, **R² Score**, **MAPE (%)** (mean absolute percentage error, computed
only over rows where the actual value is non-zero, else 0). `grade_r2()` buckets R² into a traffic-light
label using `config/settings.py`'s `R2_EXCELLENT` (0.85, 🟢) / `R2_GOOD` (0.75, 🟡) / else 🔴 "Needs
Improvement."

`training_service.py::_finish()` computes this **twice** — once on the held-out test set, once on the
training set itself — so a large train/test gap (overfitting) is visible in the experiment table rather
than only ever showing one optimistic number.

### 3.4 Persistence: what "Build Model" actually saves

On completion, every algorithm's result is persisted the same way regardless of framework
(`src/persistence/model_store.py::save_model_to_disk`), to
`saved_models/<case_id>/<model_name>/` (flat `saved_models/<model_name>/` for the `"default"` case):

| File | Contents |
|---|---|
| `model.pth` (DAE/LSTM) or `model.pkl` (RF/XGBoost/LightGBM/Kalman) | Weights / fitted estimator |
| `scaler_x.pkl`, `scaler_y.pkl` | The fitted `StandardScaler`s from the originating project |
| `columns.pkl` | `{x_cols, y_cols}` — which tags this model actually consumes/predicts |
| `metadata.pkl` | Name, saved-at timestamp, `input_dim`/`output_dim`, `model_type` |

Alongside disk persistence, `src/data/database.py::save_model_to_registry()` writes a row to
`dashboard.db`'s `model_registry` table (name, algorithm, dataset, x/y cols, avg R²/RMSE/MAE for both
train and test, file path, `case_id`) — this is what Experimentation & Model Selection's table reads.
Registry-write and MLflow-logging failures are both swallowed (best-effort, never block a successful
training run) — `mlflow.log_params`/`log_metrics`/per-epoch curves (DAE/LSTM only) are logged to
`MLFLOW_TRACKING_URI`/`MLFLOW_EXPERIMENT_NAME` (`config/settings.py`) purely for external
experiment-tracking visibility; nothing in the app reads MLflow back.

**A model is never versioned or deleted implicitly** — every training run creates a brand-new
`model_name` (`{algorithm}_{project_id}_{timestamp}`) and a brand-new experiment row; the previous one
stays exactly as it was until explicitly removed via Experimentation & Model Selection's 🗑️ Delete
(`ARCHITECTURE.md` §4, `flow.md` §4b/§8).

### 3.5 From a saved experiment to a live prediction

A saved experiment does nothing on its own until marked **"Selected for What-If Analysis"** for its
Predicted Parameter (§1.4). From then on, `src/whatif/engine.py::predict_and_update_with_soft_sensor_
model()` loads it via `model_store.load_model_from_disk()`, validates every one of its `x_cols` is present
in the current scenario row, scales with the saved `scaler_x`, calls `predict_scaled()`, and inverse-
scales with the saved `scaler_y` — the exact same scale/predict/inverse-scale contract every algorithm's
wrapper honors identically. See `flow.md` §6 for the full per-parameter dispatch order (plugin → Selected
experiment → dedicated Kalman filter → baseline).

---

## 4. Where the tunable constants live

Every threshold/weight/hyperparameter default referenced above is a named constant in
`config/settings.py` — check there before assuming a number is hardcoded elsewhere:

- **Feature selection**: `FS_WEIGHT_*` (Final Score weights), `FS_PS_*_WEIGHT` (Predictive Strength
  sub-weights), `FS_HIGHLY_REC_*` / `FS_RECOMMENDED_*` / `FS_CONSIDER_MIN_FINAL` /
  `FS_WEAK_MAX_PRED_STRENGTH` (recommendation thresholds), `FS_MULTI_Y_PS_SCALE`,
  `FS_STABILITY_RUNS` / `FS_STABILITY_SAMPLE_FRAC` / `FS_STABILITY_MAX_ROWS`.
- **DAE architecture**: `ENCODER_HIDDEN_1/2`, `DECODER_HIDDEN_1/2`, `PREDICTOR_HIDDEN_1/2`.
- **DAE auto-train**: `AUTO_TRAIN_MAX_EPOCHS`, `AUTO_TRAIN_TARGET_R2`.
- **Evaluation grading**: `R2_EXCELLENT`, `R2_GOOD`.
- **Split defaults**: `TEST_SIZE`, `RANDOM_STATE` (`src/data/preprocessing.py`'s import).
- Per-algorithm hyperparameter *UI* defaults (the ones a user actually adjusts in Build Model) live in
  the frontend's `frontend/src/pages/Train/algorithmFields.ts` (`ALGO_DEFAULTS`), mirrored 1:1 in intent
  from the legacy Streamlit `src/ui/pages/train.py` widgets.
