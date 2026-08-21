# -*- coding: utf-8 -*-
"""
Created on Thu Apr  9 12:55:23 2026
@author: 30793167 : Sumit Kumar

====================================================================
GENERIC, MULTI-PLANT WHAT-IF ENGINE
====================================================================
This used to be a hand-written, hardcoded sequence of ~20 prediction
steps and 3 copy-pasted constraint checks specific to the YANPET
Olefin-1 plant (CGC / PRC / ERC compressor trains). It is now a
config-driven engine:

  * The ORDER in which parameters get predicted is derived automatically
    from the "Model details" sheet of Config_file_updated.xlsx (a dependency
    graph, topologically sorted) -- no hardcoded parameter list.

  * "Input table" constraints (e.g. "if turbine steam flow & speed are
    both below their operating limits, bump the speed set point to its
    max" or "abort if a pressure exceeds its safe limit") are now driven
    entirely by the "Constraints" sheet, using two new columns:
        - "Linked Parameter" : the parameter to bump, if the row's own
          Parameter (the trigger) is below its "user input value" AND
          the linked parameter is below ITS OWN "user input value".
        - "Action"            : "bump_linked_to_max" (default when a
          Linked Parameter is given) or "abort_if_exceeds".
    Any plant can express its own constraint rules just by editing this
    sheet -- no code changes required.

  * Equipment-specific physics that can't be reduced to a Kalman model
    (furnace COT correlations, CoolProp turbine/compressor thermodynamics)
    is kept OUT of this file. It lives in a small, swappable plug-in
    module per plant: plants/<plant_name>_formulas.py (see
    plants/yanpet_olf1_formulas.py for the YANPET reference
    implementation). A plant with no bespoke physics needs no plug-in
    at all -- the engine runs purely off Kalman models + constraints.

  * Every path (Config_file_updated.xlsx, trained model .pkl files, results
    output) is resolved from PLANT_NAME, so multiple plants can share
    this exact file without any edits -- everything is switched through
    the Streamlit UI (plant selector) or the PLANT_NAME environment
    variable.
====================================================================
"""
# Import libraries
import os
import importlib.util

import pandas as pd
import numpy as np
import pickle
import joblib

# =====================================================================
# MULTI-PLANT PATH RESOLUTION  (mirrors Model_development_and_static_
# whatif_testing.py so both files always point at the same plant)
# =====================================================================
PLANT_NAME = (os.environ.get("PLANT_NAME") or "YANPET_OLF1").strip() or "YANPET_OLF1"
DATA_ROOT = "..\\Data"
RESULTS_ROOT = "..\\Results"


def _resolve_plant_dir(base_dir: str, plant_name: str) -> str:
    """Prefer <base_dir>/<plant_name>; fall back to a flat <base_dir>
    layout for deployments created before multi-plant support existed."""
    nested = os.path.join(base_dir, plant_name)
    return nested if os.path.isdir(nested) else base_dir


def load_process_data(plant_name: str = None) -> pd.DataFrame:
    """Load and preprocess the simulated historian data for a plant."""
    plant_name = plant_name or PLANT_NAME
    results_dir = _resolve_plant_dir(RESULTS_ROOT, plant_name)
    df = pd.read_excel(os.path.join(results_dir, 'Raw_data_plus_simulated_data.xlsx'))
    df.set_index('Timestamp', inplace=True)
    return df


# Kept for backwards compatibility with scripts that import a
# module-level `df` from this file (e.g. earlier notebooks).
try:
    df = load_process_data()
except Exception as _e:  # noqa: BLE001
    df = None
    print(f"[plant_engine] no pre-built historian data yet for plant "
          f"'{PLANT_NAME}' ({_e}); call load_process_data() after training.")


