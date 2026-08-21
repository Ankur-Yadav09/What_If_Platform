"""
src/whatif/engine.py
======================
Ported, Streamlit-free version of Scripts/whatif_runner_updated.py's generic,
config-driven whatif_analysis() pipeline: the prediction order comes from a
dependency graph built off the "Model details" sheet (topologically sorted),
constraint rules ("bump linked parameter to max", "abort if exceeds") come
entirely from the "Constraints" sheet's Linked Parameter/Action columns, and
any physics that can't be reduced to a Kalman model lives in a plant plug-in
(src/whatif/plants/) rather than hardcoded here.

This replaces this repo's previous engine.py, which mirrored an older,
single-plant, hardcoded version of the reference script: a fixed sequence of
~20 named prediction steps with 3 copy-pasted "bump to max" blocks and one
hardcoded abort check, all specific to YANPET_OLF1. That version also had a
latent bug the rewrite fixes: it extracted a predicted parameter's Kalman
input columns *positionally* (`iloc[:, 1:]`), which breaks the moment "Model
details" gains Section/model-type columns between "Predicted parameter" and
"Input parameter_1" (exactly what the new config schema does) — a literal
"CGC"/"Data model" string would land in the Kalman feature vector. This
version uses src/whatif/config_io.input_param_cols() (name-based) instead.

Differences from Scripts/whatif_runner_updated.py, all deliberate (matching
this repo's existing conventions, not the reference script's):
  - No module-level import-time side effect (the reference calls
    load_process_data() at import time); the historian is loaded once by the
    caller (backend/app/services/what_if_service.py) and passed in.
  - Config (Model details, Constraints, Section Order, ...) is loaded once by
    the caller via src/whatif/config_io.py and passed in as a WhatIfConfig,
    instead of being re-read from Config_file.xlsx on every call.
  - The plant plug-in is passed in (or auto-loaded once via
    src/whatif/plants.load_plant_formulas() if omitted) instead of being
    re-imported from disk on every call.
  - No multi-plant PLANT_NAME/path-resolution machinery — single plant,
    paths are parameterized (model_dir) instead.
  - section_order is derived from config.section_order_list() rather than
    being a separate parameter — the config workbook is the single source of
    truth for it.
  - Returns a plain WhatIfResult dataclass instead of a pandas Styler —
    coloring is a frontend concern.
  - The "Actual_vs_estimated what if.xlsx" disk write is strictly opt-in via
    write_actual_vs_estimated_xlsx (default False), and when enabled writes to
    a per-request filename rather than the reference's fixed name, to avoid
    concurrent-request overwrites.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from dataclasses import dataclass
from types import ModuleType

import joblib
import numpy as np
import pandas as pd

from src.data.database import DEFAULT_CASE_ID, list_model_selections
from src.persistence.model_store import load_model_from_disk
from src.whatif import config_io, formula_eval, plants
from src.whatif.config_io import WhatIfConfig

logger = logging.getLogger(__name__)


@dataclass
class WhatIfResult:
    actual: dict
    estimated: dict
    constraint_hit: bool
    constraint_message: str | None = None


# ---------------------------------------------------------------------------
# Generic building blocks (fully data-driven, no plant-specific names)
# ---------------------------------------------------------------------------

def build_dependency_graph(model_details_df: pd.DataFrame) -> dict[str, list[str]]:
    """{Predicted parameter: [Input parameter, ...]} straight off the Model
    details sheet — works for any set of predicted parameters."""
    graph: dict[str, list[str]] = {}
    input_cols = config_io.input_param_cols(model_details_df)
    for _, r in model_details_df.iterrows():
        pred = r.get("Predicted parameter")
        if pd.isna(pred):
            continue
        pred = str(pred).strip()
        inputs = [str(r[c]).strip() for c in input_cols if pd.notna(r[c])]
        graph[pred] = inputs
    return graph


def topological_execution_order(graph: dict[str, list[str]]) -> list[str]:
    """DFS-based topological sort: dependencies are predicted before the
    parameters that use them. Robust to cycles (a cyclic edge is simply
    skipped rather than raising)."""
    order: list[str] = []
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(node: str) -> None:
        if node in visited or node not in graph:
            return
        if node in in_progress:
            return  # cycle guard
        in_progress.add(node)
        for dep in graph[node]:
            visit(dep)
        in_progress.discard(node)
        visited.add(node)
        order.append(node)

    for node in graph:
        visit(node)
    return order


def filter_model_details_by_section(
    model_details_df: pd.DataFrame,
    target_section: str | None,
    section_order: list[str],
) -> pd.DataFrame:
    """Restricts Model details to predicted parameters whose Section is the
    target section or an upstream one (see config_io.allowed_sections_upto).
    Rows with a blank/unclassified Section are always kept. No-ops when no
    target_section/section_order was supplied, or there's no Section column."""
    if model_details_df is None or model_details_df.empty:
        return model_details_df
    sec_col = config_io.section_col(model_details_df)
    if sec_col is None or not target_section or not section_order:
        return model_details_df

    allowed = {s.strip().lower() for s in config_io.allowed_sections_upto(section_order, target_section)}
    sec_series = model_details_df[sec_col].astype(str).str.strip().str.lower()
    keep_mask = sec_series.isin(allowed) | sec_series.eq("") | sec_series.eq("nan")
    return model_details_df[keep_mask].reset_index(drop=True)


