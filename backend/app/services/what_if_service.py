"""
backend/app/services/what_if_service.py
==========================================
Business orchestration for the What-If Analysis module. Every function
reloads config/historian fresh from disk per call (no server-side session —
see src/whatif/engine.py's docstring and the migration plan's statelessness
note); all math is delegated to src/whatif/*, which is never modified here.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List

import pandas as pd
from fastapi import HTTPException, UploadFile

from src.data.database import DEFAULT_CASE_ID
from src.whatif import config_io, engine, formula_eval, historian, kpi, model_status, paths, plants, wizard
from src.whatif.config_io import WhatIfConfig

from backend.app.jobs.manager import job_manager
from backend.app.schemas import what_if as schemas


# Keyed by case_id (not a single slot) so switching between cases doesn't
# thrash a shared cache entry -- each case's config/historian is cached
# independently, invalidating only when that case's own file's mtime changes.
_config_cache: Dict[str, Dict[str, Any]] = {}
_config_cache_lock = threading.Lock()


def _empty_config() -> WhatIfConfig:
    """A brand-new case has no Config_file.xlsx on disk at all yet --
    whatif_case_service.create_case() deliberately creates blank folders,
    no files (matching the Streamlit reference's "build it all fresh from
    Setup" new-case flow). That's the normal starting state for a case, not
    an error: every get_*/commit_* endpoint should see the same well-shaped
    "nothing saved yet" config get_config_status() already special-cased
    for this — not a 404 that leaves the frontend's cached data from
    whichever case was active before untouched (query errors don't clear
    react-query's `data`), which is exactly the "new case shows the old
    case's tables" bug this fixes."""
    return WhatIfConfig(
        user_inputs_df=pd.DataFrame(columns=config_io.USER_INPUTS_COLUMNS),
        constraints_df=pd.DataFrame(columns=config_io.CONSTRAINTS_COLUMNS),
        display_order_df=pd.DataFrame(columns=config_io.DISPLAY_ORDER_COLUMNS),
        model_details_df=pd.DataFrame(columns=config_io.MODEL_DETAILS_COLUMNS),
        pi_names_df=pd.DataFrame(columns=config_io.PI_COLUMNS),
        section_order_df=pd.DataFrame(columns=config_io.SECTION_ORDER_COLUMNS),
        mvdvcv_df=pd.DataFrame(columns=config_io.MVDVCV_COLUMNS),
        formulas_df=pd.DataFrame(columns=config_io.FORMULAS_COLUMNS),
        target_section=None,
    )


def _load_config(case_id: str = DEFAULT_CASE_ID) -> WhatIfConfig:
    """Cached by (case_id, path, mtime), mirroring _load_historian() below:
    every What-If endpoint calls this, and on every page mount several of them
    fire in parallel (config/status, wizard/detected-counts, config/model-mapping,
    models/status), each independently opening Config_file.xlsx. Since this
    repo lives under a OneDrive-synced Desktop folder, that many concurrent
    opens is enough to collide with an in-flight upload's os.replace() and
    resurface the WinError 5 issue fixed in b98e63f. Safe to cache read-only
    (same rationale as _load_historian's docstring) — invalidates the instant
    the file's mtime changes, e.g. right after an upload."""
    path = paths.config_file(case_id)
    if not os.path.isfile(path):
        return _empty_config()
    mtime = os.path.getmtime(path)
    with _config_cache_lock:
        entry = _config_cache.get(case_id)
        if entry and entry["path"] == path and entry["mtime"] == mtime:
            return entry["cfg"]
    try:
        cfg = config_io.load_all_config(path)
    except config_io.ConfigSchemaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    with _config_cache_lock:
        _config_cache[case_id] = {"path": path, "mtime": mtime, "cfg": cfg}
    return cfg


_historian_cache: Dict[str, Dict[str, Any]] = {}
_historian_cache_lock = threading.Lock()


def _empty_historian() -> pd.DataFrame:
    """A brand-new case has no historian workbook on disk yet -- same
    "nothing saved yet, not an error" reasoning as _empty_config(): the
    caller shouldn't have to distinguish "this case has no data" from a
    genuine failure, and a 404 here left React Query's cached `data` from
    whichever case was active before untouched (queries don't clear `data`
    on error), which is exactly why "Model Definition" kept showing the
    previous case's rows via get_model_mapping()'s df.columns read below.
    src/whatif/historian.py::load_process_data() has no empty-shape path of
    its own (it raises if a real file parses to zero valid-timestamp rows),
    so this mirrors its actual output shape by hand: indexed by an empty
    DatetimeIndex named "Timestamp", no columns."""
    return pd.DataFrame(index=pd.DatetimeIndex([], name="Timestamp"))


def _load_historian(case_id: str = DEFAULT_CASE_ID) -> pd.DataFrame:
    """Cached by (case_id, path, mtime): the historian is a ~7000-row/194-column
    Excel file that takes several seconds to parse via openpyxl on every
    call — unlike the small config workbook, that cost is too high to pay
    on every dashboard interaction. Every consumer (engine.whatif_analysis,
    get_dates/get_timestamps/get_baseline/run_validation_filter) only reads
    from the returned frame or works on an explicit .copy(), so a read-only
    cache is safe. Invalidates automatically if the file is replaced (e.g. a
    future retrain phase), since the check is keyed on mtime, not just path."""
    path = paths.historian_file(case_id)
    if not os.path.isfile(path):
        return _empty_historian()
    mtime = os.path.getmtime(path)
    with _historian_cache_lock:
        entry = _historian_cache.get(case_id)
        if entry and entry["path"] == path and entry["mtime"] == mtime:
            return entry["df"]
    df = historian.load_process_data(path)
    with _historian_cache_lock:
        _historian_cache[case_id] = {"path": path, "mtime": mtime, "df": df}
    return df


def _atomic_write_bytes(path: str, data: bytes) -> None:
    """Temp-file-then-os.replace() write, to avoid a concurrent reader seeing
    a partially-written file. There is still no cross-request lock — Phase 1
    assumes a single engineer configuring at a time (documented limitation).

    On Windows, os.replace() can fail with PermissionError/WinError 5 if the
    destination is transiently locked by another process (Excel has it open,
    antivirus scanning it, OneDrive/cloud-sync briefly holding it if this repo
    lives under a synced folder like Desktop) — even though the file was fully
    readable moments earlier. That's a real, observed failure mode here (not
    hypothetical), so retry briefly before giving up rather than surfacing an
    opaque, uncaught 500 to the caller."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=os.path.splitext(path)[1])
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        # 15 attempts / ~28s total (was 8 / ~10s) — confirmed on this exact
        # machine that os.replace() can still fail past the old ~10s budget
        # even though the file tests as unlocked moments before and after,
        # with Windows Defender real-time protection active (AntivirusEnabled
        # / RealTimeProtectionEnabled both True) and this repo NOT under
        # OneDrive sync (verified: OneDrive's only registered sync root is
        # ~/OneDrive, unrelated to this path) — i.e. the actual lock holder
        # here is Defender's on-write scan of the freshly-written temp file,
        # not OneDrive. A real observed failure, not hypothetical, but a
        # RETRY LOOP CANNOT FIX THIS PERMANENTLY: it only widens the window a
        # transient AV/Excel/OneDrive lock has to clear. The durable fix is a
        # Windows Defender exclusion for this repo's Data/Results folders
        # (Windows Security > Virus & threat protection > Manage settings >
        # Exclusions, or, as Administrator: Add-MpPreference -ExclusionPath
        # "<repo path>").
        # Backoff is capped at 2.4s/attempt rather than growing unbounded, so
        # this doesn't turn into a multi-minute hang if the lock is actually
        # permanent (e.g. the file genuinely open in Excel).
        last_error: OSError | None = None
        for attempt in range(15):
            try:
                os.replace(tmp_path, path)
                return
            except OSError as e:
                last_error = e
                time.sleep(0.3 * min(attempt + 1, 8))
        raise last_error
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Config status / PI mapping / model mapping
# ---------------------------------------------------------------------------

def get_config_status(case_id: str = DEFAULT_CASE_ID) -> schemas.ConfigStatusResponse:
    path = paths.config_file(case_id)
    if not os.path.isfile(path):
        return schemas.ConfigStatusResponse(
            pi_mapping_present=False, pi_mapping_row_count=0,
            model_details_present=False, model_details_row_count=0, source_path=None,
        )
    cfg = _load_config(case_id)
    return schemas.ConfigStatusResponse(
        pi_mapping_present=not cfg.pi_names_df.empty,
        pi_mapping_row_count=len(cfg.pi_names_df),
        model_details_present=not cfg.model_details_df.empty,
        model_details_row_count=len(cfg.model_details_df),
        source_path=path,
    )


def get_pi_mapping(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    normalized = wizard.normalize_pi_df(cfg.pi_names_df)
    rows = json.loads(normalized.to_json(orient="records")) if not normalized.empty else []
    return schemas.RowsResponse(rows=rows)


async def upload_config(file: UploadFile, case_id: str = DEFAULT_CASE_ID) -> schemas.ConfigStatusResponse:
    data = await file.read()
    try:
        pd.ExcelFile(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not parse workbook: {e}")
    try:
        _atomic_write_bytes(paths.config_file(case_id), data)
    except OSError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The workbook was read successfully, but saving it to {paths.config_file(case_id)} failed: {e}. "
                "This usually means the file is currently open in Excel or being synced by OneDrive/cloud "
                "storage — close it and try again."
            ),
        )
    return get_config_status(case_id)


def get_detected_counts(case_id: str = DEFAULT_CASE_ID) -> schemas.DetectedCountsResponse:
    cfg = _load_config(case_id)
    pi_norm = wizard.normalize_pi_df(cfg.pi_names_df)
    cgc = wizard.available_stages(pi_norm, "CGC")
    prc = wizard.available_stages(pi_norm, "PRC")
    erc = wizard.available_stages(pi_norm, "ERC")
    furnaces = wizard.available_furnaces(pi_norm)
    return schemas.DetectedCountsResponse(
        cgc_max=max(cgc) if cgc else 0,
        prc_max=max(prc) if prc else 0,
        erc_max=max(erc) if erc else 0,
        furnace_max=max(furnaces) if furnaces else 0,
    )


def generate_mapping(
    body: schemas.GenerateMappingRequest, case_id: str = DEFAULT_CASE_ID
) -> schemas.GenerateMappingResponse:
    cfg = _load_config(case_id)
    pi_norm = wizard.normalize_pi_df(cfg.pi_names_df)
    cgc_all = wizard.available_stages(pi_norm, "CGC")
    prc_all = wizard.available_stages(pi_norm, "PRC")
    erc_all = wizard.available_stages(pi_norm, "ERC")
    furnace_all = wizard.available_furnaces(pi_norm)

    cgc_stages = [s for s in cgc_all if s <= body.cgc_stages]
    prc_stages = [s for s in prc_all if s <= body.prc_stages]
    erc_stages = [s for s in erc_all if s <= body.erc_stages]
    furnaces = [f for f in furnace_all if f <= body.furnaces]

    mapping = wizard.generate_pi_mapping(pi_norm, cgc_stages, prc_stages, erc_stages, furnaces)
    section_counts: Dict[str, int] = (
        {k: int(v) for k, v in mapping.groupby("Section").size().to_dict().items()}
        if not mapping.empty else {}
    )

    return schemas.GenerateMappingResponse(
        rows=json.loads(mapping.to_json(orient="records")) if not mapping.empty else [],
        section_counts=section_counts,
        wizard_selection={
            "cgc_stages_answered": body.cgc_stages, "prc_stages_answered": body.prc_stages,
            "erc_stages_answered": body.erc_stages, "furnaces_answered": body.furnaces,
            "cgc_stages_kept": cgc_stages, "prc_stages_kept": prc_stages,
            "erc_stages_kept": erc_stages, "furnaces_kept": furnaces,
        },
    )


def commit_mapping(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    """Validates/normalizes the edited PI mapping grid and persists it to
    Config_file.xlsx immediately (the other 7 sheets are carried forward
    unchanged from the current on-disk config -- see _cfg_rows())."""
    df = pd.DataFrame(body.rows)
    normalized = wizard.normalize_pi_df(df) if not df.empty else df
    rows = json.loads(normalized.to_json(orient="records")) if not normalized.empty else []

    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["pi_mapping_rows"] = rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=rows)


def get_model_mapping(case_id: str = DEFAULT_CASE_ID) -> schemas.ModelMappingResponse:
    cfg = _load_config(case_id)
    df = _load_historian(case_id)
    return schemas.ModelMappingResponse(
        rows=json.loads(cfg.model_details_df.to_json(orient="records")) if not cfg.model_details_df.empty else [],
        historian_tags=sorted(df.columns.astype(str).tolist()),
    )


def commit_model_mapping(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["model_details_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def get_formulas(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.formulas_df.to_json(orient="records")) if not cfg.formulas_df.empty else []
    return schemas.RowsResponse(rows=rows)


def _sync_formula_inputs(model_details_rows: list, formula_rows: list) -> None:
    """Mutates model_details_rows in place: for every Predicted Parameter
    with a saved formula, writes the formula's referenced variable names
    into that row's own Input parameter_1..8 cells (truncated to 8 -- the
    config file's fixed-column schema), so engine.py's dependency graph
    (built off those exact cells, see engine.py::build_dependency_graph)
    schedules it after whatever it reads. Mirrors the frontend's
    ModelConfigTab.tsx::withSyncedInputs for Data-model rows' AI-selected X
    features -- same reasoning, just formula-driven instead."""
    input_cols = config_io.INPUT_PARAMETER_COLUMNS
    for formula_row in formula_rows:
        param = str(formula_row.get("Predicted parameter", "")).strip()
        expr = str(formula_row.get("Formula", "")).strip()
        if not param or not expr:
            continue
        try:
            names = formula_eval.extract_variable_names(expr)
        except formula_eval.FormulaError:
            continue
        for target in model_details_rows:
            if str(target.get("Predicted parameter", "")).strip() != param:
                continue
            for i, col in enumerate(input_cols):
                target[col] = names[i] if i < len(names) else ""
            break


def commit_formulas(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["formulas_rows"] = body.rows
    _sync_formula_inputs(payload["model_details_rows"], body.rows)
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def validate_formula(body: schemas.FormulaValidateRequest) -> schemas.FormulaValidateResponse:
    """Syntax/whitelist-only check (no historian row needed) -- lets the
    Formula Editor give immediate feedback while typing, before Save."""
    errors = formula_eval.validate_formula(body.formula)
    variables = [] if errors else formula_eval.extract_variable_names(body.formula)
    return schemas.FormulaValidateResponse(valid=not errors, errors=errors, variables=variables)


# ---------------------------------------------------------------------------
# New config sheets (Section Order, MV/DV/CV taglist, Constraints, User
# Inputs, Column Order, Target Section) -- same stateless echo-back pattern
# as get_pi_mapping()/commit_mapping() above: the client carries full sheet
# state per request, there's no server-side session to persist into except
# via the explicit save_config() call below.
# ---------------------------------------------------------------------------

def get_section_order(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.section_order_df.to_json(orient="records")) if not cfg.section_order_df.empty else []
    return schemas.RowsResponse(rows=rows)


def commit_section_order(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["section_order_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def get_mvdvcv_taglist(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.mvdvcv_df.to_json(orient="records")) if not cfg.mvdvcv_df.empty else []
    return schemas.RowsResponse(rows=rows)


def commit_mvdvcv_taglist(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["mvdvcv_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def get_constraints(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.constraints_df.to_json(orient="records")) if not cfg.constraints_df.empty else []
    return schemas.RowsResponse(rows=rows)


def commit_constraints(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["constraints_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def get_user_inputs(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.user_inputs_df.to_json(orient="records")) if not cfg.user_inputs_df.empty else []
    return schemas.RowsResponse(rows=rows)


def commit_user_inputs(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["user_inputs_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def get_column_order(case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    rows = json.loads(cfg.display_order_df.to_json(orient="records")) if not cfg.display_order_df.empty else []
    return schemas.RowsResponse(rows=rows)


def commit_column_order(body: schemas.MappingRowsRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.RowsResponse:
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["display_order_rows"] = body.rows
    _write_all_sheets(case_id=case_id, **payload)
    return schemas.RowsResponse(rows=body.rows)


def _target_section_response(section_order: List[str], target_section: str | None) -> schemas.TargetSectionResponse:
    active_scope = config_io.allowed_sections_upto(section_order, target_section)
    excluded = [s for s in section_order if s not in active_scope]
    return schemas.TargetSectionResponse(
        section_order=section_order, target_section=target_section,
        active_scope=active_scope, excluded_sections=excluded,
    )


def get_target_section(case_id: str = DEFAULT_CASE_ID) -> schemas.TargetSectionResponse:
    cfg = _load_config(case_id)
    return _target_section_response(cfg.section_order_list(), cfg.target_section)


def set_target_section(
    body: schemas.TargetSectionRequest, case_id: str = DEFAULT_CASE_ID
) -> schemas.TargetSectionResponse:
    """Persists the chosen target_section into Config_file.xlsx immediately
    (the other 7 sheets are carried forward unchanged). The Dashboard/Case
    Setup also hold it client-side (ActiveWhatIfContext) and pass it
    explicitly to compute/tag-options/validation-filter for the current
    session, independent of what's saved here."""
    cfg = _load_config(case_id)
    payload = _cfg_rows(cfg)
    payload["target_section"] = body.target_section
    _write_all_sheets(case_id=case_id, **payload)
    return _target_section_response(cfg.section_order_list(), body.target_section)


def _rows_to_df(rows: list, columns: list) -> pd.DataFrame:
    """pd.DataFrame(rows) on an empty list produces a DataFrame with zero
    columns, not just zero rows -- which then trips up any downstream
    consumer checking for a named column (e.g. "Section" in df.columns).
    Falls back to the sheet's known column set so a fully-cleared sheet
    (e.g. resetting to a blank case) still round-trips through
    config_io.load_all_config() cleanly."""
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=columns)


def _write_all_sheets(
    pi_mapping_rows: list,
    model_details_rows: list,
    constraints_rows: list,
    user_inputs_rows: list,
    display_order_rows: list,
    section_order_rows: list,
    mvdvcv_rows: list,
    target_section: str | None,
    case_id: str = DEFAULT_CASE_ID,
    formulas_rows: list | None = None,
) -> None:
    """Writes all 9 sheets to Config_file.xlsx in one call -- shared by
    save_config() (all sheets from the client at once) and every commit_X()
    below (only its own sheet changes; the others are the current on-disk
    values, passed straight through so a per-section save can't clobber
    anything else). formulas_rows defaults to None/empty so any existing
    caller that doesn't yet know about the Formulas sheet still works
    unchanged -- it just writes an empty Formulas sheet."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _rows_to_df(pi_mapping_rows, config_io.PI_COLUMNS).to_excel(
            writer, sheet_name="PI_generalised_Name", index=False
        )
        _rows_to_df(model_details_rows, config_io.MODEL_DETAILS_COLUMNS).to_excel(
            writer, sheet_name="Model details", index=False
        )
        _rows_to_df(constraints_rows, config_io.CONSTRAINTS_COLUMNS).to_excel(
            writer, sheet_name="Constraints", index=False
        )
        _rows_to_df(user_inputs_rows, config_io.USER_INPUTS_COLUMNS).to_excel(
            writer, sheet_name="user inputs", index=False
        )
        _rows_to_df(display_order_rows, config_io.DISPLAY_ORDER_COLUMNS).to_excel(
            writer, sheet_name="display_column_order", index=False
        )
        _rows_to_df(section_order_rows, config_io.SECTION_ORDER_COLUMNS).to_excel(
            writer, sheet_name="Section Order", index=False
        )
        _rows_to_df(mvdvcv_rows, config_io.MVDVCV_COLUMNS).to_excel(
            writer, sheet_name="MV_DV_CV_taglist", index=False
        )
        pd.DataFrame({"Target Section": [target_section or ""]}).to_excel(
            writer, sheet_name="Target Section", index=False
        )
        _rows_to_df(formulas_rows or [], config_io.FORMULAS_COLUMNS).to_excel(
            writer, sheet_name="Formulas", index=False
        )

    try:
        _atomic_write_bytes(paths.config_file(case_id), buf.getvalue())
    except OSError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Could not save the configuration to {paths.config_file(case_id)}: {e}. "
                "This usually means the file is currently open in Excel or being synced by OneDrive/cloud "
                "storage — close it and try again."
            ),
        )


def _cfg_rows(cfg: WhatIfConfig) -> Dict[str, Any]:
    """Every sheet's current on-disk rows, in the exact shape each get_X()
    above already returns them -- used by commit_X() below to carry the 7
    untouched sheets forward unchanged while only the one being edited
    changes."""
    def _rows(df: pd.DataFrame) -> list:
        return json.loads(df.to_json(orient="records")) if not df.empty else []

    pi_normalized = wizard.normalize_pi_df(cfg.pi_names_df)
    return {
        "pi_mapping_rows": _rows(pi_normalized),
        "model_details_rows": _rows(cfg.model_details_df),
        "constraints_rows": _rows(cfg.constraints_df),
        "user_inputs_rows": _rows(cfg.user_inputs_df),
        "display_order_rows": _rows(cfg.display_order_df),
        "section_order_rows": _rows(cfg.section_order_df),
        "mvdvcv_rows": _rows(cfg.mvdvcv_df),
        "formulas_rows": _rows(cfg.formulas_df),
        "target_section": cfg.target_section,
    }


def save_config(body: schemas.ConfigSaveRequest, case_id: str = DEFAULT_CASE_ID) -> schemas.ConfigStatusResponse:
    """Writes all 9 sheets to Config_file.xlsx in one call -- the wizard's
    primary persistence path, replacing the download-then-reupload round trip
    export_config()/upload_config() otherwise requires. The wizard's own
    ConfigSaveRequest doesn't carry Formulas rows (that sheet belongs to
    Model Definition's Formula Editor, saved separately via commit_formulas)
    -- current on-disk formulas are carried forward unchanged here, same as
    every commit_X()'s _cfg_rows() pattern, so this unrelated save can't
    silently wipe them."""
    cfg = _load_config(case_id)
    formulas_rows = json.loads(cfg.formulas_df.to_json(orient="records")) if not cfg.formulas_df.empty else []
    _write_all_sheets(
        pi_mapping_rows=body.pi_mapping_rows,
        model_details_rows=body.model_details_rows,
        constraints_rows=body.constraints_rows,
        user_inputs_rows=body.user_inputs_rows,
        display_order_rows=body.display_order_rows,
        section_order_rows=body.section_order_rows,
        mvdvcv_rows=body.mvdvcv_rows,
        target_section=body.target_section,
        case_id=case_id,
        formulas_rows=formulas_rows,
    )
    return get_config_status(case_id)


_corr_cache: Dict[str, Dict[str, Any]] = {}
_corr_cache_lock = threading.Lock()


def get_correlation_matrix(case_id: str = DEFAULT_CASE_ID) -> schemas.CorrelationMatrixResponse:
    path = paths.training_workbook(case_id)
    if not os.path.isfile(path):
        # No training workbook uploaded for this case yet -- same "not an
        # error" treatment as _load_historian()/_load_config(): an empty
        # matrix, not a 404 that would otherwise leave stale cached data
        # from a previously-active case on screen.
        return schemas.CorrelationMatrixResponse(columns=[], matrix=[], n_rows=0)
    mtime = os.path.getmtime(path)
    with _corr_cache_lock:
        entry = _corr_cache.get(case_id)
        corr = entry["corr"] if entry and entry["path"] == path and entry["mtime"] == mtime else None
    if corr is None:
        df = _load_historian(case_id)
        corr = df.corr(method="pearson", numeric_only=True).round(4)
        with _corr_cache_lock:
            _corr_cache[case_id] = {"path": path, "mtime": mtime, "corr": corr}

    matrix = [[None if pd.isna(v) else float(v) for v in row] for row in corr.to_numpy()]
    return schemas.CorrelationMatrixResponse(columns=corr.columns.tolist(), matrix=matrix, n_rows=len(corr))


def get_accuracy_summary(case_id: str = DEFAULT_CASE_ID) -> schemas.AccuracySummaryResponse:
    path = os.path.join(paths.model_dir(case_id), "Model_accuracy_summary.csv")
    if not os.path.isfile(path):
        return schemas.AccuracySummaryResponse(rows=[], available=False)
    df = pd.read_csv(path)
    rows = json.loads(df.to_json(orient="records"))
    return schemas.AccuracySummaryResponse(rows=rows, available=True)


def export_config(body: schemas.ConfigExportRequest):
    pi_df = pd.DataFrame(body.pi_mapping_rows)
    model_df = pd.DataFrame(body.model_details_rows)

    if body.format == "csv":
        buf = io.StringIO()
        pi_df.to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8"), "text/csv", "Generated_PI_mapping.csv"

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pi_df.to_excel(writer, sheet_name="PI_generalised_Name", index=False)
        model_df.to_excel(writer, sheet_name="Model details", index=False)
        pd.DataFrame(body.constraints_rows).to_excel(writer, sheet_name="Constraints", index=False)
        pd.DataFrame(body.user_inputs_rows).to_excel(writer, sheet_name="user inputs", index=False)
        pd.DataFrame(body.display_order_rows).to_excel(writer, sheet_name="display_column_order", index=False)
        pd.DataFrame(body.section_order_rows).to_excel(writer, sheet_name="Section Order", index=False)
        pd.DataFrame(body.mvdvcv_rows).to_excel(writer, sheet_name="MV_DV_CV_taglist", index=False)
        pd.DataFrame({"Target Section": [body.target_section or ""]}).to_excel(
            writer, sheet_name="Target Section", index=False
        )
        pd.DataFrame(body.formulas_rows).to_excel(writer, sheet_name="Formulas", index=False)
    return (
        buf.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Config_file.xlsx",
    )


async def upload_training_data(
    file: UploadFile, case_id: str = DEFAULT_CASE_ID
) -> schemas.TrainingDataUploadResponse:
    data = await file.read()
    try:
        xl = pd.ExcelFile(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Could not parse workbook: {e}")

    required = ["PI data", "Furnace data"]
    missing = [s for s in required if s not in xl.sheet_names]
    if missing:
        return schemas.TrainingDataUploadResponse(
            saved=False, sheets_found=list(xl.sheet_names), missing_sheets=missing,
        )

    try:
        _atomic_write_bytes(paths.training_workbook(case_id), data)
    except OSError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The workbook was read successfully, but saving it to "
                f"{paths.training_workbook(case_id)} failed: {e}. "
                "This usually means the file is currently open in Excel or being synced by OneDrive/cloud "
                "storage — close it and try again."
            ),
        )
    return schemas.TrainingDataUploadResponse(saved=True, sheets_found=list(xl.sheet_names), missing_sheets=[])


def _model_mapping_filled(case_id: str = DEFAULT_CASE_ID) -> bool:
    try:
        cfg = _load_config(case_id)
    except HTTPException:
        return False
    return not cfg.model_details_df.dropna(how="all").empty


def get_models_status(case_id: str = DEFAULT_CASE_ID) -> schemas.ModelStatusResponse:
    try:
        cfg = _load_config(case_id)
        required_tags = model_status.required_kalman_tags(cfg.model_details_df, case_id)
    except HTTPException:
        required_tags = []
    status = model_status.check_models_trained(paths.model_dir(case_id), required_tags)
    raw_sim_present = os.path.isfile(paths.historian_file(case_id))
    training_data_present = os.path.isfile(paths.training_workbook(case_id))
    mapping_filled = _model_mapping_filled(case_id)

    # Mirrors Whatif_streamlit_dashboard.py's _train_blockers checklist.
    blockers: List[str] = []
    if not os.path.isfile(paths.whatif_train_script()):
        blockers.append("Training script not found under Scripts/")
    if not training_data_present:
        blockers.append("Training dataset not saved yet (Step A)")
    if not mapping_filled:
        blockers.append("The Model Mapping sheet is still empty")

    return schemas.ModelStatusResponse(
        all_present=status.all_present,
        tags_ok=status.tags_ok,
        tags_missing=status.tags_missing,
        pkl_count=status.pkl_count,
        required_pkl_count=len(required_tags) * 3,
        raw_sim_present=raw_sim_present,
        training_data_present=training_data_present,
        model_mapping_filled=mapping_filled,
        can_train=not blockers,
        train_blockers=blockers,
        # Mirrors Streamlit's _results_ready gate: training is only required
        # when neither the historian nor a full set of model artifacts exist.
        training_required=not (raw_sim_present or status.all_present),
    )


def _run_training_subprocess(case_id: str = DEFAULT_CASE_ID) -> Dict[str, Any]:
    """Runs the legacy training script exactly as the Streamlit reference did
    (subprocess, cwd=Scripts/ so its "..\\Data"/"..\\Results" relative paths
    resolve to the repo root), then re-checks the artifacts it should have
    produced.

    Case-awareness reuses the script's own pre-existing multi-PLANT_NAME
    folder resolution (_resolve_plant_dir: prefer Data/<PLANT_NAME> and
    Results/<PLANT_NAME>, else fall back to the flat layout) — setting
    PLANT_NAME=<case_id> for a non-default case makes it read/write
    Data/<case_id>/... and Results/<case_id>/... unchanged, exactly mirroring
    how every other case-scoped path in this app resolves (see paths.py's
    _case_dir). The default case leaves PLANT_NAME unset, so it keeps
    resolving to the original flat Data/Results layout.

    The script reads "<CONFIG_DIR>/Config_file.xlsx" for the Model details
    sheet — the same single file Data/<case_id>/Config_file.xlsx that What-If
    Setup's UI itself reads and writes (see config_file()/_load_config()) —
    so there is exactly one config file per case, always current; no
    separate "_updated" snapshot/copy step is needed."""
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"  # suppress plt.show() pop-ups in a headless subprocess
    env["WHATIF_CASE_ID"] = case_id
    if case_id != DEFAULT_CASE_ID:
        env["PLANT_NAME"] = case_id
    proc = subprocess.run(
        [sys.executable, paths.whatif_train_script()],
        cwd=paths.scripts_dir(),
        env=env,
        capture_output=True,
        text=True,
    )
    try:
        cfg = config_io.load_all_config(paths.config_file(case_id))
        required_tags = model_status.required_kalman_tags(cfg.model_details_df, case_id)
    except (config_io.ConfigSchemaError, OSError):
        required_tags = []
    status = model_status.check_models_trained(paths.model_dir(case_id), required_tags)
    raw_sim_present = os.path.isfile(paths.historian_file(case_id))
    success = proc.returncode == 0 and (status.pkl_count > 0 or raw_sim_present)
    return {
        "success": success,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-8000:],
        "stderr_tail": (proc.stderr or "")[-8000:],
        "pkl_count": status.pkl_count,
        "all_present": status.all_present,
        "raw_sim_present": raw_sim_present,
    }


def train_models(case_id: str = DEFAULT_CASE_ID) -> str:
    status = get_models_status(case_id)
    if not status.can_train:
        raise HTTPException(status_code=422, detail="; ".join(status.train_blockers))
    return job_manager.submit(_run_training_subprocess, case_id, progress_mode="none")


# ---------------------------------------------------------------------------
# Dashboard: tag resolution, timestamps, baseline, scenario compute
# ---------------------------------------------------------------------------

def _limits_for(tags: List[str], df: pd.DataFrame, cfg: WhatIfConfig) -> Dict[str, Dict[str, float]]:
    """Config-sheet limits first, historical min/max as fallback (ported from
    Whatif_streamlit_dashboard.py's _limits_for)."""
    config_limits: Dict[str, Any] = {}
    ui = cfg.user_inputs_df
    if {"Parameter", "Lower Limit", "Upper Limit"}.issubset(ui.columns):
        dl = ui.copy()
        dl["Parameter"] = dl["Parameter"].astype(str).str.strip()
        dl = dl[dl["Parameter"].str.lower() != "nan"]
        config_limits = dl.set_index("Parameter")[["Lower Limit", "Upper Limit"]].to_dict("index")

    out: Dict[str, Dict[str, float]] = {}
    for tag in tags:
        cfg_lim = config_limits.get(tag)
        lo = pd.to_numeric(pd.Series([cfg_lim.get("Lower Limit")]), errors="coerce").iloc[0] if cfg_lim else None
        hi = pd.to_numeric(pd.Series([cfg_lim.get("Upper Limit")]), errors="coerce").iloc[0] if cfg_lim else None
        if pd.notna(lo) and pd.notna(hi):
            out[tag] = {"lower": float(lo), "upper": float(hi)}
        elif tag in df.columns and pd.api.types.is_numeric_dtype(df[tag]):
            out[tag] = {"lower": float(df[tag].min()), "upper": float(df[tag].max())}
        else:
            out[tag] = {"lower": 0.0, "upper": 1e6}
    return out


def _load_plugin():
    """Plain package import, cheap after the first call (Python module
    cache) -- no need for a separate mtime-based cache like config/historian."""
    return plants.load_plant_formulas()


def get_tag_options(
    body: schemas.TagOptionsRequest, case_id: str = DEFAULT_CASE_ID
) -> schemas.TagOptionsResponse:
    """3-tier source resolution: wizard-generated tags -> config 'user inputs'
    sheet -> full historian dropdown fallback (ported from the dashboard tab's
    Source A/B/C logic). When target_section is given, all_tags is scoped to
    PI tags belonging to the target section or an upstream one."""
    cfg = _load_config(case_id)
    df = _load_historian(case_id)
    all_tags = sorted(df.columns.astype(str).tolist())

    if body.target_section and not cfg.pi_names_df.empty and "Section" in cfg.pi_names_df.columns:
        allowed = {
            s.strip().lower()
            for s in config_io.allowed_sections_upto(cfg.section_order_list(), body.target_section)
        }
        pi_norm = wizard.normalize_pi_df(cfg.pi_names_df)
        # The historian's columns are named after "Generalized Description"
        # (e.g. "CGC_STAGE_1_SUCTION_PRESSURE"), not "Pi_tags" (the raw PI
        # point name, e.g. "YN.ETH1.13P185") — scope against the former.
        scoped_tags = set(
            pi_norm.loc[
                pi_norm["Section"].astype(str).str.strip().str.lower().isin(allowed), "Generalized Description"
            ]
        )
        if scoped_tags:
            all_tags = sorted(t for t in all_tags if t in scoped_tags)

    generated_tags = sorted(t for t in body.generated_tags if t in df.columns)

    ui = cfg.user_inputs_df
    config_tags: List[str] = []
    if {"Parameter", "Lower Limit", "Upper Limit"}.issubset(ui.columns):
        dl = ui.copy()
        dl["Parameter"] = dl["Parameter"].astype(str).str.strip()
        config_tags = [t for t in dl["Parameter"].tolist() if t.lower() != "nan"]

    if generated_tags:
        source, tags = "wizard", generated_tags
    elif config_tags:
        source, tags = "config", config_tags
    else:
        source, tags = "historian", []

    limits = _limits_for(tags, df, cfg)
    return schemas.TagOptionsResponse(tags=tags, all_tags=all_tags, source=source, limits=limits)


def get_dates(case_id: str = DEFAULT_CASE_ID) -> schemas.DatesResponse:
    df = _load_historian(case_id)
    dates = sorted(pd.Series(df.index.date).unique())
    return schemas.DatesResponse(dates=[d.isoformat() for d in dates])


def get_timestamps(date: str, case_id: str = DEFAULT_CASE_ID) -> schemas.TimestampsResponse:
    df = _load_historian(case_id)
    try:
        target = pd.Timestamp(date).date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {date}")
    stamps = sorted(df.index[df.index.date == target])
    return schemas.TimestampsResponse(timestamps=[ts.strftime("%Y-%m-%d %H:%M:%S") for ts in stamps])


def get_baseline(timestamp: str, tags: List[str], case_id: str = DEFAULT_CASE_ID) -> schemas.BaselineResponse:
    df = _load_historian(case_id)
    ts = pd.Timestamp(timestamp)
    if ts not in df.index:
        raise HTTPException(status_code=404, detail=f"Timestamp {timestamp} not found in historian.")
    active_tags = [t for t in tags if t in df.columns] or df.columns.tolist()
    row = df.loc[[ts], active_tags].T
    row.columns = ["value"]
    values: Dict[str, Any] = {}
    for tag, val in row["value"].items():
        if pd.isna(val):
            values[tag] = None
            continue
        try:
            values[tag] = float(val)
        except (TypeError, ValueError):
            values[tag] = str(val)
    return schemas.BaselineResponse(values=values)


def run_scenario(
    body: schemas.WhatIfScenarioRequest, case_id: str = DEFAULT_CASE_ID
) -> schemas.WhatIfScenarioResponse:
    """The core call: loads historian + config once, runs whatif_analysis()
    exactly once. Never decomposed into per-tag endpoints — the pipeline is
    order-dependent with a mid-pipeline constraint short-circuit."""
    df = _load_historian(case_id)
    cfg = _load_config(case_id)
    try:
        ts = pd.Timestamp(body.timestamp)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid timestamp: {body.timestamp}")
    if ts not in df.index:
        raise HTTPException(status_code=404, detail=f"Timestamp {body.timestamp} not found in historian.")

    user_input_df = pd.DataFrame(
        [{"Parameter": o.parameter, "Value": o.value} for o in body.overrides],
        columns=["Parameter", "Value"],
    )

    output_path = None
    if body.write_actual_vs_estimated_xlsx:
        output_path = paths.actual_vs_estimated_file(ts.strftime("%Y%m%d_%H%M%S"), case_id)

    plugin = _load_plugin()
    try:
        result = engine.whatif_analysis(
            df, ts, user_input_df, cfg, paths.model_dir(case_id),
            plugin=plugin,
            target_section=body.target_section,
            write_actual_vs_estimated_xlsx=body.write_actual_vs_estimated_xlsx,
            output_path=output_path,
            case_id=case_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"A required model artifact is missing: {e}")

    all_keys = sorted(k for k in (set(result.actual.keys()) | set(result.estimated.keys())) if k != "Timestamp")
    all_keys = kpi.apply_preferred_order(all_keys, cfg.display_order_df)
    rows: List[schemas.WhatIfScenarioRow] = []
    for key in all_keys:
        act = result.actual.get(key)
        est = result.estimated.get(key)
        try:
            change = float(est) - float(act)
        except (TypeError, ValueError):
            change = None
        rows.append(schemas.WhatIfScenarioRow(parameter=key, actual=act, estimated=est, change=change))

    # Same section resolution engine.whatif_analysis() itself uses (a
    # request-supplied target_section wins; otherwise fall back to the
    # saved config's), so the KPI cards reflect exactly the scope the
    # scenario was actually computed against — mirrors
    # Whatif_streamlit_dashboard_updated.py's KPI cards, which only show
    # tiles for the target section and everything upstream of it.
    resolved_target_section = body.target_section if body.target_section is not None else cfg.target_section
    allowed_sections = config_io.allowed_sections_upto(cfg.section_order_list(), resolved_target_section)
    section_map = kpi.build_param_section_map(cfg)

    kpis: List[schemas.WhatIfKpi] = []
    kpi_tags = kpi.scope_to_target_section(kpi.derive_kpi_tags(cfg, plugin), section_map, allowed_sections)
    kpi_tags = kpi.apply_preferred_order(kpi_tags, cfg.display_order_df)
    for tag in kpi_tags:
        try:
            act_f = float(result.actual.get(tag))
            est_f = float(result.estimated.get(tag))
        except (TypeError, ValueError):
            continue
        kpis.append(schemas.WhatIfKpi(tag=tag, actual=act_f, estimated=est_f, change=est_f - act_f))

    return schemas.WhatIfScenarioResponse(
        constraint_hit=result.constraint_hit,
        constraint_message=result.constraint_message,
        rows=rows,
        kpis=kpis,
    )


def run_validation_filter(
    body: schemas.ValidationFilterRequest, case_id: str = DEFAULT_CASE_ID
) -> schemas.ValidationFilterResponse:
    """Default shortlist of filterable parameters: the same derived tag set
    used for KPI tiles (see kpi.derive_kpi_tags's docstring for why there's
    no clean upstream equivalent of the old hardcoded VALIDATION_TAGS list)."""
    df = _load_historian(case_id)
    cfg = _load_config(case_id)
    plugin = _load_plugin()
    available = [t for t in kpi.derive_kpi_tags(cfg, plugin) if t in df.columns]
    available = kpi.apply_preferred_order(available, cfg.display_order_df)
    filtered = df.copy()
    for tag in available:
        criterion = body.filters.get(tag)
        if criterion is None:
            continue
        if pd.api.types.is_numeric_dtype(filtered[tag]):
            lo = criterion.min if criterion.min is not None else float(df[tag].min())
            hi = criterion.max if criterion.max is not None else float(df[tag].max())
            filtered = filtered[(filtered[tag] >= lo) & (filtered[tag] <= hi)]
        elif criterion.values is not None:
            filtered = filtered[filtered[tag].isin(criterion.values)]

    display = filtered[available].reset_index() if available else filtered.reset_index()
    rows = json.loads(display.to_json(orient="records", date_format="iso"))
    return schemas.ValidationFilterResponse(rows=rows, match_count=len(filtered))


def export_scenario_csv(body: "schemas.WhatIfExportCsvRequest"):
    """Merged scenario + validation CSV export. Simplified relative to the
    original's pandas merge-on-Parameter (which joined a transposed scenario
    table against a transposed validation table): here the two tables are
    written as clearly-labeled sections in one CSV, since the client already
    has both JSON payloads and a literal structural merge would be fragile to
    reproduce exactly server-side without re-deriving the original's index
    alignment assumptions."""
    scenario_df = pd.DataFrame([r.model_dump() for r in body.rows])
    scenario_df.insert(0, "Selected Timestamp", body.timestamp)

    buf = io.StringIO()
    scenario_df.to_csv(buf, index=False)
    if body.validation_rows:
        buf.write("\nHistorical Validation Matches\n")
        pd.DataFrame(body.validation_rows).to_csv(buf, index=False)

    filename = "filtered_validation_data.csv" if body.validation_rows else "WhatIf_Result.csv"
    return buf.getvalue().encode("utf-8"), "text/csv", filename