# =====================================================================
# PLANT PHYSICS PLUG-IN DISCOVERY
# =====================================================================
def load_plant_formulas(plant_name: str = None):
    """Loads plants/<plant_name>_formulas.py next to this file, if present.
    Returns None (pure data-driven engine, no bespoke physics hooks) when
    no plug-in exists for the plant. A plant plug-in may define:
        HOOKS              : {"after:<param>": callable(row, row_updated)}
        OWNED_PARAMETERS    : set of predicted params computed by physics,
                              NOT by Kalman (engine skips the Kalman step
                              but still applies hooks/overrides).
        SKIP_PARAMETERS     : set of predicted params to ignore entirely
                              (legacy / unused alternate models).
        BULK_SIMULATION     : {param: callable(df) -> pd.Series} physics
                              for params whose Model details 'model' is a
                              simulation/first-principle type. Shared with
                              the training script; the engine also calls
                              these at runtime on the current what-if row.
        SIMULATION          : optional runtime-only overrides of
                              BULK_SIMULATION entries (same signature).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    plant_name = (plant_name or PLANT_NAME).strip().lower().replace(" ", "_")
    # Same TWO candidate locations the training script checks -- keeping
    # these in sync matters: if only one of the two scripts finds the
    # plug-in, hook/simulation parameters (COT, PRC power, totals, ...)
    # get populated during training but silently stay frozen at their
    # baseline values in every what-if run.
    candidates = [
        os.path.join(here, "plants", f"{plant_name}_formulas.py"),  # plants/ sub-folder layout
        os.path.join(here, f"{plant_name}_formulas.py"),            # plug-in next to this file
    ]
    candidate = next((c for c in candidates if os.path.isfile(c)), None)
    if candidate is None:
        print(f"[plant_engine] WARNING: no physics plug-in found for plant "
              f"'{plant_name}' (looked for: {candidates}). Hook/simulation "
              f"parameters (e.g. COT, compressor power, plant totals) will "
              f"NOT be recomputed in what-if runs.")
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"plant_formulas_{plant_name}", candidate)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print(f"[plant_engine] loaded plant physics plug-in: {candidate}")
        return mod
    except Exception as e:  # noqa: BLE001
        print(f"[plant_engine] WARNING: could not load plant physics plug-in "
              f"'{candidate}': {e}. Hook/simulation parameters will NOT be "
              f"recomputed in what-if runs.")
        return None


# =====================================================================
# GENERIC BUILDING BLOCKS  (fully data-driven, no plant-specific names)
# =====================================================================
def _input_param_cols(config_df_model_details: pd.DataFrame) -> list:
    """Only 'Input parameter_N' columns are ever treated as model inputs --
    explicitly, by name -- so metadata columns like 'model' (data-driven
    vs simulation/first-principle) are never mistaken for an input tag."""
    return [c for c in config_df_model_details.columns
            if str(c).strip().lower().startswith("input parameter")]


def _model_type_col(config_df_model_details: pd.DataFrame):
    """Finds the Model details column that says whether a predicted
    parameter is a data-driven (Kalman) model or a simulation/
    first-principle one. Tolerant of naming variants; returns None if
    the sheet doesn't have one (older config workbooks)."""
    for c in config_df_model_details.columns:
        cn = str(c).strip().lower()
        if cn in ("model", "model type", "model_type") or ("model" in cn and "type" in cn):
            return c
    return None


def config_non_data_model_parameters(config_df_model_details: pd.DataFrame) -> set:
    """Predicted parameters whose 'model' column is set to something
    other than a data-driven model (e.g. 'First principle', 'Simulation').
    A blank value or a missing column means data-driven, so this returns
    an empty set for older config workbooks -- fully backward compatible."""
    col = _model_type_col(config_df_model_details)
    if col is None:
        return set()
    out = set()
    for _, r in config_df_model_details.iterrows():
        pred = r.get("Predicted parameter")
        if pd.isna(pred):
            continue
        mtype = r.get(col)
        mtype = "" if pd.isna(mtype) else str(mtype).strip().lower()
        if mtype and "data" not in mtype:
            out.add(str(pred).strip())
    return out


