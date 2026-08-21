"""
src/whatif/model_status.py
============================
A pure file-existence check over the required Kalman-model tags' 3 artifacts
each (kalman_filter_model_{tag}.pkl, scaler_X_{tag}.pkl, scaler_y_{tag}.pkl)
under Results/Model/.

The required tag list used to be a hardcoded 15-entry constant, ported
verbatim from the original single-plant Streamlit dashboard. That list
predates the generalized config schema and had drifted out of sync with it
(missing CHG_GAS_FLOW_TO_DRYER, which the current Config_file.xlsx does mark
as a Data model parameter and does have trained artifacts for). It's now
derived from the live "Model details" sheet instead: every predicted
parameter whose model type is data-driven (see
src/whatif/config_io.non_data_model_parameters, which the rewritten
src/whatif/engine.py also uses to decide what to Kalman-predict vs. hand to
the plant plug-in) is required.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd

from src.data.database import DEFAULT_CASE_ID, list_model_selections
from src.whatif import config_io


@dataclass
class ModelStatus:
    all_present: bool
    tags_ok: list[str]
    tags_missing: list[str]
    pkl_count: int


def _tag_artifacts(model_dir: str, tag: str) -> list[str]:
    return [
        os.path.join(model_dir, f"kalman_filter_model_{tag}.pkl"),
        os.path.join(model_dir, f"scaler_X_{tag}.pkl"),
        os.path.join(model_dir, f"scaler_y_{tag}.pkl"),
    ]


def required_kalman_tags(model_details_df: pd.DataFrame, case_id: str = DEFAULT_CASE_ID) -> list[str]:
    """Every 'Predicted parameter' whose model type is data-driven (blank
    defaults to data-driven) — i.e. every parameter src/whatif/engine.py will
    try to Kalman-predict rather than hand to the plant plug-in.

    A parameter with an Experiment-History-selected Soft Sensor model
    (src.data.database.whatif_model_selection, scoped to case_id) is
    excluded: engine.py tries that model first and only falls back to Kalman
    if it's missing, so a selected parameter no longer needs Kalman
    artifacts to be "ready"."""
    if model_details_df is None or model_details_df.empty or "Predicted parameter" not in model_details_df.columns:
        return []
    non_data = config_io.non_data_model_parameters(model_details_df)
    selected = set(list_model_selections(case_id))
    tags = model_details_df["Predicted parameter"].dropna().astype(str).str.strip()
    return [t for t in tags.unique() if t and t not in non_data and t not in selected]


def check_models_trained(model_dir: str, required_tags: list[str]) -> ModelStatus:
    tags = required_tags
    tags_ok: list[str] = []
    tags_missing: list[str] = []
    pkl_count = 0

    for tag in tags:
        artifacts = _tag_artifacts(model_dir, tag)
        present = [os.path.isfile(p) for p in artifacts]
        pkl_count += sum(present)
        if all(present):
            tags_ok.append(tag)
        else:
            tags_missing.append(tag)

    return ModelStatus(
        all_present=not tags_missing,
        tags_ok=tags_ok,
        tags_missing=tags_missing,
        pkl_count=pkl_count,
    )