def collect_simulation_functions(plugin: ModuleType | None) -> dict:
    """Simulation/first-principle functions from the plant plug-in, keyed by
    Predicted parameter name: BULK_SIMULATION (also used by the training
    script) merged with SIMULATION (runtime-only overrides). Empty when the
    plant has no plug-in."""
    if plugin is None:
        return {}
    sim_funcs = dict(getattr(plugin, "BULK_SIMULATION", {}) or {})
    sim_funcs.update(getattr(plugin, "SIMULATION", {}) or {})
    return sim_funcs


def collect_formula_functions(formulas_df: pd.DataFrame) -> dict:
    """First-Principle parameters driven by a user-typed Formula (Model
    Definition's Formula Editor, config_io.FORMULAS_COLUMNS) instead of a
    hardcoded plant plug-in function. Returned in the exact shape
    collect_simulation_functions() returns, so the caller can simply
    `sim_funcs.update(...)` these in -- a formula takes precedence over a
    plug-in function for the same parameter name, since it's a more
    specific, explicitly-configured override. Uses formula_eval's safe,
    whitelisted AST evaluator -- never Python's eval()/exec()."""
    if formulas_df is None or formulas_df.empty:
        return {}
    funcs: dict = {}
    for _, r in formulas_df.iterrows():
        param = str(r.get("Predicted parameter", "")).strip()
        expr = str(r.get("Formula", "")).strip()
        if not param or not expr or expr.lower() == "nan":
            continue

        def make_fn(expr: str):
            def fn(row_df: pd.DataFrame):
                names = formula_eval.extract_variable_names(expr)
                values = {n: float(row_df[n].iloc[-1]) for n in names}
                return formula_eval.evaluate_formula(expr, values)
            return fn

        funcs[param] = make_fn(expr)
    return funcs


def simulate_and_update_parameter(
    y_col: str,
    selected_row: pd.DataFrame,
    selected_row_updated: pd.DataFrame,
    sim_funcs: dict,
) -> pd.DataFrame:
    """Runtime counterpart of the training script's bulk-simulation pass:
    recomputes a simulation/first-principle parameter for the current row via
    the plant plug-in. Runs at the parameter's own slot in the execution
    order, so it reflects whatever inputs the user has overridden by then."""
    sim_func = sim_funcs.get(y_col)
    if sim_func is None:
        return selected_row_updated

    try:
        needs_actual = (
            y_col not in selected_row.columns
            or pd.isna(pd.to_numeric(selected_row[y_col], errors="coerce").iloc[0])
        )
        if needs_actual:
            actual_series = sim_func(selected_row.copy())
            selected_row.loc[:, y_col] = float(pd.Series(actual_series).iloc[-1])
    except Exception:
        logger.exception("Baseline simulation for '%s' failed; keeping whatever baseline value exists.", y_col)

    try:
        sim_series = sim_func(selected_row_updated.copy())
        selected_row_updated.loc[:, y_col] = float(pd.Series(sim_series).iloc[-1])
    except Exception:
        logger.exception("Simulation for '%s' failed; keeping baseline value for it.", y_col)
    return selected_row_updated