# =====================================================================
# SECTION-BASED PROCESS FLOW SCOPING
# =====================================================================
def _section_col(config_df_model_details: pd.DataFrame):
    """Finds the Model details column naming each predicted parameter's
    plant section. Tolerant of naming variants; returns None if the
    sheet has no such column (older config workbooks -- fully backward
    compatible, no scoping applied in that case)."""
    for c in config_df_model_details.columns:
        if str(c).strip().lower() == "section":
            return c
    return None


def allowed_sections_upto(section_order: list, target_section: str) -> list:
    """Given the plant's process execution order (e.g. Furnace, Quench,
    CGC, ERC, PRC, Cold) and a selected target section, returns every
    section from the start of the sequence up to and INCLUDING the
    target -- i.e. all upstream sections plus the target itself, with no
    downstream sections. If target_section isn't found in section_order
    (or either is empty), no restriction is applied: the full section
    list is returned unchanged so older/unconfigured plants keep
    behaving exactly as before."""
    if not section_order or not target_section:
        return list(section_order) if section_order else []
    norm_order = [str(s).strip().lower() for s in section_order]
    t = str(target_section).strip().lower()
    if t not in norm_order:
        return list(section_order)
    idx = norm_order.index(t)
    return list(section_order)[: idx + 1]


def filter_model_details_by_section(
    config_df_model_details: pd.DataFrame,
    target_section: str = None,
    section_order: list = None,
) -> pd.DataFrame:
    """Restricts the Model details sheet to predicted parameters whose
    'Section' is one of the upstream sections + the target section
    itself (see allowed_sections_upto). This is what keeps the
    prediction engine from ever running models that belong to
    downstream sections, per the section-based What-if requirement.

    Rows with a blank/unclassified Section are always kept (so an
    un-tagged predicted parameter -- e.g. a global first-principle
    calculation -- never silently disappears just because the config
    workbook hasn't been fully annotated yet).

    No-ops (returns the frame unchanged) when:
      * no target_section / section_order was supplied, or
      * the Model details sheet has no 'Section' column at all.
    """
    if config_df_model_details is None or config_df_model_details.empty:
        return config_df_model_details
    sec_col = _section_col(config_df_model_details)
    if sec_col is None or not target_section or not section_order:
        return config_df_model_details

    allowed = {s.strip().lower() for s in allowed_sections_upto(section_order, target_section)}
    sec_series = config_df_model_details[sec_col].astype(str).str.strip().str.lower()
    keep_mask = sec_series.isin(allowed) | sec_series.eq("") | sec_series.eq("nan")
    return config_df_model_details[keep_mask].reset_index(drop=True)


def collect_simulation_functions(custom_formulas) -> dict:
    """Simulation / first-principle functions exposed by the plant
    plug-in, keyed by 'Predicted parameter' name. Two sources, merged:

      * BULK_SIMULATION : {param: callable(df) -> pd.Series} -- already
        used by the TRAINING script across the whole historian. These
        functions are naturally vectorized, so they work just as well on
        the single-row dataframe the what-if engine passes at runtime.
      * SIMULATION      : optional {param: callable(df) -> pd.Series}
        with runtime-specific implementations. Takes precedence over a
        same-named BULK_SIMULATION entry, for plants whose runtime
        physics must differ from the bulk/historical version.

    Returns {} when the plant has no plug-in (pure Kalman engine)."""
    if custom_formulas is None:
        return {}
    sim_funcs = dict(getattr(custom_formulas, "BULK_SIMULATION", {}) or {})
    sim_funcs.update(getattr(custom_formulas, "SIMULATION", {}) or {})
    return sim_funcs


