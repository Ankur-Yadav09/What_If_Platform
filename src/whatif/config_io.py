"""
src/whatif/config_io.py
========================
Loads every relevant sheet from Config_file.xlsx into one WhatIfConfig
object, passed explicitly into the engine (src/whatif/engine.py) instead
of being re-read from disk on every call, as the original
Scripts/whatif_runner.py did.

Sheet -> field mapping (matches Scripts/Whatif_streamlit_dashboard_updated.py's
SHEET_TO_STATE, tolerant of the two extra unused sheets that exist on the
real Config_file.xlsx: "process_param_stats" and "Model details_copy",
which are simply ignored).

Schema history: the original (5-sheet) config had no process-flow concept —
every predicted parameter was always computed. The generalized schema adds
"Section Order" (the plant's process-flow sequence) and "Target Section" (a
single-cell sheet naming which section the current case setup is scoped up
to), plus "MV_DV_CV_taglist" (an alternative/prioritized input-tag source for
Model Mapping). All three are optional for backward compatibility with
older-shaped workbooks: they default to empty/None rather than raising, and
src/whatif/engine.py's section-scoping is a no-op when they're absent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

# The real Constraints sheet on disk historically used this misspelled column
# name. Some re-exported workbooks now use the corrected spelling instead —
# constraints_max_col() below resolves whichever is actually present so
# neither reading nor writing code has to hardcode one variant.
CONSTRAINTS_MAX_COL = "Max vlaue"
_CONSTRAINTS_MAX_COL_VARIANTS = ["Max vlaue", "Max value"]

USER_INPUTS_COLUMNS = ["Parameter", "Value", "Lower Limit", "Upper Limit", "Remark"]
CONSTRAINTS_COLUMNS = [
    "Parameter", "user input value", CONSTRAINTS_MAX_COL, "UOM", "Remark",
    "Linked Parameter", "Action",
]
DISPLAY_ORDER_COLUMNS = ["Sr.no", "Preferred columns"]
INPUT_PARAMETER_COLUMNS = [f"Input parameter_{i}" for i in range(1, 9)]
MODEL_DETAILS_COLUMNS = ["Predicted parameter", "Section"] + INPUT_PARAMETER_COLUMNS + ["model type"]
PI_COLUMNS = ["Pi_tags", "Generalized Description", "Section"]
SECTION_ORDER_COLUMNS = ["Sr.no", "Section"]
MVDVCV_COLUMNS = ["Name", "GeneralizedDescription", "Section", "Type"]
# One row per Predicted Parameter with Model Type = "First principle" whose
# value is computed from a user-typed math expression (Model Definition's
# Formula Editor) instead of a hardcoded plant plug-in function -- see
# src/whatif/formula_eval.py for the safe evaluator and
# engine.py::collect_formula_functions for how it's wired into the same
# simulation slot the plug-in would otherwise fill. New, optional sheet:
# absent entirely on older workbooks, same backward-compatible convention as
# Section Order/Target Section/MV_DV_CV_taglist (see module docstring).
FORMULAS_COLUMNS = ["Predicted parameter", "Formula"]

_SHEET_TO_FIELD = {
    "user inputs": "user_inputs_df",
    "model details": "model_details_df",
    "constraints": "constraints_df",
    "display_column_order": "display_order_df",
    "pi_generalised_name": "pi_names_df",
    "section order": "section_order_df",
    "mv_dv_cv_taglist": "mvdvcv_df",
    "formulas": "formulas_df",
}

_TARGET_SECTION_SHEET_NORM = "targetsection"


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _norm_col(name: str) -> str:
    """Same normalization as _norm_name, applied to column headers so
    'GeneralizedDescription' and 'Generalized Description' (both seen on real
    workbooks) resolve to the same canonical field."""
    return _norm_name(name)


_SHEET_LOOKUP_NORM = {_norm_name(k): v for k, v in _SHEET_TO_FIELD.items()}


def match_sheet_to_field(sheet_name: str) -> str | None:
    """Maps a workbook sheet name to a WhatIfConfig field name, tolerant of
    spacing/casing variants (ported from Whatif_streamlit_dashboard.py's
    _match_sheet_to_state). Returns None for the Target Section sheet and any
    unrecognized sheet — Target Section is handled separately since it's a
    scalar, not a DataFrame field."""
    n = _norm_name(sheet_name)
    if n == _TARGET_SECTION_SHEET_NORM:
        return None
    if n in _SHEET_LOOKUP_NORM:
        return _SHEET_LOOKUP_NORM[n]
    if "pi" in n and ("general" in n or "generalis" in n or "generaliz" in n):
        return "pi_names_df"
    # Tolerant of any MV/DV/CV letter ordering + "taglist"/"tag list" spacing
    # (e.g. a workbook sheet literally named "MV_CV_DV Tag List") — not just
    # the exact "mv_dv_cv_taglist" spelling in _SHEET_TO_FIELD above.
    if "mv" in n and "dv" in n and "cv" in n and "tag" in n:
        return "mvdvcv_df"
    return None


def is_target_section_sheet(sheet_name: str) -> bool:
    return _norm_name(sheet_name) == _TARGET_SECTION_SHEET_NORM


class ConfigSchemaError(ValueError):
    """Raised when a loaded sheet doesn't have the columns the engine needs."""


