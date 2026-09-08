"""
config/settings.py
==================
Single source of truth for all constants, paths, and defaults used across
the Soft Sensor Prediction System.

No module at a lower layer (data, models, training, ui) should hard-code
any value that appears here.  All imports run top-down:
    config.settings  ←  src.*  ←  app.py
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------
DB_PATH: str = "dashboard.db"
MODEL_DIR: str = "saved_models"

os.makedirs(MODEL_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Experiment tracking (MLflow) — logs params/metrics/artifacts for every
# Soft Sensor training run (backend/app/services/training_service.py).
# Separate from DB_PATH's model_registry table: that's this app's own model
# list (Overview/Predict pages); MLflow tracking runs alongside it, not
# instead of it. Browse runs with `mlflow ui --backend-store-uri sqlite:///mlflow.db`.
# ---------------------------------------------------------------------------
MLFLOW_TRACKING_URI: str = "sqlite:///mlflow.db"
MLFLOW_EXPERIMENT_NAME: str = "soft-sensor-training"

# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------
TEST_SIZE: float = 0.2
RANDOM_STATE: int = 42

# ---------------------------------------------------------------------------
# Model architecture — encoder/decoder/predictor hidden sizes
# ---------------------------------------------------------------------------
ENCODER_HIDDEN_1: int = 128
ENCODER_HIDDEN_2: int = 64
DECODER_HIDDEN_1: int = 64
DECODER_HIDDEN_2: int = 128
PREDICTOR_HIDDEN_1: int = 32
PREDICTOR_HIDDEN_2: int = 16

# ---------------------------------------------------------------------------
# Training defaults (reflected in the Streamlit widgets as initial values)
# ---------------------------------------------------------------------------
DEFAULT_LATENT_DIM: int = 5
DEFAULT_DROPOUT_RATE: float = 0.2
DEFAULT_MASKING_RATIO: float = 0.10
DEFAULT_EPOCHS: int = 150
DEFAULT_LR: float = 0.001
DEFAULT_WEIGHT_TO_PRED: float = 5.0
DEFAULT_BATCH_SIZE: int = 128

# Auto-train
AUTO_TRAIN_MAX_EPOCHS: int = 1000
AUTO_TRAIN_TARGET_R2: float = 0.80

# Early stopping & LR scheduling
DEFAULT_EARLY_STOP_PATIENCE: int = 20   # epochs without val improvement before stopping
DEFAULT_LR_PATIENCE: int = 10           # epochs without improvement before LR is halved

# ---------------------------------------------------------------------------
# What-If simulator
# ---------------------------------------------------------------------------
MAX_SWEEP_POINTS: int = 500
TREND_EPSILON: float = 1e-5

# ---------------------------------------------------------------------------
# What-If Analysis module (src/whatif/*) — file-based config/model locations.
# Kept separate from MODEL_DIR/DB_PATH: this is a different, Excel/pickle-
# based persistence world shared with the standalone Scripts/ what-if app,
# not the dashboard.db / saved_models world used elsewhere in this file.
# ---------------------------------------------------------------------------
WHATIF_DATA_DIR: str = "Data"
WHATIF_RESULTS_DIR: str = "Results"
WHATIF_MODEL_DIR: str = "Results/Model"
WHATIF_CONFIG_FILE: str = "Data/Config_file.xlsx"
WHATIF_TRAINING_WORKBOOK: str = "Data/DMC_Screen_tags_data.xlsx"
WHATIF_HISTORIAN_FILE: str = "Results/Raw_data_plus_simulated_data.xlsx"

# ---------------------------------------------------------------------------
# Feature Selection Scoring
# ---------------------------------------------------------------------------
# Component weights (sum = 1.0)
# FQ removed — missing/variance handled upstream in preprocessing; VIF enforced via gate.
FS_WEIGHT_SELECTION_FREQ:       float = 0.30
FS_WEIGHT_PREDICTIVE_STRENGTH:  float = 0.50
FS_WEIGHT_STABILITY:            float = 0.20

# Predictive Strength sub-weights — 5 active scoring methods (must sum to 1.0)
# Permutation Importance: robust model-agnostic signal, highest weight.
# Mutual Information: captures non-linear feature-target dependencies.
# Target Correlation: fast, reliable linear measure.
# mRMR: rewards relevance while penalising redundancy with already-selected features.
# Elastic Net: regularisation-based coefficient, sparse and stable.
FS_PS_CORR_WEIGHT:  float = 0.20   # Target Correlation
FS_PS_MI_WEIGHT:    float = 0.25   # Mutual Information
FS_PS_PERM_WEIGHT:  float = 0.30   # Permutation Importance
FS_PS_MRMR_WEIGHT:  float = 0.15   # mRMR
FS_PS_EN_WEIGHT:    float = 0.10   # Elastic Net

# Multi-Y threshold scaling: each extra Y target softens PS recommendation
# thresholds by this fraction (capped at 4 extra targets = 32% max softening).
FS_MULTI_Y_PS_SCALE: float = 0.08

# Recommendation thresholds
# Lowered by ~10-12 pts to compensate for FQ removal from FinalScore (~15pt average contribution).
# FQ quality gates removed from logic; VIF still enforced as a hard gate for Highly Recommended.
FS_HIGHLY_REC_MIN_FINAL:          float = 70.0
FS_HIGHLY_REC_MIN_PRED_STRENGTH:  float = 65.0
FS_HIGHLY_REC_MAX_VIF:            float = 10.0

FS_RECOMMENDED_MIN_FINAL:         float = 50.0
FS_RECOMMENDED_MIN_PRED_STRENGTH: float = 45.0

FS_CONSIDER_MIN_FINAL:            float = 35.0

FS_WEAK_MAX_PRED_STRENGTH:        float = 30.0

# Stability bootstrap
FS_STABILITY_RUNS:       int   = 20
FS_STABILITY_SAMPLE_FRAC: float = 0.80
FS_STABILITY_MAX_ROWS:   int   = 3000

# ---------------------------------------------------------------------------
# Evaluation / grading thresholds
# ---------------------------------------------------------------------------
R2_EXCELLENT: float = 0.85
R2_GOOD: float = 0.75