def simulate_and_update_parameter(
    y_col: str,
    selected_row: pd.DataFrame,
    selected_row_updated: pd.DataFrame,
    sim_funcs: dict,
) -> pd.DataFrame:
    """Runtime counterpart of the training script's bulk-simulation pass:
    computes a simulation/first-principle 'Predicted parameter' for the
    CURRENT what-if row by calling the plant plug-in's simulation
    function on it. Because this runs at the parameter's own slot in the
    topological execution order -- i.e. AFTER user overrides and linked
    constraints have been applied to its inputs, and after any upstream
    Kalman/simulation parameters have been refreshed -- the result
    automatically reflects whatever input values the user changed in the
    What-if Dashboard.

    The simulation function receives a COPY of the row, and only the
    target column is written back, so intermediate columns the physics
    creates internally don't leak into the Actual-vs-estimated table.

    If the baseline ('actual') row is missing this parameter (e.g. the
    historian workbook predates the parameter being added to the config),
    the same function also fills in the actual side once, so the
    comparison table and KPI deltas stay meaningful."""
    sim_func = sim_funcs.get(y_col)
    if sim_func is None:
        return selected_row_updated

    # Baseline / 'actual' side -- only when absent or NaN, never overwriting
    # the historian's own (bulk-simulated) value.
    try:
        needs_actual = (
            y_col not in selected_row.columns
            or pd.isna(pd.to_numeric(selected_row[y_col], errors="coerce").iloc[0])
        )
        if needs_actual:
            actual_series = sim_func(selected_row.copy())
            selected_row.loc[:, y_col] = float(pd.Series(actual_series).iloc[-1])
    except Exception as e:  # noqa: BLE001
        print(f"[plant_engine] baseline simulation for '{y_col}' failed ({e}); "
              f"keeping whatever baseline value exists.")

    # Scenario / 'estimated' side -- always recomputed from the current
    # (user-overridden) inputs.
    try:
        sim_series = sim_func(selected_row_updated.copy())
        selected_row_updated.loc[:, y_col] = float(pd.Series(sim_series).iloc[-1])
    except Exception as e:  # noqa: BLE001
        print(f"[plant_engine] simulation for '{y_col}' failed ({e}); "
              f"keeping baseline value for it.")
    return selected_row_updated


def predict_and_update_with_kalman(
    y_col: str,
    selected_row_updated: pd.DataFrame,
    config_df_model_details: pd.DataFrame,
    results_dir: str,
) -> pd.DataFrame:
    """Generalizes the Kalman filter loading, scaling, prediction, and
    dataframe update process for any target column (y_col)."""
    row = config_df_model_details[config_df_model_details["Predicted parameter"] == y_col]
    u_cols = row[_input_param_cols(config_df_model_details)].dropna(axis=1).values.ravel().tolist()
    u_cols = [str(c).strip() for c in u_cols if str(c).strip()]

    model_path = os.path.join(results_dir, f'kalman_filter_model_{y_col}.pkl')
    scaler_x_path = os.path.join(results_dir, f'scaler_X_{y_col}.pkl')
    scaler_y_path = os.path.join(results_dir, f'scaler_y_{y_col}.pkl')

    with open(model_path, 'rb') as f:
        kalman_model = pickle.load(f)

    scaler_X = joblib.load(scaler_x_path)
    scaler_y = joblib.load(scaler_y_path)

    feature_df = selected_row_updated[u_cols]
    scaled_test = scaler_X.transform(feature_df)
    kalman_model.step(y=None, u=scaled_test.reshape(-1, 1))

    results = kalman_model.to_dataframe()
    pred_scaled = results[('$y_0$', 'filtered', 'output')].iloc[-1]
    pred_unscaled = scaler_y.inverse_transform([[pred_scaled]]).ravel()

    selected_row_updated.loc[:, y_col] = pred_unscaled[0]
    return selected_row_updated


