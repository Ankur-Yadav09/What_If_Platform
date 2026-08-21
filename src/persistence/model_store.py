"""
src/persistence/model_store.py
================================
Model persistence utilities — save, load, and list all supported model types.

Supported types
---------------
DAE            — PyTorch IndustrialDAE  (model.pth)
LSTM           — PyTorch LSTMPredictor  (model.pth)
Random Forest  — sklearn               (model.pkl)
XGBoost        — xgboost               (model.pkl)
LightGBM       — lightgbm              (model.pkl)
Kalman Filter  — recursive linear filter (model.pkl)

Directory layout
----------------
saved_models/<case_id>/<model_name>/    (flat saved_models/<model_name>/ for the default case)
    model.pth | model.pkl   model weights / fitted estimator
    scaler_x.pkl            fitted StandardScaler for X
    scaler_y.pkl            fitted StandardScaler for Y
    columns.pkl             {'x_cols': [...], 'y_cols': [...]}
    metadata.pkl            info dict including model_type

Case isolation mirrors src/whatif/paths.py's _case_dir(): DEFAULT_CASE_ID
resolves to the original flat saved_models/<model_name>/ layout unchanged,
so every model saved before per-case isolation existed keeps working.

Public API
----------
save_model_to_disk(wrapper, scaler_x, scaler_y, x_cols, y_cols, model_name, case_id=DEFAULT_CASE_ID)
load_model_from_disk(model_name, case_id=DEFAULT_CASE_ID)  → (wrapper, scaler_x, scaler_y, x_cols, y_cols)
list_saved_models(case_id=DEFAULT_CASE_ID)                 → list[dict]
delete_model_from_disk(model_name, case_id=DEFAULT_CASE_ID)
"""
from __future__ import annotations

import datetime
import os
import pickle
import shutil
from typing import List, Tuple

import torch

from config.settings import MODEL_DIR
from src.data.database import DEFAULT_CASE_ID
from src.models.architecture import IndustrialDAE
from src.models.wrappers import DAEWrapper, LSTMPredictor, LSTMWrapper, SklearnWrapper

_SKLEARN_TYPES = {"Random Forest", "XGBoost", "LightGBM", "Kalman Filter"}