def predict_and_update_with_kalman(
    y_col: str,
    row_df: pd.DataFrame,
    model_details_df: pd.DataFrame,
    model_dir: str,
) -> pd.DataFrame:
    """Loads kalman_filter_model_{y_col}.pkl + its two scalers, runs one
    no-measurement Kalman step over the tag's configured input features
    (name-based, via config_io.input_param_cols — NOT positional), and writes
    the inverse-scaled prediction into row_df[y_col]."""
    row = model_details_df[model_details_df["Predicted parameter"] == y_col]
    u_cols = row[config_io.input_param_cols(model_details_df)].dropna(axis=1).values.ravel().tolist()
    u_cols = [str(c).strip() for c in u_cols if str(c).strip()]

    model_path = os.path.join(model_dir, f"kalman_filter_model_{y_col}.pkl")
    scaler_x_path = os.path.join(model_dir, f"scaler_X_{y_col}.pkl")
    scaler_y_path = os.path.join(model_dir, f"scaler_y_{y_col}.pkl")

    with open(model_path, "rb") as f:
        kalman_model = pickle.load(f)
    scaler_x = joblib.load(scaler_x_path)
    scaler_y = joblib.load(scaler_y_path)

    feature_df = row_df[u_cols]
    scaled = scaler_x.transform(feature_df)
    kalman_model.step(y=None, u=scaled.reshape(-1, 1))

    results = kalman_model.to_dataframe()
    pred_scaled = results[("$y_0$", "filtered", "output")].iloc[-1]
    pred_unscaled = scaler_y.inverse_transform([[pred_scaled]]).ravel()

    row_df.loc[:, y_col] = pred_unscaled[0]
    return row_df


def predict_and_update_with_soft_sensor_model(
    y_col: str, row_df: pd.DataFrame, case_id: str = DEFAULT_CASE_ID
) -> pd.DataFrame:
    """Alternative to predict_and_update_with_kalman(): if the Experiment
    History page has marked a Soft Sensor model (src/persistence/model_store)
    as the active predictor for y_col (src.data.database.whatif_model_selection),
    load it and predict with it instead of the dedicated Kalman filter.
    Both the selection lookup and the saved model itself are scoped to
    case_id, matching the per-case isolation of the dedicated Kalman path
    (model_dir already varies per case; this is its Soft Sensor counterpart).

    Raises LookupError — not FileNotFoundError — when no selection exists or
    a required input column is missing from row_df, so the caller can
    distinguish "nothing selected, use Kalman" from Kalman's own "no trained
    artifacts" case while still chaining both into the same graceful,
    logged, keep-baseline fallback."""
    model_name = list_model_selections(case_id).get(y_col)
    if model_name is None:
        raise LookupError(f"No selected Soft Sensor experiment for '{y_col}'.")

    wrapper, scaler_x, scaler_y, x_cols, y_cols = load_model_from_disk(model_name, case_id)
    missing = [c for c in x_cols if c not in row_df.columns]
    if missing:
        raise LookupError(f"Selected experiment '{model_name}' needs missing column(s) {missing}.")

    x_scaled = scaler_x.transform(row_df[x_cols])
    preds = scaler_y.inverse_transform(wrapper.predict_scaled(x_scaled))
    preds = np.asarray(preds)
    pred_value = preds[0, y_cols.index(y_col)] if preds.ndim > 1 else preds.ravel()[0]

    row_df.loc[:, y_col] = pred_value
    return row_df