def update_parameter_from_user_input(
    y_col: str,
    user_input_df: pd.DataFrame,
    selected_row_updated: pd.DataFrame,
) -> pd.DataFrame:
    """Generalizes fetching a user override for y_col and applying it if valid."""
    if user_input_df is None or user_input_df.empty or "Parameter" not in user_input_df.columns:
        return selected_row_updated

    matching_input = user_input_df.loc[user_input_df["Parameter"].astype(str).str.strip() == y_col, 'Value']
    raw_input_val = matching_input.iloc[0] if not matching_input.empty else np.nan

    try:
        user_value = float(raw_input_val) if pd.notna(raw_input_val) and str(raw_input_val).strip().lower() != "none" else np.nan
    except (ValueError, TypeError):
        user_value = np.nan

    current_val_series = selected_row_updated.get(y_col, np.nan)
    current_value = current_val_series.iloc[0] if isinstance(current_val_series, pd.Series) and not current_val_series.empty else current_val_series

    final_value = user_value if not (isinstance(user_value, float) and np.isnan(user_value)) else current_value

    if isinstance(selected_row_updated, pd.DataFrame):
        selected_row_updated.loc[:, y_col] = final_value
    else:
        selected_row_updated[y_col] = final_value

    return selected_row_updated


def build_dependency_graph(config_df_model_details: pd.DataFrame) -> dict:
    """{Predicted parameter: [Input parameter, ...]} straight off the
    Model details sheet -- works for any set of predicted parameters."""
    graph = {}
    input_cols = _input_param_cols(config_df_model_details)
    for _, r in config_df_model_details.iterrows():
        pred = r.get("Predicted parameter")
        if pd.isna(pred):
            continue
        pred = str(pred).strip()
        inputs = [str(r[c]).strip() for c in input_cols if pd.notna(r[c])]
        graph[pred] = inputs
    return graph


def topological_execution_order(graph: dict) -> list:
    """DFS-based topological sort: dependencies are predicted before the
    parameters that use them. Robust to cycles (a cyclic edge is simply
    skipped rather than raising)."""
    order, visited, in_progress = [], set(), set()

    def visit(node):
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


def _constraints_lookup(constraints_df: pd.DataFrame, parameter: str):
    if constraints_df is None or constraints_df.empty:
        return None
    rows = constraints_df[constraints_df["Parameter"].astype(str).str.strip() == str(parameter).strip()]
    return rows if not rows.empty else None