def case_model_dir(case_id: str) -> str:
    """The saved_models/ folder scoped to case_id (flat MODEL_DIR for the
    default case) -- also used by callers outside this module (e.g.
    training_service.py) that need to record a model_registry file_path
    consistent with where save_model_to_disk() actually wrote it."""
    if case_id == DEFAULT_CASE_ID:
        return MODEL_DIR
    return os.path.join(MODEL_DIR, case_id)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_model_to_disk(
    wrapper,
    scaler_x,
    scaler_y,
    x_cols: List[str],
    y_cols: List[str],
    model_name: str,
    case_id: str = DEFAULT_CASE_ID,
) -> None:
    """
    Persist any supported model wrapper with its scalers and column config.

    Idempotent: a second call with the same model_name silently overwrites.
    """
    save_path = os.path.join(case_model_dir(case_id), model_name)
    os.makedirs(save_path, exist_ok=True)

    model_type = wrapper.model_type

    # ---- Model weights / estimator ----
    if model_type == "DAE":
        dae = wrapper.model
        torch.save(
            {
                "state_dict": dae.state_dict(),
                "input_dim":  len(x_cols),
                "latent_dim": dae.encoder[-1].out_features,
                "output_dim": dae.predictor[-1].out_features,
            },
            os.path.join(save_path, "model.pth"),
        )

    elif model_type == "LSTM":
        lstm = wrapper.model
        torch.save(
            {
                "state_dict":  lstm.state_dict(),
                "input_size":  lstm.lstm.input_size,
                "hidden_size": lstm.hidden_size,
                "n_layers":    lstm.n_layers,
                "output_size": lstm.head[-1].out_features,
                "dropout":     lstm.lstm.dropout,
                "window_size": wrapper.window_size,
            },
            os.path.join(save_path, "model.pth"),
        )

    elif model_type in _SKLEARN_TYPES:
        with open(os.path.join(save_path, "model.pkl"), "wb") as fh:
            pickle.dump(wrapper.model, fh)

    else:
        raise ValueError(f"Unknown model_type for saving: {model_type!r}")

    # ---- Scalers ----
    for fname, obj in [("scaler_x.pkl", scaler_x), ("scaler_y.pkl", scaler_y)]:
        with open(os.path.join(save_path, fname), "wb") as fh:
            pickle.dump(obj, fh)

    # ---- Column config ----
    with open(os.path.join(save_path, "columns.pkl"), "wb") as fh:
        pickle.dump({"x_cols": x_cols, "y_cols": y_cols}, fh)

    # ---- Metadata ----
    meta = {
        "name":       model_name,
        "saved_at":   datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_dim":  len(x_cols),
        "output_dim": len(y_cols),
        "model_type": model_type,
        "x_cols":     x_cols,
        "y_cols":     y_cols,
    }
    with open(os.path.join(save_path, "metadata.pkl"), "wb") as fh:
        pickle.dump(meta, fh)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_model_from_disk(
    model_name: str,
    case_id: str = DEFAULT_CASE_ID,
) -> Tuple[object, object, object, List[str], List[str]]:
    """
    Reconstruct a saved model from disk.

    Returns
    -------
    (wrapper, scaler_x, scaler_y, x_cols, y_cols)

    where wrapper is one of DAEWrapper | SklearnWrapper | LSTMWrapper.
    """
    load_path = os.path.join(case_model_dir(case_id), model_name)

    with open(os.path.join(load_path, "metadata.pkl"), "rb") as fh:
        meta = pickle.load(fh)

    # Backward-compat: models saved before multi-model support are DAE
    model_type = meta.get("model_type", "DAE")

    if model_type == "DAE":
        ckpt = torch.load(
            os.path.join(load_path, "model.pth"), weights_only=False
        )
        dae = IndustrialDAE(
            input_dim=ckpt["input_dim"],
            latent_dim=ckpt["latent_dim"],
            output_dim=ckpt["output_dim"],
        )
        dae.load_state_dict(ckpt["state_dict"])
        dae.eval()
        wrapper = DAEWrapper(dae)

    elif model_type == "LSTM":
        ckpt = torch.load(
            os.path.join(load_path, "model.pth"), weights_only=False
        )
        lstm = LSTMPredictor(
            input_size=ckpt["input_size"],
            hidden_size=ckpt["hidden_size"],
            n_layers=ckpt["n_layers"],
            output_size=ckpt["output_size"],
            dropout=ckpt["dropout"],
        )
        lstm.load_state_dict(ckpt["state_dict"])
        lstm.eval()
        wrapper = LSTMWrapper(lstm, window_size=ckpt["window_size"])

    elif model_type in _SKLEARN_TYPES:
        with open(os.path.join(load_path, "model.pkl"), "rb") as fh:
            sk_model = pickle.load(fh)
        wrapper = SklearnWrapper(sk_model, model_type)

    else:
        raise ValueError(f"Unknown model_type in saved metadata: {model_type!r}")

    with open(os.path.join(load_path, "scaler_x.pkl"), "rb") as fh:
        scaler_x = pickle.load(fh)
    with open(os.path.join(load_path, "scaler_y.pkl"), "rb") as fh:
        scaler_y = pickle.load(fh)
    with open(os.path.join(load_path, "columns.pkl"), "rb") as fh:
        cols = pickle.load(fh)

    return wrapper, scaler_x, scaler_y, cols["x_cols"], cols["y_cols"]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_model_from_disk(model_name: str, case_id: str = DEFAULT_CASE_ID) -> None:
    """Remove a saved model's whole directory. A no-op if it's already gone,
    matching save_model_to_disk's own idempotent spirit."""
    shutil.rmtree(os.path.join(case_model_dir(case_id), model_name), ignore_errors=True)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def list_saved_models(case_id: str = DEFAULT_CASE_ID) -> List[dict]:
    """Return metadata dicts for every model saved to disk within case_id."""
    models: List[dict] = []
    case_dir = case_model_dir(case_id)
    if not os.path.exists(case_dir):
        return models

    for name in os.listdir(case_dir):
        meta_path = os.path.join(case_dir, name, "metadata.pkl")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "rb") as fh:
                    models.append(pickle.load(fh))
            except Exception:
                pass

    return models