def update_parameter_from_user_input(
    y_col: str,
    user_input_df: pd.DataFrame,
    row_df: pd.DataFrame,
) -> pd.DataFrame:
    """Overwrites row_df[y_col] with the user-supplied override if present and
    numeric; otherwise leaves the current (baseline/predicted) value."""
    if user_input_df is None or user_input_df.empty or "Parameter" not in user_input_df.columns:
        return row_df

    matching = user_input_df.loc[user_input_df["Parameter"].astype(str).str.strip() == y_col, "Value"]
    raw_val = matching.iloc[0] if not matching.empty else np.nan
    try:
        user_value = float(raw_val) if pd.notna(raw_val) and str(raw_val).strip().lower() != "none" else np.nan
    except (ValueError, TypeError):
        user_value = np.nan

    current_series = row_df.get(y_col, np.nan)
    current_value = (
        current_series.iloc[0]
        if isinstance(current_series, pd.Series) and not current_series.empty
        else current_series
    )

    final_value = user_value if not (isinstance(user_value, float) and np.isnan(user_value)) else current_value
    row_df.loc[:, y_col] = final_value
    return row_df


def _constraints_lookup(constraints_df: pd.DataFrame, parameter: str) -> pd.DataFrame | None:
    if constraints_df is None or constraints_df.empty:
        return None
    rows = constraints_df[constraints_df["Parameter"].astype(str).str.strip() == str(parameter).strip()]
    return rows if not rows.empty else None