def _require_columns(df: pd.DataFrame, required: list[str], sheet_label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ConfigSchemaError(
            f"Sheet '{sheet_label}' is missing expected column(s) {missing}. "
            f"Found columns: {list(df.columns)}"
        )


def _rename_tolerant_columns(df: pd.DataFrame, canonical: list[str]) -> pd.DataFrame:
    """Renames any column whose normalized form matches a normalized entry in
    `canonical` to that canonical spelling, leaving unmatched columns as-is."""
    if df.empty:
        return df
    canon_lookup = {_norm_col(c): c for c in canonical}
    rename_map = {}
    for col in df.columns:
        canon = canon_lookup.get(_norm_col(col))
        if canon is not None and canon != col:
            rename_map[col] = canon
    return df.rename(columns=rename_map) if rename_map else df


def constraints_max_col(df: pd.DataFrame) -> str:
    """Returns whichever of the known Max-value column spellings is actually
    present on `df` (both `"Max vlaue"` and the corrected `"Max value"` are
    seen on real workbooks). Falls back to the historical misspelled default
    if neither is present (e.g. an empty/placeholder frame)."""
    for variant in _CONSTRAINTS_MAX_COL_VARIANTS:
        if variant in df.columns:
            return variant
    return CONSTRAINTS_MAX_COL


def input_param_cols(model_details_df: pd.DataFrame) -> list[str]:
    """Name-based (not positional) list of a Model details row's
    'Input parameter_N' columns. Positional slicing breaks once Section/model
    type columns sit between 'Predicted parameter' and the first input column."""
    return [c for c in model_details_df.columns if str(c).strip().lower().startswith("input parameter")]


def model_type_col(model_details_df: pd.DataFrame) -> str | None:
    for c in model_details_df.columns:
        n = str(c).strip().lower()
        if n in ("model", "model type"):
            return c
    return None


def _is_data_model(value) -> bool:
    """Blank/NaN defaults to a data-driven (Kalman) model, matching the
    reference scripts' convention."""
    text = str(value).strip().lower() if pd.notna(value) else ""
    return text in ("", "data model", "data", "nan")


def non_data_model_parameters(model_details_df: pd.DataFrame) -> set[str]:
    """Predicted parameters whose model type marks them as simulation/
    first-principle (computed via a plugin, not trained as a Kalman filter)."""
    if model_details_df is None or model_details_df.empty:
        return set()
    col = model_type_col(model_details_df)
    if col is None:
        return set()
    mask = ~model_details_df[col].map(_is_data_model)
    return set(model_details_df.loc[mask, "Predicted parameter"].astype(str))


def section_col(model_details_df: pd.DataFrame) -> str | None:
    for c in model_details_df.columns:
        if str(c).strip().lower() == "section":
            return c
    return None


def allowed_sections_upto(section_order: list[str], target_section: str | None) -> list[str]:
    """Every section at or before `target_section` in `section_order`
    (process-flow order), i.e. upstream sections + the target itself, no
    downstream. Case/whitespace-insensitive match (real workbooks have been
    seen with inconsistent casing between Section Order and Target Section).
    Returns the full `section_order` if `target_section` is None/blank or not
    found (no scoping applied)."""
    if not section_order or not target_section:
        return list(section_order or [])
    norm_order = [str(s).strip().lower() for s in section_order]
    t = str(target_section).strip().lower()
    if t not in norm_order:
        return list(section_order)
    idx = norm_order.index(t)
    return list(section_order)[: idx + 1]


@dataclass
class WhatIfConfig:
    user_inputs_df: pd.DataFrame
    constraints_df: pd.DataFrame
    display_order_df: pd.DataFrame
    model_details_df: pd.DataFrame
    pi_names_df: pd.DataFrame
    section_order_df: pd.DataFrame
    mvdvcv_df: pd.DataFrame
    formulas_df: pd.DataFrame
    target_section: str | None = None

    def section_order_list(self) -> list[str]:
        if self.section_order_df is None or self.section_order_df.empty or "Section" not in self.section_order_df:
            return []
        return [str(s) for s in self.section_order_df["Section"].tolist() if pd.notna(s) and str(s).strip()]


def _read_sheet(xl: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(xl, sheet_name=sheet_name).dropna(how="all").reset_index(drop=True)


def _read_target_section(xl: pd.ExcelFile, sheet_name: str) -> str | None:
    df = pd.read_excel(xl, sheet_name=sheet_name)
    df = df.dropna(how="all")
    if df.empty:
        return None
    if "Target Section" in df.columns:
        val = df["Target Section"].iloc[0]
    else:
        val = df.iloc[0, 0]
    if pd.isna(val) or not str(val).strip():
        return None
    return str(val).strip()


def load_all_config(path: str) -> WhatIfConfig:
    """Reads every recognised sheet from Config_file.xlsx once. Unknown/unused
    sheets (process_param_stats, Model details_copy) are silently ignored.

    Uses `with` to explicitly close the underlying OS file handle as soon as
    reading is done. pd.ExcelFile(path) opened from a string path does NOT
    reliably release its Windows file handle just because the object goes out
    of scope — it depends on the cyclic GC running, not plain refcounting,
    since the ExcelFile/openpyxl workbook hold circular references to each
    other. Without an explicit close, every call to this function (which is
    every What-If Studio config/wizard endpoint) leaks a handle on
    Config_file.xlsx; since these endpoints are hit constantly (React Query
    refetch-on-focus, wizard actions, etc.), the file stays locked almost
    continuously, causing uploads/replacements of this same file to fail with
    a persistent (not transient) WinError 5 Access Denied."""
    found: dict[str, pd.DataFrame] = {}
    target_section: str | None = None
    with pd.ExcelFile(path) as xl:
        for sheet in xl.sheet_names:
            if is_target_section_sheet(sheet):
                target_section = _read_target_section(xl, sheet)
                continue
            field = match_sheet_to_field(sheet)
            if field is None or field in found:
                continue
            found[field] = _read_sheet(xl, sheet)

    user_inputs_df = found.get("user_inputs_df", pd.DataFrame(columns=USER_INPUTS_COLUMNS))
    constraints_df = found.get("constraints_df", pd.DataFrame(columns=CONSTRAINTS_COLUMNS))
    display_order_df = found.get("display_order_df", pd.DataFrame(columns=DISPLAY_ORDER_COLUMNS))
    model_details_df = found.get("model_details_df", pd.DataFrame(columns=MODEL_DETAILS_COLUMNS))
    pi_names_df = found.get("pi_names_df", pd.DataFrame(columns=PI_COLUMNS))
    section_order_df = found.get("section_order_df", pd.DataFrame(columns=SECTION_ORDER_COLUMNS))
    mvdvcv_df = found.get("mvdvcv_df", pd.DataFrame(columns=MVDVCV_COLUMNS))
    formulas_df = found.get("formulas_df", pd.DataFrame(columns=FORMULAS_COLUMNS))

    pi_names_df = _rename_tolerant_columns(pi_names_df, PI_COLUMNS)
    mvdvcv_df = _rename_tolerant_columns(mvdvcv_df, MVDVCV_COLUMNS)

    if not constraints_df.empty:
        max_col = constraints_max_col(constraints_df)
        _require_columns(constraints_df, ["Parameter", "user input value", max_col], "Constraints")
    if not model_details_df.empty:
        _require_columns(model_details_df, ["Predicted parameter"], "Model details")

    return WhatIfConfig(
        user_inputs_df=user_inputs_df,
        constraints_df=constraints_df,
        display_order_df=display_order_df,
        model_details_df=model_details_df,
        pi_names_df=pi_names_df,
        section_order_df=section_order_df,
        mvdvcv_df=mvdvcv_df,
        formulas_df=formulas_df,
        target_section=target_section,
    )
