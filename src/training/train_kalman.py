"""
src/training/train_kalman.py
==============================
Training function for the Kalman Filter soft sensor model.

Uses genuine state-space system identification: `nfoursid.NFourSID` performs
subspace identification (via Hankel matrices over consecutive time steps) to
recover a state-space model (A, B, C, D), then predictions are made by
stepping an `nfoursid.kalman.Kalman` filter row-by-row over the input
sequence. This mirrors the approach already used by the What-If module
(`Scripts/Model_development_and_static_whatif_testing.py` /
`src/whatif/engine.py`), applied here to the Train page's generic
project/algorithm pipeline.

Because subspace identification depends on temporally consecutive rows
(Hankel matrices span consecutive time steps), the calling project MUST have
been built with a sequential (non-shuffled) train/test split — enforced in
backend/app/services/training_service.py before this function is ever
called, not here.

Multi-Y is supported by fitting one independent NFourSID/Kalman pair per
output column (mirroring how the reference script itself repeats the same
block once per predicted parameter), all driven by the same input rows.

Public API
----------
train_kalman_model(X_train, y_train_scaled,
                    X_test, y_test_scaled, y_test_raw, y_cols, scaler_y,
                    **hparams)
    -> (SklearnWrapper, loss_history_dict)
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from nfoursid.kalman import Kalman
from nfoursid.nfoursid import NFourSID
from sklearn.metrics import mean_absolute_error, r2_score

from src.models.wrappers import SklearnWrapper


class _KalmanFilterRegressor:
    """
    State-space regressor identified via NFourSID subspace identification,
    predicted via a stepped Kalman filter.

    Exposes the same ``fit(X, y)`` / ``predict(X)`` surface as an sklearn
    estimator so it can be wrapped with the existing ``SklearnWrapper`` used
    by the tree-ensemble models — nothing downstream (save/load, MLflow,
    Predict page) needs to know this isn't a plain sklearn regressor.
    """

    def __init__(
        self,
        process_noise: float = 1e-4,
        measurement_noise: float = 1e-2,
        initial_covariance: float = 1.0,
        num_block_rows: int = 10,
        rank: int = 2,
        random_state: int = 42,
    ) -> None:
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.initial_covariance = initial_covariance
        self.num_block_rows = num_block_rows
        self.rank = rank
        self.random_state = random_state  # accepted, unused: NFourSID is a deterministic linear-algebra fit

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_KalmanFilterRegressor":
        X = np.atleast_2d(np.asarray(X, dtype=float))
        y = np.asarray(y, dtype=float)
        if y.ndim == 1:
            y = y.reshape(-1, 1)

        x_names = [f"x{i}" for i in range(X.shape[1])]

        # One NFourSID -> state-space -> (implicit) Kalman pair per target
        # column, exactly mirroring how the reference script repeats this
        # block once per predicted parameter.
        state_spaces = []
        for j in range(y.shape[1]):
            y_name = f"y{j}"
            train_df = pd.DataFrame(X, columns=x_names)
            train_df[y_name] = y[:, j]

            nfoursid = NFourSID(
                train_df,
                output_columns=[y_name],
                input_columns=x_names,
                num_block_rows=self.num_block_rows,
            )
            nfoursid.subspace_identification()
            state_space, _ = nfoursid.system_identification(rank=self.rank)
            state_spaces.append(state_space)

        self.state_spaces_ = state_spaces
        self.x_names_ = x_names
        self.n_outputs_ = y.shape[1]
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=float))
        preds = np.zeros((X.shape[0], self.n_outputs_))

        for j, state_space in enumerate(self.state_spaces_):
            y_dim, x_dim = state_space.y_dim, state_space.x_dim

            # noise_covariance is a (y_dim+x_dim, y_dim+x_dim) block matrix:
            # top-left y_dim x y_dim block = measurement noise, bottom-right
            # x_dim x x_dim block = process noise (see nfoursid.kalman.Kalman).
            noise_cov = np.eye(y_dim + x_dim)
            noise_cov[:y_dim, :y_dim] *= self.measurement_noise
            noise_cov[y_dim:, y_dim:] *= self.process_noise

            kalman = Kalman(state_space=state_space, noise_covariance=noise_cov)
            # Note: nfoursid.kalman.Kalman has no P0 hook — .step() always
            # falls back to a hardcoded np.eye(x_dim) for the first step's
            # predicted covariance (matching the reference code, which
            # doesn't seed P0 either). An earlier attempt to pre-seed
            # kalman.p_predicteds here corrupted to_dataframe(), which zips
            # several internally-tracked lists that must all stay the same
            # length as the number of .step() calls — self.initial_covariance
            # is accepted for API/schema compatibility but intentionally
            # unused for this algorithm.

            for i in range(X.shape[0]):
                kalman.step(y=None, u=X[i].reshape(-1, 1))

            results = kalman.to_dataframe()
            # nfoursid always labels state-space outputs with its own
            # canonical symbol (e.g. "$y_0$") regardless of the column name
            # passed into NFourSID(output_columns=...) — read it back from
            # the state space itself rather than guessing the format.
            y_label = state_space.y_column_names[0]
            preds[:, j] = results[(y_label, "filtered", "output")].values

        return preds


def train_kalman_model(
    X_train: np.ndarray,
    y_train_scaled: np.ndarray,
    X_test: np.ndarray,
    y_test_scaled: np.ndarray,
    y_test_raw,             # pd.DataFrame of unscaled test targets
    y_cols: List[str],
    scaler_y,               # fitted StandardScaler for Y
    **hparams,
) -> tuple:
    """
    Train a state-space (NFourSID + Kalman) model for multi-output soft
    sensor prediction.

    Parameters
    ----------
    X_train / X_test   : scaled numpy feature arrays (rows must be in
                          temporal order — see module docstring)
    y_train_scaled      : scaled numpy target array (N, output_dim)
    y_test_scaled        : scaled test targets
    y_test_raw           : unscaled test targets DataFrame
    y_cols               : ordered target column names
    scaler_y             : fitted StandardScaler
    **hparams            : process_noise, measurement_noise,
                            initial_covariance, num_block_rows, rank,
                            random_state

    Returns
    -------
    wrapper      : SklearnWrapper ready for inference
    loss_history : minimal dict matching the format used by the other
                   non-epoch-curve models (tree ensembles)
    """
    # ---- Normalise array shapes ----
    X_train        = np.atleast_2d(X_train)
    X_test         = np.atleast_2d(X_test)
    y_train_scaled = np.array(y_train_scaled)
    y_test_scaled  = np.array(y_test_scaled)
    if y_train_scaled.ndim == 1:
        y_train_scaled = y_train_scaled.reshape(-1, 1)
    if y_test_scaled.ndim == 1:
        y_test_scaled = y_test_scaled.reshape(-1, 1)

    # ---- Fit ----
    model = _KalmanFilterRegressor(**hparams)
    model.fit(X_train, y_train_scaled)

    # ---- Quick validation metrics ----
    pred_scaled = model.predict(X_test)
    pred_raw = scaler_y.inverse_transform(pred_scaled)

    r2_vals  = [r2_score(y_test_raw[c], pred_raw[:, i])  for i, c in enumerate(y_cols)]
    mae_vals = [mean_absolute_error(y_test_raw[c], pred_raw[:, i]) for i, c in enumerate(y_cols)]

    avg_r2  = float(np.mean(r2_vals))
    avg_mae = float(np.mean(mae_vals))

    # Minimal loss_history so train.py post-training code doesn't need branching
    loss_history: Dict = {
        "epoch_recon_losses": [],
        "epoch_pred_losses":  [],
        "val_recon_losses":   [],
        "val_pred_losses":    [],
        "actual_epochs":      None,  # no epoch concept for a one-shot state-space fit
        "early_stopped":      False,
        "final_r2":           avg_r2,
        "final_mae":          avg_mae,
    }

    return SklearnWrapper(model, "Kalman Filter"), loss_history