def apply_linked_constraints_for_inputs(
    row_df: pd.DataFrame,
    input_params: list[str],
    constraints_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generic replacement for the old hardcoded 'bump speed to max if steam
    flow & speed are both below their limits' blocks. For every input_param
    about to be consumed, checks whether any Constraints row names it as a
    'Linked Parameter' with Action == 'bump_linked_to_max'; if so, applies
    that rule using only values from the Constraints sheet."""
    if constraints_df is None or constraints_df.empty or "Linked Parameter" not in constraints_df.columns:
        return row_df

    for p in input_params:
        trigger_rows = constraints_df[constraints_df["Linked Parameter"].astype(str).str.strip() == str(p).strip()]
        if trigger_rows.empty:
            continue
        for _, trig in trigger_rows.iterrows():
            action = str(trig.get("Action", "")).strip().lower() or "bump_linked_to_max"
            if action != "bump_linked_to_max":
                continue
            trigger_param = str(trig["Parameter"]).strip()
            linked_param = str(trig["Linked Parameter"]).strip()
            if trigger_param not in row_df.columns or linked_param not in row_df.columns:
                continue
            linked_rows = _constraints_lookup(constraints_df, linked_param)
            if linked_rows is None:
                continue
            try:
                trig_val = float(row_df[trigger_param].values[0])
                link_val = float(row_df[linked_param].values[0])
                trig_limit = float(trig["user input value"])
                link_limit = float(linked_rows["user input value"].values[0])
                max_col = config_io.constraints_max_col(linked_rows)
                link_max = float(linked_rows[max_col].values[0])
                if trig_val < trig_limit and link_val < link_limit:
                    row_df.loc[:, linked_param] = link_max
            except (ValueError, TypeError, KeyError, IndexError):
                continue
    return row_df


def check_abort_constraints(
    row_df: pd.DataFrame,
    constraints_df: pd.DataFrame,
    y_col: str,
) -> tuple[bool, str | None]:
    """Generic replacement for the hardcoded 'CGC_5TH_STG_DISCH_PRES > limit
    -> abort' check. Any Constraints row with Action == 'abort_if_exceeds' on
    y_col hard-stops the run."""
    if constraints_df is None or constraints_df.empty or "Action" not in constraints_df.columns:
        return False, None
    rows = constraints_df[
        (constraints_df["Parameter"].astype(str).str.strip() == y_col)
        & (constraints_df["Action"].astype(str).str.strip().str.lower() == "abort_if_exceeds")
    ]
    if rows.empty or y_col not in row_df.columns:
        return False, None
    try:
        limit = float(rows["user input value"].values[0])
        val = float(row_df[y_col].values[0])
    except (ValueError, TypeError, IndexError):
        return False, None
    if val > limit:
        remark = rows["Remark"].values[0] if "Remark" in rows.columns and pd.notna(rows["Remark"].values[0]) else None
        msg = remark or f"constraints hit: {y_col} ({val:.2f}) exceeded limit ({limit:.2f})"
        return True, msg
    return False, None


def apply_leaf_overrides_and_constraints(
    row_df: pd.DataFrame,
    input_params: list[str],
    user_input_df: pd.DataFrame,
    constraints_df: pd.DataFrame,
) -> pd.DataFrame:
    """Right before a parameter is predicted: (a) applies any linked 'bump to
    max' constraint on its raw inputs, then (b) applies a user override on
    any of its raw inputs the user has set directly."""
    row_df = apply_linked_constraints_for_inputs(row_df, input_params, constraints_df)
    for p in input_params:
        if p in row_df.columns:
            row_df = update_parameter_from_user_input(p, user_input_df, row_df)
    return row_df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def whatif_analysis(
    df: pd.DataFrame,
    user_time: pd.Timestamp,
    user_input_df: pd.DataFrame,
    config: WhatIfConfig,
    model_dir: str,
    plugin: ModuleType | None = None,
    target_section: str | None = None,
    write_actual_vs_estimated_xlsx: bool = False,
    output_path: str | None = None,
    case_id: str = DEFAULT_CASE_ID,
) -> WhatIfResult:
    if plugin is None:
        plugin = plants.load_plant_formulas()

    section_order = config.section_order_list()
    target_section = target_section if target_section is not None else config.target_section

    model_details_df = filter_model_details_by_section(config.model_details_df, target_section, section_order)
    constraints_df = config.constraints_df

    owned = set(getattr(plugin, "OWNED_PARAMETERS", set())) if plugin else set()
    skip = set(getattr(plugin, "SKIP_PARAMETERS", set())) if plugin else set()
    hooks = dict(getattr(plugin, "HOOKS", {})) if plugin else {}

    # A predicted parameter whose "model type" is non-data-driven (e.g.
    # "First principle") never had a Kalman filter trained for it — treat it
    # like a plugin-owned parameter (skip the Kalman step) without requiring
    # a plug-in just to declare that.
    simulation_params = config_io.non_data_model_parameters(model_details_df)
    owned = owned | simulation_params

    sim_funcs = collect_simulation_functions(plugin)
    sim_funcs.update(collect_formula_functions(config.formulas_df))
    missing_sim = sorted(p for p in simulation_params if p not in sim_funcs and p not in skip)
    if missing_sim:
        logger.info(
            "Simulation-type parameter(s) %s have no SIMULATION/BULK_SIMULATION function; "
            "they'll keep their baseline value unless a HOOK sets them.",
            missing_sim,
        )

    graph = build_dependency_graph(model_details_df)
    execution_order = topological_execution_order(graph)

    selected_row = df.loc[[user_time]].copy()
    selected_row.index.name = "Timestamp"
    selected_row_updated = selected_row.copy()

    # Apply every user override up front, to every column it names — not
    # just the ones declared as some predicted parameter's own input.
    # Physics/simulation hooks often read raw historian tags directly that
    # were never declared as an "Input parameter" anywhere in Model details.
    if user_input_df is not None and not user_input_df.empty and "Parameter" in user_input_df.columns:
        for p in user_input_df["Parameter"].dropna().astype(str).str.strip().unique():
            if p and p in selected_row_updated.columns:
                selected_row_updated = update_parameter_from_user_input(p, user_input_df, selected_row_updated)

    hooks = {str(k).strip().lower().replace(" ", ""): v for k, v in hooks.items()}
    hooks_fired: set[str] = set()

    def _run_hook(hook_key: str, sr: pd.DataFrame, sru: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        hooks_fired.add(hook_key)
        result = hooks[hook_key](sr, sru)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return sr, result

    constraint_hit = False
    constraint_message: str | None = None

    for y_col in execution_order:
        if y_col in skip:
            continue

        input_params = graph.get(y_col, [])
        selected_row_updated = apply_leaf_overrides_and_constraints(
            selected_row_updated, input_params, user_input_df, constraints_df
        )

        if y_col in simulation_params:
            selected_row_updated = simulate_and_update_parameter(
                y_col=y_col, selected_row=selected_row, selected_row_updated=selected_row_updated,
                sim_funcs=sim_funcs,
            )
        elif y_col not in owned and y_col in selected_row_updated.columns:
            try:
                selected_row_updated = predict_and_update_with_soft_sensor_model(
                    y_col, selected_row_updated, case_id
                )
            except LookupError:
                try:
                    selected_row_updated = predict_and_update_with_kalman(
                        y_col, selected_row_updated, model_details_df, model_dir,
                    )
                except FileNotFoundError:
                    logger.info("No trained model for '%s' in %s; keeping baseline value.", y_col, model_dir)
                except KeyError as exc:
                    # Model Definition's Input parameter_N for y_col can now hold
                    # Soft Sensor X-feature names (populated on Accept) rather
                    # than historian tags, for parameters whose selected
                    # experiment's own X columns aren't in the historian either
                    # (the LookupError above) -- row_df[u_cols] then raises
                    # KeyError instead of the dedicated model simply being
                    # absent. Same graceful degrade as the FileNotFoundError
                    # case, not a crash.
                    logger.info(
                        "Kalman fallback for '%s' needs missing column(s) %s in %s; keeping baseline value.",
                        y_col, exc, model_dir,
                    )

        selected_row_updated = update_parameter_from_user_input(y_col, user_input_df, selected_row_updated)

        aborted, msg = check_abort_constraints(selected_row_updated, constraints_df, y_col)
        if aborted:
            selected_row_updated[y_col] = msg
            constraint_hit = True
            constraint_message = msg
            break

        hook_key = f"after:{y_col}".strip().lower().replace(" ", "")
        if hook_key in hooks:
            selected_row, selected_row_updated = _run_hook(hook_key, selected_row, selected_row_updated)

    if not constraint_hit:
        # Safety net: any hook whose trigger parameter never appeared in the
        # execution order (missing/misspelled in Model details) still runs,
        # so its outputs don't silently stay frozen at baseline.
        for hook_key in hooks:
            if hook_key in hooks_fired:
                continue
            logger.warning(
                "Hook '%s' was never triggered by the execution order; running it now "
                "so its output parameters still get computed.", hook_key,
            )
            try:
                selected_row, selected_row_updated = _run_hook(hook_key, selected_row, selected_row_updated)
            except Exception:
                logger.exception("Hook '%s' failed in the safety-net pass.", hook_key)

    result = _build_result(selected_row, selected_row_updated, user_time, constraint_hit, constraint_message)
    if write_actual_vs_estimated_xlsx and output_path:
        _write_actual_vs_estimated(selected_row, selected_row_updated, output_path)
    return result


def _build_result(
    actual_row: pd.DataFrame,
    estimated_row: pd.DataFrame,
    user_time: pd.Timestamp,
    constraint_hit: bool,
    constraint_message: str | None,
) -> WhatIfResult:
    actual = json.loads(actual_row.iloc[[0]].to_json(orient="records"))[0]
    estimated = json.loads(estimated_row.iloc[[0]].to_json(orient="records"))[0]
    actual["Timestamp"] = str(user_time)
    estimated["Timestamp"] = str(user_time)
    return WhatIfResult(
        actual=actual,
        estimated=estimated,
        constraint_hit=constraint_hit,
        constraint_message=constraint_message,
    )


def _write_actual_vs_estimated(actual_row: pd.DataFrame, estimated_row: pd.DataFrame, output_path: str) -> None:
    combined = pd.concat([actual_row, estimated_row], axis=0)
    combined.index = ["actual", "estimated"]
    combined.to_excel(output_path, engine="openpyxl")