def apply_linked_constraints_for_inputs(
    selected_row_updated: pd.DataFrame,
    input_params: list,
    constraints_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generic replacement for the old hardcoded 'bump speed to max if
    steam flow & speed are both below their limits' blocks. For every
    input_param about to be consumed, checks whether any Constraints row
    names it as a 'Linked Parameter' with Action == 'bump_linked_to_max';
    if so, applies that rule using ONLY values from the Constraints sheet."""
    if constraints_df is None or constraints_df.empty or "Linked Parameter" not in constraints_df.columns:
        return selected_row_updated

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
            if trigger_param not in selected_row_updated.columns or linked_param not in selected_row_updated.columns:
                continue
            linked_rows = _constraints_lookup(constraints_df, linked_param)
            if linked_rows is None:
                continue
            try:
                trig_val = float(selected_row_updated[trigger_param].values[0])
                link_val = float(selected_row_updated[linked_param].values[0])
                trig_limit = float(trig["user input value"])
                link_limit = float(linked_rows["user input value"].values[0])
                max_col = "Max vlaue" if "Max vlaue" in linked_rows.columns else "Max value"
                link_max = float(linked_rows[max_col].values[0])
                if trig_val < trig_limit and link_val < link_limit:
                    selected_row_updated.loc[:, linked_param] = link_max
            except (ValueError, TypeError, KeyError, IndexError):
                continue
    return selected_row_updated


def check_abort_constraints(selected_row_updated: pd.DataFrame, constraints_df: pd.DataFrame, y_col: str):
    """Generic replacement for the hardcoded 'CGC_5TH_STG_DISCH_PRES >
    limit -> abort' check. Any Constraints row with Action ==
    'abort_if_exceeds' on y_col hard-stops the run."""
    if constraints_df is None or constraints_df.empty or "Action" not in constraints_df.columns:
        return False, None
    rows = constraints_df[
        (constraints_df["Parameter"].astype(str).str.strip() == y_col) &
        (constraints_df["Action"].astype(str).str.strip().str.lower() == "abort_if_exceeds")
    ]
    if rows.empty or y_col not in selected_row_updated.columns:
        return False, None
    try:
        limit = float(rows["user input value"].values[0])
        val = float(selected_row_updated[y_col].values[0])
    except (ValueError, TypeError, IndexError):
        return False, None
    if val > limit:
        remark = rows["Remark"].values[0] if "Remark" in rows.columns and pd.notna(rows["Remark"].values[0]) else None
        msg = remark or f"constraints hit: {y_col} ({val:.2f}) exceeded limit ({limit:.2f})"
        return True, msg
    return False, None


def apply_leaf_overrides_and_constraints(
    selected_row_updated: pd.DataFrame,
    input_params: list,
    user_input_df: pd.DataFrame,
    constraints_df: pd.DataFrame,
) -> pd.DataFrame:
    """Right before a parameter is predicted, this (a) applies any linked
    'bump to max' constraint on its raw inputs, then (b) applies a user
    override on any of its raw inputs that the user has set directly.
    Generic across plants -- driven entirely by the Constraints /
    user-inputs sheets, not by hardcoded parameter names."""
    selected_row_updated = apply_linked_constraints_for_inputs(selected_row_updated, input_params, constraints_df)
    for p in input_params:
        if p in selected_row_updated.columns:
            selected_row_updated = update_parameter_from_user_input(p, user_input_df, selected_row_updated)
    return selected_row_updated


def _color_diff(val):
    color = 'green' if val > 0 else 'red' if val < 0 else ''
    return f'background-color: {color}' if color else ''


def _finalize(selected_row, selected_row_updated, user_time, results_dir):
    Actual_vs_estimated = pd.concat([selected_row, selected_row_updated], axis=0)
    Actual_vs_estimated.index = ["actual", "estimated"]

    try:
        diff = Actual_vs_estimated.loc['estimated'] - Actual_vs_estimated.loc['actual']
        styled = Actual_vs_estimated.style.apply(lambda _: diff.map(_color_diff), axis=1)
    except TypeError:
        # a constraint-abort message string landed in what is usually a
        # numeric column -- fall back to an unstyled table.
        styled = Actual_vs_estimated

    Actual_vs_estimated["Timestamp"] = user_time
    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, "Actual_vs_estimated what if.xlsx")
    try:
        styled.to_excel(out_path, engine='openpyxl')
    except Exception:  # noqa: BLE001
        Actual_vs_estimated.to_excel(out_path, engine='openpyxl')
    return styled


# =====================================================================
# THE GENERIC ENGINE
# =====================================================================
def whatif_analysis(
    df: pd.DataFrame,
    user_time,
    user_input_df: pd.DataFrame,
    plant_name: str = None,
    plant_dir: str = None,
    results_dir: str = None,
    custom_formulas=None,
    target_section: str = None,
    section_order: list = None,
):
    """Runs a full what-if pass for `user_time`, entirely driven by the
    selected plant's Config_file_updated.xlsx (Model details + Constraints
    sheets) plus an optional physics plug-in.

    Parameters
    ----------
    plant_name : which plant's config/model/results folders to use
                 (defaults to PLANT_NAME / env var, set by the dashboard).
    plant_dir  : override for the folder containing Config_file_updated.xlsx.
    results_dir: override for the folder containing trained *.pkl models
                 and where the output workbook is written.
    custom_formulas : override the auto-discovered plant plug-in module
                 (mainly useful for testing).
    target_section : the section selected for this What-if run (e.g.
                 "CGC"). When given together with section_order, the
                 engine only predicts models whose Model details
                 'Section' is that section or an upstream one -- see
                 filter_model_details_by_section(). None (the default)
                 runs every predicted parameter, unchanged behaviour.
    section_order : the plant's process execution order (e.g.
                 ["Furnace", "Quench", "CGC", "ERC", "PRC", "Cold"]),
                 as configured in the "Section Order" sheet / the
                 dashboard's Process Flow Order tab.
    """
    plant_name = plant_name or PLANT_NAME
    cfg_dir = plant_dir or _resolve_plant_dir(DATA_ROOT, plant_name)
    res_dir = results_dir or _resolve_plant_dir(RESULTS_ROOT, plant_name)
    model_dir = os.path.join(res_dir, "Model")

    config_df_model_details = pd.read_excel(os.path.join(cfg_dir, "Config_file_updated.xlsx"), sheet_name='Model details')
    constraints_df = pd.read_excel(os.path.join(cfg_dir, "Config_file_updated.xlsx"), sheet_name="Constraints")

    # Restrict the Model details sheet -- and therefore every downstream
    # step (simulation-param detection, the dependency graph, the
    # topological execution order) -- to the selected section and its
    # upstream sections. A no-op when target_section/section_order
    # aren't supplied or the sheet has no 'Section' column.
    config_df_model_details = filter_model_details_by_section(
        config_df_model_details, target_section=target_section, section_order=section_order
    )

    if custom_formulas is None:
        custom_formulas = load_plant_formulas(plant_name)
    owned = getattr(custom_formulas, "OWNED_PARAMETERS", set()) if custom_formulas else set()
    skip = getattr(custom_formulas, "SKIP_PARAMETERS", set()) if custom_formulas else set()
    hooks = getattr(custom_formulas, "HOOKS", {}) if custom_formulas else {}

    # A predicted parameter whose Model details "model" column says
    # something other than a data-driven model (e.g. "First principle",
    # "Simulation") never had a Kalman filter trained for it -- treat it
    # like a plugin-OWNED parameter (skip the Kalman step) without
    # requiring a Python plug-in just to declare that. A blank/missing
    # "model" value or a config workbook with no such column defaults to
    # data-driven, so older configs behave exactly as before.
    simulation_params = set(config_non_data_model_parameters(config_df_model_details))
    owned = set(owned) | simulation_params

    # Simulation/first-principle functions from the plant plug-in.
    # These are RUN AT THE PARAMETER'S OWN SLOT in the execution order
    # below, so a simulation-type parameter is recomputed for the current
    # row -- and therefore reacts to every user input change -- instead
    # of silently keeping its baseline historian value. A simulation
    # parameter with no registered function falls back to the old
    # behaviour (hook or baseline value), with a one-line notice.
    sim_funcs = collect_simulation_functions(custom_formulas)
    _missing_sim = sorted(p for p in simulation_params
                          if p not in sim_funcs and p not in skip)
    if _missing_sim:
        print(f"[plant_engine] simulation-type parameter(s) {_missing_sim} have no "
              f"SIMULATION/BULK_SIMULATION function in the '{plant_name}' formulas "
              f"plug-in -- they will keep their baseline value unless a HOOK sets them.")

    graph = build_dependency_graph(config_df_model_details)
    execution_order = topological_execution_order(graph)

    selected_row = pd.DataFrame(df.loc[user_time]).T
    selected_row.index.name = "Timestamp"
    selected_row_updated = selected_row.copy()

    # Apply EVERY user override up front, to every column it names --
    # not just the ones that happen to be declared as some predicted
    # parameter's "Input parameter" in Model details. Physics/simulation
    # hooks (e.g. furnace_cot_hook, prc_turbine_hook) often read raw
    # historian tags directly that were never declared as an "Input
    # parameter" anywhere in that sheet -- without this blanket pass,
    # changing such a tag in the What-if Dashboard has no effect on
    # those hooks' output, since the per-predicted-parameter override
    # step below only ever touches tags in that parameter's own,
    # explicitly-listed input list.
    if user_input_df is not None and not user_input_df.empty and "Parameter" in user_input_df.columns:
        for _p in user_input_df["Parameter"].dropna().astype(str).str.strip().unique():
            if _p and _p in selected_row_updated.columns:
                selected_row_updated = update_parameter_from_user_input(_p, user_input_df, selected_row_updated)

    # Normalize hook keys once ("after: X " -> "after:X") so a stray
    # space in the plug-in or the config sheet can't stop a hook firing.
    hooks = {str(k).strip().lower().replace(" ", ""): v for k, v in hooks.items()}
    hooks_fired = set()

    def _run_hook(hook_key, sr, sru):
        hooks_fired.add(hook_key)
        result = hooks[hook_key](sr, sru)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return sr, result

    for y_col in execution_order:
        if y_col in skip:
            continue

        input_params = graph.get(y_col, [])
        selected_row_updated = apply_leaf_overrides_and_constraints(
            selected_row_updated, input_params, user_input_df, constraints_df
        )

        if y_col in simulation_params:
            # Simulation / first-principle model type: recompute this
            # parameter for the CURRENT row via the plant plug-in's
            # simulation function. Inputs already carry the user's
            # overrides (blanket pass above + per-input pass just now),
            # so any input change in the dashboard flows straight
            # through to this parameter's value.
            selected_row_updated = simulate_and_update_parameter(
                y_col=y_col,
                selected_row=selected_row,
                selected_row_updated=selected_row_updated,
                sim_funcs=sim_funcs,
            )
        elif y_col not in owned and y_col in selected_row_updated.columns:
            try:
                selected_row_updated = predict_and_update_with_kalman(
                    y_col=y_col,
                    selected_row_updated=selected_row_updated,
                    config_df_model_details=config_df_model_details,
                    results_dir=model_dir,
                )
            except FileNotFoundError:
                # No trained model for this parameter yet -- keep the
                # baseline/historical value rather than hard-crashing.
                print(f"[plant_engine] no trained model for '{y_col}' in {model_dir}; keeping baseline value.")

        selected_row_updated = update_parameter_from_user_input(y_col, user_input_df, selected_row_updated)

        aborted, msg = check_abort_constraints(selected_row_updated, constraints_df, y_col)
        if aborted:
            selected_row_updated[y_col] = msg
            return _finalize(selected_row, selected_row_updated, user_time, res_dir)

        hook_key = f"after:{y_col}".strip().lower().replace(" ", "")
        if hook_key in hooks:
            selected_row, selected_row_updated = _run_hook(hook_key, selected_row, selected_row_updated)

    # -----------------------------------------------------------------
    # SAFETY NET: any registered hook whose trigger parameter never
    # appeared in the execution order (e.g. it isn't listed as a
    # "Predicted parameter" in the Model details sheet, or its name is
    # spelled differently there) would previously just never run --
    # leaving its outputs (Coil_Avg_COT / Overall_COT, PRC power,
    # Total_Power_(KW), ...) frozen at their baseline values with no
    # error anywhere. Run those leftovers now, in the order the plug-in
    # declares them (which encodes their dependencies: furnace -> PRC ->
    # totals), and say so loudly.
    # -----------------------------------------------------------------
    for hook_key in hooks:
        if hook_key in hooks_fired:
            continue
        print(f"[plant_engine] WARNING: hook '{hook_key}' was never triggered by the "
              f"execution order (its trigger parameter is missing from / spelled "
              f"differently in the Model details sheet). Running it now so its "
              f"output parameters still get computed.")
        try:
            selected_row, selected_row_updated = _run_hook(hook_key, selected_row, selected_row_updated)
        except Exception as hook_err:  # noqa: BLE001
            print(f"[plant_engine] hook '{hook_key}' failed in the safety-net pass: {hook_err}")

    return _finalize(selected_row, selected_row_updated, user_time, res_dir)
