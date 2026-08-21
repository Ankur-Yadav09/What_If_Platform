"""
backend/app/services/overview_service.py
============================================
GET /api/overview is pure aggregation (dataset + saved-model inventories) —
no per-model computation, no state. Both train-set and test-set metrics are
read straight from the registry (captured once at training time in
training_service.py::_finish()) — there is no live recompute here anymore.
An earlier version of this file had a GET /models/{name}/performance
endpoint that recomputed R² live over the full stored dataset (train rows
the model had already seen + test rows); that blended, leakage-inflated
number was retired in favor of the honest train_r2/avg_r2 pair already
captured at training time.
"""
from __future__ import annotations

from src.data.database import (
    DEFAULT_CASE_ID,
    clear_model_selection as _clear_model_selection,
    delete_model_from_registry,
    list_datasets_from_db,
    list_model_selections,
    list_models_from_registry,
    set_model_selection as _set_model_selection,
)
from src.persistence.model_store import (
    delete_model_from_disk,
    list_saved_models as list_saved_models_on_disk,
)

from backend.app.schemas.datasets import DatasetSummary
from backend.app.schemas.overview import OverviewResponse, SavedModelSummary


def get_overview(case_id: str = DEFAULT_CASE_ID) -> OverviewResponse:
    datasets = [
        DatasetSummary(name=r[0], uploaded_at=r[1], rows=r[2], cols=r[3])
        for r in list_datasets_from_db()  # global across cases -- unchanged
    ]

    registry_by_name = {
        r["model_name"]: r for r in list_models_from_registry(case_id)
    }
    selections = list_model_selections(case_id)  # {parameter: model_name}

    saved_models = []
    for m in list_saved_models_on_disk(case_id):
        reg = registry_by_name.get(m["name"])
        y_cols = m.get("y_cols", [])
        saved_models.append(
            SavedModelSummary(
                name=m["name"],
                saved_at=m["saved_at"],
                input_dim=m["input_dim"],
                output_dim=m["output_dim"],
                algorithm=(reg["algorithm"] if reg else m.get("model_type")),
                dataset_name=reg["dataset_name"] if reg else None,
                avg_r2=reg["avg_r2"] if reg else None,
                avg_rmse=reg["avg_rmse"] if reg else None,
                avg_mae=reg["avg_mae"] if reg else None,
                train_r2=reg["train_r2"] if reg else None,
                train_rmse=reg["train_rmse"] if reg else None,
                train_mae=reg["train_mae"] if reg else None,
                x_cols=m.get("x_cols", []),
                y_cols=y_cols,
                selected_for=[p for p in y_cols if selections.get(p) == m["name"]],
            )
        )

    return OverviewResponse(datasets=datasets, saved_models=saved_models)


def select_model_for_parameter(
    parameter: str, model_name: str, case_id: str = DEFAULT_CASE_ID
) -> OverviewResponse:
    """Mark model_name as the active Soft Sensor model for parameter — the
    "Use for What-If Analysis" action on Experiment History. Validates the
    model actually exists on disk and predicts that parameter, so a stale or
    mismatched (parameter, model_name) pair can't silently get wired in."""
    models_on_disk = {m["name"]: m for m in list_saved_models_on_disk(case_id)}
    model = models_on_disk.get(model_name)
    if model is None:
        raise ValueError(f"No saved model named '{model_name}'.")
    if parameter not in model.get("y_cols", []):
        raise ValueError(f"Model '{model_name}' does not predict parameter '{parameter}'.")

    _set_model_selection(parameter, model_name, case_id)
    return get_overview(case_id)


def clear_model_selection(parameter: str, case_id: str = DEFAULT_CASE_ID) -> OverviewResponse:
    """Un-pick the selected experiment for parameter, reverting it to the
    dedicated Kalman-filter fallback in src/whatif/engine.py."""
    _clear_model_selection(parameter, case_id)
    return get_overview(case_id)


def delete_model(model_name: str, case_id: str = DEFAULT_CASE_ID) -> OverviewResponse:
    """Permanently remove a trained experiment — its saved_models/ files and
    its model_registry row. Also clears any What-If "Selected for What-If
    Analysis" pointer(s) at model_name, for every parameter it was selected
    for, so predict_and_update_with_soft_sensor_model() never looks up a
    model_name that no longer exists on disk (it would otherwise surface as
    an unhandled FileNotFoundError rather than the graceful LookupError ->
    Kalman-fallback path engine.py's dispatch already handles)."""
    registry_row = next(
        (r for r in list_models_from_registry(case_id) if r["model_name"] == model_name), None
    )
    if registry_row is not None:
        delete_model_from_registry(registry_row["id"])

    for parameter, selected_name in list_model_selections(case_id).items():
        if selected_name == model_name:
            _clear_model_selection(parameter, case_id)

    delete_model_from_disk(model_name, case_id)
    return get_overview(case_id)
