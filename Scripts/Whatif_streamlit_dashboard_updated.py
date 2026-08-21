
# -*- coding: utf-8 -*-
"""
Multi-Plant Enterprise What-If Platform
====================================================================
PART-1 : Imports | Page Config | CSS | Historian loading |
         PI_generalised_Name loading | Session states |
         Tag segregation functions
PART-2 : Configuration Hub | Plant Configuration Wizard |
         CGC / PRC / ERC stage selection | Furnace selection |
         Automatic PI mapping generation | Mapping export
PART-3 : What-if Dashboard | Generated tag selection |
         Timestamp selection | Baseline values |
         User override inputs | whatif_analysis execution
PART-4 : KPI cards | Actual vs Estimated table |
         Change highlighting | Historical validation | CSV export
====================================================================
"""

# =====================================================================
# PART-1  |  IMPORTS
# =====================================================================
import io
import json
import os
import re
import tempfile
import traceback
import subprocess
import sys
from glob import glob

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------
# Model-training file layout (matches Model_development_and_
# static_whatif_testing.py, which reads "..\Data" and writes
# "..\Results\Model" relative to its own folder):
#
#   <parent>/
#     ├── Data/DMC_Screen_tags_data.xlsx   (sheet 'PI data' and/or 'Furnace data')
#     ├── Data/Config_file_updated.xlsx            (PI mapping + Model details)
#     ├── Results/Model/*.pkl              (trained model artefacts)
#     └── <app folder>/Whatif_streamlit_dashboard.py
#                       Model_development_and_static_whatif_testing.py
# =====================================================================
# PART-1  |  PAGE CONFIG  (must be the first Streamlit call)
# =====================================================================
st.set_page_config(
    page_title="What-If Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_SCRIPT = os.path.join(APP_DIR, "Model_development_and_static_whatif_testing.py")
DATA_BASE_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "Data"))
RESULTS_BASE_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "Results"))
DEFAULT_PLANT_NAME = "YANPET_OLF1"

# ---------------------------------------------------------------
# MULTI-PLANT SUPPORT
# ---------------------------------------------------------------
# This same dashboard, whatif_runner.py and Model_development_and_
# static_whatif_testing.py can serve any number of plants. Each plant
# gets its own subfolder:
#   Data/<plant>/Config_file_updated.xlsx, DMC_Screen_tags_data.xlsx
#   Results/<plant>/Model/*.pkl, Raw_data_plus_simulated_data.xlsx
# A plant with no such subfolder falls back to the flat Data/ , Results/
# layout, so a pre-existing single-plant deployment keeps working
# unchanged. Everything below is driven entirely by the plant picked in
# the sidebar -- no code edits needed to add another plant.
# ---------------------------------------------------------------
def _resolve_plant_path(base_dir: str, plant_name: str) -> str:
    nested = os.path.join(base_dir, plant_name)
    return nested if os.path.isdir(nested) else base_dir


def discover_plants() -> list:
    """Plant names = subfolders of Data/ that contain a Config_file_updated.xlsx,
    always including the default so a brand-new deployment still shows
    an option even before any plant folder has been created."""
    found = []
    if os.path.isdir(DATA_BASE_DIR):
        for name in sorted(os.listdir(DATA_BASE_DIR)):
            sub = os.path.join(DATA_BASE_DIR, name)
            if os.path.isdir(sub) and any(
                f.lower() == "config_file_updated.xlsx" for f in os.listdir(sub)
            ):
                found.append(name)
    if DEFAULT_PLANT_NAME not in found:
        found.append(DEFAULT_PLANT_NAME)
    return found


if "plant_name" not in st.session_state:
    st.session_state["plant_name"] = DEFAULT_PLANT_NAME

_PLANT_SCOPED_KEYS = [
    "config_autoloaded", "user_inputs_df", "model_details_df", "constraints_df",
    "display_order_df", "pi_names_df", "lbt_input_df", "generated_pi_mapping",
    "generated_tags", "wizard_selection", "pi_source", "config_uploaded_via_ui",
    "setup_complete", "training_data_ready", "models_trained", "editor_rev",
    "result", "selected_time", "_autosave_sig", "config_file_uploaded",
    "_last_config_upload_sig",
]


def _reset_plant_scoped_state():
    """Config/results are per-plant; wipe them so switching plants never
    leaks another plant's tags, limits, or last what-if result."""
    for _k in _PLANT_SCOPED_KEYS:
        st.session_state.pop(_k, None)
    st.session_state["config_autoloaded"] = False


with st.sidebar:
    st.markdown("### 🏭 Plant")
    _plant_options = discover_plants()
    if st.session_state["plant_name"] not in _plant_options:
        _plant_options.append(st.session_state["plant_name"])
    _new_plant_label = "+ Add a new plant..."
    _choices = _plant_options + [_new_plant_label]
    _current = st.session_state["plant_name"]
    _default_idx = _choices.index(_current) if _current in _choices else 0
    _picked = st.selectbox("Active plant", _choices, index=_default_idx, key="plant_picker")

    if _picked == _new_plant_label:
        _new_name = st.text_input("New plant name (letters/numbers/underscore)", key="new_plant_name")
        st.caption("No files needed — you'll build the PI mapping, model mapping, "
                   "constraints, user inputs and column order for this plant entirely "
                   "in the **Configuration Hub** tab, then save it from there.")
        if st.button("Create plant", key="create_plant_btn"):
            _clean_name = re.sub(r"[^A-Za-z0-9_\-]", "_", (_new_name or "").strip())
            if not _clean_name:
                st.error("Enter a plant name first.")
            elif _clean_name in _plant_options:
                st.error(f"Plant '{_clean_name}' already exists — pick it from the list instead.")
            else:
                _plant_dir = os.path.join(DATA_BASE_DIR, _clean_name)
                os.makedirs(_plant_dir, exist_ok=True)
                # Also stake out this plant's own Results/<name>/Model folder.
                # Without this, _resolve_plant_path() would find no nested
                # Results dir yet and silently fall back to the flat legacy
                # Results/ folder -- which is exactly where another plant's
                # (e.g. YANPET_OLF1's) trained models/historian data live.
                os.makedirs(os.path.join(RESULTS_BASE_DIR, _clean_name, "Model"), exist_ok=True)
                st.session_state["plant_name"] = _clean_name
                _reset_plant_scoped_state()
                st.success(f"Plant '{_clean_name}' created — switching to it. "
                           "Head to the Configuration Hub to build its config.")
                st.rerun()
    elif _picked != st.session_state["plant_name"]:
        st.session_state["plant_name"] = _picked
        _reset_plant_scoped_state()
        st.rerun()

    st.caption(f"Working on **{st.session_state['plant_name']}**. Everything below "
               "(config, training, what-if runs) targets this plant only.")

PLANT_NAME = st.session_state["plant_name"]
os.environ["PLANT_NAME"] = PLANT_NAME  # so whatif_runner / training subprocess pick the same plant

TRAIN_DATA_DIR = _resolve_plant_path(DATA_BASE_DIR, PLANT_NAME)
RESULTS_DIR = _resolve_plant_path(RESULTS_BASE_DIR, PLANT_NAME)
MODEL_DIR = os.path.join(RESULTS_DIR, "Model")
TRAIN_WORKBOOK = os.path.join(TRAIN_DATA_DIR, "DMC_Screen_tags_data.xlsx")
# If this file exists, models were already trained -> training is OPTIONAL
RAW_SIM_FILE = os.path.join(RESULTS_DIR, "Raw_data_plus_simulated_data.xlsx")

# ---------------------------------------------------------------
# CONFIG SCRATCH DIR — the uploaded Config_file_updated.xlsx is never
# written into the plant's persistent Data/<plant>/ folder. It's kept
# in a throwaway, per-browser-session temp folder instead, so nothing
# survives beyond this session and no config ever lingers where a
# future auto-load (or another tool) could pick it up. Both the
# training subprocess (via the CONFIG_DIR env var) and whatif_analysis()
# (via its plant_dir override) are pointed at this folder instead of
# TRAIN_DATA_DIR for the config file specifically -- historian/raw data
# still live in TRAIN_DATA_DIR / RESULTS_DIR as before.
# ---------------------------------------------------------------
if "_config_scratch_root" not in st.session_state:
    st.session_state["_config_scratch_root"] = tempfile.mkdtemp(prefix="whatif_cfg_")
CONFIG_DIR = os.path.join(st.session_state["_config_scratch_root"], PLANT_NAME)
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_WORKBOOK = os.path.join(CONFIG_DIR, "Config_file_updated.xlsx")

try:
    from pandas.io.formats.style import Styler as _PdStyler
except Exception:  # noqa: BLE001
    _PdStyler = None

# ---------------------------------------------------------------
# Safe import of the what-if engine. The UI must never hard-crash
# with a raw traceback if the backend module is missing/broken.
# ---------------------------------------------------------------
WHATIF_IMPORT_ERROR = None
try:
    from whatif_runner import load_process_data, whatif_analysis, load_plant_formulas
except Exception as _imp_err:  # noqa: BLE001
    WHATIF_IMPORT_ERROR = _imp_err
    load_process_data = None
    whatif_analysis = None
    load_plant_formulas = None

# =====================================================================
# PART-1  |  CSS  (dark control-room theme)
# =====================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap');

.stApp {
    background: radial-gradient(circle at top right, #1e293b, #0f172a);
    color: #f8fafc;
    font-family: 'Inter', -apple-system, sans-serif;
}

/* ---------- Headings ---------- */
h1 {
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 34px !important;
    font-weight: 800 !important;
    margin-bottom: 4px;
}
h2, h3, h4 {
    color: #f1f5f9 !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}
label {
    color: #e2e8f0 !important;
    font-size: 14px !important;
    font-weight: 600 !important;
}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] {
    background-color: #0b1220 !important;
    border-right: 1px solid rgba(255,255,255,0.08) !important;
}
section[data-testid="stSidebar"] * { color: #f1f5f9 !important; }
section[data-testid="stSidebar"] h3 {
    color: #38bdf8 !important;
    font-size: 13px !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 14px;
}

/* ---------- Tabs ---------- */
button[data-baseweb="tab"] {
    font-size: 15px !important;
    font-weight: 600 !important;
    color: #94a3b8 !important;
    transition: all .2s ease;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #38bdf8 !important;
    border-bottom-color: #38bdf8 !important;
}

/* ---------- Inputs ---------- */
div[data-baseweb="select"] > div,
.stTextInput input, .stNumberInput input {
    background-color: #1e293b !important;
    color: #f8fafc !important;
    border-radius: 8px !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #38bdf8 !important;
    box-shadow: 0 0 0 1px #38bdf8 !important;
}
div[data-baseweb="select"] span { color: #f8fafc !important; font-weight: 500 !important; }

/* ---------- Tables ---------- */
[data-testid="stDataFrame"], .stDataEditor {
    border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    background-color: #1e293b !important;
}

/* ---------- Buttons ---------- */
.stButton > button, .stDownloadButton > button {
    background: linear-gradient(135deg, #3b82f6, #1d4ed8) !important;
    color: #fff !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    border: none !important;
    padding: 10px 24px !important;
    width: 100%;
    box-shadow: 0 4px 12px rgba(59,130,246,0.25);
    transition: all .2s ease-in-out;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(59,130,246,0.35);
}
.stDownloadButton > button {
    background: linear-gradient(135deg, #10b981, #059669) !important;
    box-shadow: 0 4px 12px rgba(16,185,129,0.20);
}

/* ---------- Cards ---------- */
.executive-card {
    background-color: rgba(30,41,59,0.4);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
}
.wizard-chip {
    display: inline-block;
    padding: 4px 12px;
    margin: 2px 6px 2px 0;
    border-radius: 999px;
    background: rgba(56,189,248,0.12);
    border: 1px solid rgba(56,189,248,0.35);
    color: #7dd3fc;
    font-size: 12px;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
}
.kpi-value { font-family: 'JetBrains Mono', monospace; }

/* ---------- Config panel headers (PI Mapping / Model Mapping / etc.) ---------- */
.panel-header {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 18px;
    border-radius: 12px 12px 0 0;
    border: 1px solid rgba(255,255,255,0.08);
    border-bottom: none;
    background: linear-gradient(90deg, var(--panel-accent-a, #1e293b), rgba(30,41,59,0.3));
    margin-top: 6px;
}
.panel-header .panel-icon {
    font-size: 26px;
    line-height: 1;
    filter: drop-shadow(0 0 6px rgba(255,255,255,0.15));
}
.panel-header .panel-title {
    font-size: 17px;
    font-weight: 700;
    color: #f8fafc;
    margin: 0;
}
.panel-header .panel-desc {
    font-size: 12.5px;
    color: #94a3b8;
    margin-top: 2px;
}
.panel-header .panel-count {
    margin-left: auto;
    padding: 4px 14px;
    border-radius: 999px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    font-size: 13px;
    white-space: nowrap;
}

/* ---------- Numbered step banners (What-if case setup) ---------- */
.step-banner {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 14px 18px;
    margin: 10px 0 16px;
    border-radius: 12px;
    background: linear-gradient(90deg, rgba(59,130,246,0.18), rgba(30,41,59,0.25));
    border: 1px solid rgba(59,130,246,0.30);
    border-left: 4px solid #3b82f6;
}
.step-banner .step-badge {
    flex: 0 0 auto;
    width: 34px; height: 34px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700; font-size: 16px;
    color: #ffffff;
    background: linear-gradient(135deg, #3b82f6, #2563eb);
    box-shadow: 0 3px 8px rgba(59,130,246,0.40);
}
.step-banner .step-emoji { font-size: 24px; line-height: 1; }
.step-banner .step-title { font-size: 18px; font-weight: 700; color: #f8fafc; margin: 0; }
.step-banner .step-sub   { font-size: 12.5px; color: #94a3b8; margin: 2px 0 0; }
.panel-body-wrap [data-testid="stDataFrame"], .panel-body-wrap .stDataEditor {
    border-radius: 0 0 12px 12px !important;
    border-top: none !important;
}

/* ---------- KPI stat strip ---------- */
.kpi-strip { display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0 18px 0; }
.kpi-card {
    flex: 1 1 140px;
    min-width: 130px;
    padding: 14px 16px;
    border-radius: 12px;
    background: rgba(30,41,59,0.55);
    border: 1px solid rgba(255,255,255,0.08);
    border-left: 4px solid var(--kpi-accent, #38bdf8);
}
.kpi-card .kpi-num {
    font-family: 'JetBrains Mono', monospace;
    font-size: 26px;
    font-weight: 800;
    color: #f8fafc;
    line-height: 1.1;
}
.kpi-card .kpi-label {
    font-size: 12px;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 4px;
}

/* Expander polish */
details {
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 10px !important;
}
</style>
""", unsafe_allow_html=True)


# =====================================================================
# PART-1  |  HISTORIAN LOADING (cached, defensive)
# =====================================================================
@st.cache_data(show_spinner="Loading historian process data...")
def get_cached_process_data(plant_name: str) -> pd.DataFrame:
    """
    Loads historical data from the historian and normalises it:
      - forces a proper DatetimeIndex (invalid rows dropped)
      - sorts chronologically
      - drops fully-empty columns
    Raises RuntimeError with a readable message on any failure.
    `plant_name` is part of the cache key so switching plants reloads
    the right dataset instead of reusing a stale cached one.
    """
    if load_process_data is None:
        raise RuntimeError(
            "Backend module 'whatif_runner' could not be imported: "
            f"{WHATIF_IMPORT_ERROR}"
        )
    raw = load_process_data(plant_name=plant_name)
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        raise RuntimeError("Historian returned an empty dataset.")

    out = raw.copy()
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[out.index.notna()].sort_index()
    out = out.dropna(axis=1, how="all")
    if out.empty:
        raise RuntimeError("No rows with valid timestamps found in historian data.")
    return out


@st.cache_data(show_spinner="Loading training workbook for correlation preview...")
def get_cached_training_df_for_corr(train_workbook_path: str, _mtime: float):
    """Lightweight reload of the saved training workbook for the
    Correlation Matrix step -- independent of full model training.
    Mirrors the training script's basic 'PI data' / 'Furnace data'
    parsing (header-in-row-1, Timestamp index, numeric coercion), but
    does NOT replicate derived/simulated columns computed during actual
    training (e.g. Coil_Avg_COT) -- those only exist after Train Models.

    Cached by (path, mtime): re-parses the workbook (slow -- Excel I/O
    on a potentially large file) only the first time, or after a new
    training dataset is saved (which changes the file's mtime). Every
    other rerun of the app (typing elsewhere, switching steps, etc.)
    reuses the cached result instantly instead of re-reading the file.
    """
    if not os.path.isfile(train_workbook_path):
        return None
    try:
        xl = pd.ExcelFile(train_workbook_path)
    except Exception:  # noqa: BLE001
        return None
    frames = []
    for sheet in ("PI data", "Furnace data"):
        if sheet not in xl.sheet_names:
            continue
        raw = pd.read_excel(xl, sheet_name=sheet)
        if raw.empty:
            continue
        raw.columns = raw.iloc[0]
        raw = raw[1:].reset_index(drop=True)
        raw.columns = [str(c).strip() for c in raw.columns]
        if "Timestamp" not in raw.columns:
            continue
        raw = raw.set_index("Timestamp")
        raw = raw.apply(pd.to_numeric, errors="coerce")
        frames.append(raw)
    if not frames:
        return None
    combined = frames[0]
    for f in frames[1:]:
        combined = combined.join(f, how="outer", rsuffix="_furnace")
    return combined.dropna(how="all")


@st.cache_data(show_spinner="Computing correlation matrix...")
def get_cached_corr_matrix(train_workbook_path: str, _mtime: float):
    """The Pearson correlation matrix itself, cached alongside the raw
    load -- corr() on a wide table is also non-trivial, so this avoids
    recomputing it on every rerun too. Returns (df_corr, n_numeric_cols,
    n_rows) or (None, 0, 0) if there's nothing to compute yet."""
    src = get_cached_training_df_for_corr(train_workbook_path, _mtime)
    if src is None or src.empty:
        return None, 0, 0
    numeric_cols = src.select_dtypes(include="number").columns.tolist()
    if len(numeric_cols) < 2:
        return None, len(numeric_cols), len(src)
    df_corr = src[numeric_cols].corr(method="pearson").round(2)
    return df_corr, len(numeric_cols), len(src)


# =====================================================================
# PART-1  |  PI_generalised_Name LOADING (cached, multi-source)
# =====================================================================
PI_SHEET = "PI_generalised_Name"
PI_COLUMNS = ["Pi_tags", "Generalized Description", "Section"]

# Sheet name (normalised) -> session-state key
SHEET_TO_STATE = {
    "user inputs": "user_inputs_df",
    "model details": "model_details_df",
    "constraints": "constraints_df",
    "display_column_order": "display_order_df",
    "pi_generalised_name": "pi_names_df",
    "lbt_input": "lbt_input_df",
    "section order": "section_order_df",
    "mv_dv_cv_taglist": "mvdvcv_df",
    "mv dv cv taglist": "mvdvcv_df",
}


def _norm_name(name: str) -> str:
    """'PI generalised Tags ' -> 'pigeneralisedtags' (robust sheet matching)."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


_SHEET_LOOKUP_NORM = {_norm_name(k): v for k, v in SHEET_TO_STATE.items()}


def _match_sheet_to_state(sheet_name: str):
    """Maps a workbook sheet to a session key, tolerant of naming variants.
    Any sheet starting with 'pi' and containing a recognisable qualifier
    (general/generalis/generaliz, tag, mapping, dictionary, master, names)
    is treated as the PI tag dictionary -- this covers both the sheet's
    canonical on-disk name ('PI_generalised_Name') and the name the UI
    itself uses everywhere ('PI Tag Mapping')."""
    n = _norm_name(sheet_name)
    if n in _SHEET_LOOKUP_NORM:
        return _SHEET_LOOKUP_NORM[n]
    if "pi" in n and any(k in n for k in (
        "general", "generalis", "generaliz", "tag", "mapping", "dictionary", "master", "name"
    )):
        return "pi_names_df"
    if "section" in n and any(k in n for k in ("order", "flow", "sequence")):
        return "section_order_df"
    return None


def _candidate_config_paths() -> list:
    """
    CONFIG FILE SEARCH PATH (first hit wins):
      1. Data/<active plant>/Config_file_updated.xlsx   <- multi-plant layout (always searched)
      2. <app folder>/Config_file_updated.xlsx )
      3. <app folder>/Data/Config_file_updated.xlsx     )  <- legacy single-plant layout,
      4. <one folder back>/Data/Config_file_updated.xlsx)     ONLY searched when the active
                                                        plant has no dedicated
                                                        subfolder of its own (i.e.
                                                        it resolved straight to the
                                                        flat Data/ dir). This keeps a
                                                        brand-new/empty plant from
                                                        picking up another plant's
                                                        flat, legacy config file.
      5. same locations for PI_generalised_Name.xlsx
    Filename matching is case-insensitive.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = [TRAIN_DATA_DIR]  # active plant's resolved Data dir (highest priority)
    if os.path.normpath(TRAIN_DATA_DIR) == os.path.normpath(DATA_BASE_DIR):
        # No per-plant subfolder exists for the active plant -> this is a
        # legacy/flat single-plant deployment; broaden the search so it
        # still finds a Config_file_updated.xlsx placed next to the app or in ../Data.
        dirs += [
            here,
            os.path.join(here, "Data"),
            os.path.abspath(os.path.join(here, "..", "Data")),
            os.getcwd(),
            os.path.join(os.getcwd(), "Data"),
            os.path.abspath(os.path.join(os.getcwd(), "..", "Data")),
        ]
    seen_dirs, paths = set(), []
    for d in dirs:
        d = os.path.normpath(d)
        if d in seen_dirs or not os.path.isdir(d):
            continue
        seen_dirs.add(d)
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for want in ("config_file_updated.xlsx", "pi_generalised_name.xlsx"):
            for f in files:
                if f.lower() == want or (_norm_name(f).startswith("configfile") and f.lower().endswith(".xlsx")):
                    paths.append(os.path.join(d, f))
    # de-duplicate, preserve priority order
    out, seen = [], set()
    for p in paths:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


@st.cache_data(show_spinner=False)
def autoload_config_from_disk(plant_name: str, data_dir: str, _cache_bust: float = 0.0) -> tuple:
    """
    AUTOMATIC CONFIG LOADING — no upload required.
    Walks the search path above (app folder, ./Data, ../Data) and loads
    every recognised sheet. Returns ({session_key: DataFrame}, source_path).
    `_cache_bust` isn't used inside the function -- it's the newest mtime
    among the candidate config files, passed in purely so that Streamlit's
    @st.cache_data (a process-wide cache keyed on arguments) invalidates
    and re-reads the file whenever it changes on disk, e.g. after an
    autosave -- otherwise a page refresh could return a stale cached copy.
    The front-end upload remains available as an OPTIONAL override.
    """
    found: dict = {}
    source = None
    for path in _candidate_config_paths():
        try:
            xl = pd.ExcelFile(path)
        except Exception:  # noqa: BLE001
            continue
        loaded_any = False
        for sheet in xl.sheet_names:
            state_name = _match_sheet_to_state(sheet)
            if state_name is None or state_name in found:
                continue
            try:
                sheet_df = (pd.read_excel(xl, sheet_name=sheet)
                            .dropna(how="all").reset_index(drop=True))
            except Exception:  # noqa: BLE001
                continue
            found[state_name] = sheet_df
            loaded_any = True
        # Standalone PI file may only contain the dictionary sheet
        if loaded_any and source is None:
            source = path
        if len(found) >= len(SHEET_TO_STATE):
            break
    return found, source


# Canonical, name-based section keywords -- used both to auto-classify
# blank "Section" values in the PI dictionary and to auto-classify blank
# "Section" values for predicted parameters in the Model Mapping editor.
# Order matters: first match wins (e.g. "CGC" must be checked before a
# generic "Cold" catch-all).
_SECTION_KEYWORDS = [
    ("Furnace", ("furnace", "coil", "cot", "cracking")),
    ("Quench", ("quench",)),
    ("CGC", ("cgc",)),
    ("ERC", ("erc",)),
    ("PRC", ("prc",)),
    ("Cold", ("cold", "demeth", "ethylene", "ethane", "deethaniz", "depropaniz")),
]


def infer_section(name) -> str:
    """Best-effort plant-section guess from a tag/parameter name, used
    to auto-classify rows that were left with a blank 'Section' value.
    Returns '' if nothing matches -- the row simply stays unclassified
    rather than raising."""
    if name is None:
        return ""
    n = str(name).strip().lower()
    if not n or n == "nan":
        return ""
    for section, keywords in _SECTION_KEYWORDS:
        if any(kw in n for kw in keywords):
            return section
    return ""


def normalize_pi_df(pi_df: pd.DataFrame) -> pd.DataFrame:
    """Cleans the PI dictionary: trims text, title-cases Section, drops blanks.
    Blank/missing Section values are auto-inferred (clubbed) from tag names."""
    if pi_df is None or pi_df.empty:
        return pd.DataFrame(columns=PI_COLUMNS)
    out = pi_df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for col in PI_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[[c for c in out.columns if c in set(PI_COLUMNS) | set(out.columns)]]
    out["Pi_tags"] = out["Pi_tags"].astype(str).str.strip()
    out["Generalized Description"] = out["Generalized Description"].astype(str).str.strip()
    out["Section"] = (
        out["Section"].astype(str).str.strip().str.title()
        .replace({"Nan": "", "None": "",
                  "Cgc": "CGC", "Prc": "PRC", "Erc": "ERC"})
    )
    # Club unclassified tags into their section automatically
    blank = out["Section"] == ""
    if blank.any():
        out.loc[blank, "Section"] = out.loc[blank, "Generalized Description"].map(infer_section)
    out = out[(out["Pi_tags"] != "") & (out["Pi_tags"].str.lower() != "nan")]
    return out.reset_index(drop=True)


# =====================================================================
# PART-1  |  SESSION STATES (single source of truth)
# =====================================================================
_SESSION_DEFAULTS = {
    "user_inputs_df": pd.DataFrame(
        columns=["Parameter", "Value", "Lower Limit", "Upper Limit", "Remark"]),
    "model_details_df": pd.DataFrame(
        columns=["Predicted parameter", "Section"] + [f"Input parameter_{i}" for i in range(1, 9)]),
    "constraints_df": pd.DataFrame(
        columns=["Parameter", "user input value", "Max value", "UOM", "Remark",
                 "Linked Parameter", "Action"]),
    "display_order_df": pd.DataFrame(columns=["Sr.no", "Preferred columns"]),
    "pi_names_df": pd.DataFrame(columns=PI_COLUMNS),
    # Process execution order (Furnace -> Quench -> CGC -> ERC -> PRC ->
    # Cold, etc.) -- defines which sections count as "upstream" of a
    # selected target section in the What-if Dashboard.
    "section_order_df": pd.DataFrame(columns=["Sr.no", "Section"]),
    # MV/DV/CV tag list -- the primary, prioritized source of input tags for
    # Model Mapping (Step 7). Schema matches MV_DV_CV_taglist.xlsx.
    "mvdvcv_df": pd.DataFrame(columns=["Name", "GeneralizedDescription", "Section", "Type"]),
    "lbt_input_df": pd.DataFrame(
        columns=["Iteration No", "Match_tags", "Tolerance_minimum",
                 "Tolerance_maximum", "Match_Tag_Decimal",
                 "performance_tag", "direction"]),
    # Wizard outputs
    "generated_pi_mapping": pd.DataFrame(columns=PI_COLUMNS),
    "generated_tags": [],
    "wizard_selection": {},
    "pi_source": "session memory",
    # PI Tag Mapping sheet stays hidden until a config workbook containing
    # the model mapping sheet is uploaded through the UI
    "config_uploaded_via_ui": False,
    # True once the user has uploaded a Config_file_updated.xlsx THIS SESSION.
    # No config is ever pre-loaded from disk by default -- an upload is
    # always required before the wizard/editors are considered "live"
    # and before model training is allowed to run.
    "config_file_uploaded": False,
    # Simulation overrides in the What-if Dashboard stay hidden until the
    # user clicks "Proceed to What-if Dashboard" in the case setup tab
    "setup_complete": False,
    # Training workflow gates
    "training_data_ready": False,   # PI data and/or Furnace data sheet(s) saved to disk
    "models_trained": False,        # model script ran OK and pkl files exist
    # Bumped on every config upload so the data editors re-render fresh data
    "editor_rev": 0,
    # Guided Case Setup wizard: which step (1-7) is currently active, and
    # the shared "active" target section, set in Step 2 and reused as the
    # default in the 📊 What-if Dashboard tab's own Target Section picker.
    "cs_step": 1,
    "target_section": None,
}

for _key, _default in _SESSION_DEFAULTS.items():
    if _key not in st.session_state:
        st.session_state[_key] = (
            _default.copy() if isinstance(_default, (pd.DataFrame, dict, list)) else _default
        )


# =====================================================================
# PART-1  |  SECTION-BASED PROCESS FLOW ORDER
# =====================================================================
def get_section_order() -> list:
    """The plant's process execution order (upstream -> downstream), exactly
    as manually entered in Step 1 of the case setup wizard. Returns an
    empty list if the user hasn't defined it yet -- this is intentionally
    NOT auto-populated or inferred from any other sheet."""
    so_df = st.session_state.get("section_order_df")
    if so_df is None or so_df.empty or "Section" not in so_df.columns:
        return []
    ordered = so_df.copy()
    if "Sr.no" in ordered.columns:
        ordered = ordered.sort_values("Sr.no", na_position="last")
    secs = [str(s).strip() for s in ordered["Section"].tolist()
            if str(s).strip() and str(s).strip().lower() != "nan"]
    seen, out = set(), []
    for s in secs:
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def allowed_sections_upto(section_order: list, target_section: str) -> list:
    """All sections from the start of section_order up to and including
    target_section (upstream sections + the target itself, no
    downstream sections). Falls back to the full list, unrestricted, if
    target_section isn't recognised -- mirrors whatif_runner.allowed_sections_upto."""
    if not section_order or not target_section:
        return list(section_order or [])
    norm = [str(s).strip().lower() for s in section_order]
    t = str(target_section).strip().lower()
    if t not in norm:
        return list(section_order)
    return list(section_order)[: norm.index(t) + 1]



# =====================================================================
# PART-1  |  TAG SEGREGATION FUNCTIONS
# =====================================================================
_ORDINAL_TO_INT = {"1ST": 1, "2ND": 2, "3RD": 3, "4TH": 4, "5TH": 5,
                   "6TH": 6, "7TH": 7, "8TH": 8}
_STAGE_RE = re.compile(r"(1ST|2ND|3RD|[4-8]TH)[_\s]*(?:STG|STAGE)", re.IGNORECASE)
# Furnace number token: matches "F7" mid-name ("..._F7") and at the start of the
# name ("F11_Furnace_Feed..."). The number must be followed by "_" or end-of-name
# so "F7A" / "Feed" don't false-match. Case-sensitive: only an uppercase F counts.
_FURNACE_RE = re.compile(r"(?:^|_)F(\d{1,2})(?:_|$)")
_FURNACE_RANGE_RE = re.compile(r"(?:^|_)F(\d{1,2})_(\d{1,2})(?:_|$)")


def extract_stage_number(tag: str):
    """Returns compressor stage number embedded in a tag name, else None.
    e.g. 'CGC_5TH_STG_DISCH_PRES' -> 5 ; 'PRC_1ST_STAGE_Suction_FLOW' -> 1
    """
    if not isinstance(tag, str):
        return None
    m = _STAGE_RE.search(tag.upper())
    return _ORDINAL_TO_INT.get(m.group(1).upper()) if m else None


def extract_furnace_numbers(tag: str):
    """Returns the set of furnace numbers referenced by a tag, else empty set.
    Handles single ('Total_ET1NE_Feed_F7' -> {7}) and range
    ('Quench_tower_feed_temp_F6_12' -> {6..12}) patterns.
    """
    if not isinstance(tag, str):
        return set()
    rng = _FURNACE_RANGE_RE.search(tag)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if lo <= hi <= 20:
            return set(range(lo, hi + 1))
    single = _FURNACE_RE.search(tag)
    if single:
        return {int(single.group(1))}
    return set()


def segregate_tags_by_section(pi_df: pd.DataFrame) -> dict:
    """Splits the PI dictionary into {Section: DataFrame} groups.
    Section is coerced to a plain string first (NaN/blank -> 'Unclassified')
    so the resulting dict keys are always comparable/sortable -- a mix of
    real section names (str) and a raw NaN (float) otherwise breaks any
    later sorted(section_groups.items())."""
    if pi_df is None or pi_df.empty or "Section" not in pi_df.columns:
        return {}
    _df = pi_df.copy()
    _df["Section"] = (
        _df["Section"].fillna("Unclassified").astype(str).str.strip()
        .replace({"": "Unclassified", "nan": "Unclassified", "None": "Unclassified"})
    )
    return {sec: grp.reset_index(drop=True)
            for sec, grp in _df.groupby("Section", dropna=False)}


def available_stages(pi_df: pd.DataFrame, section: str) -> list:
    """Sorted list of stage numbers present in a compressor section."""
    if pi_df is None or pi_df.empty:
        return []
    sub = pi_df[pi_df["Section"].str.upper() == section.upper()]
    stages = {extract_stage_number(t) for t in sub["Generalized Description"]}
    return sorted(s for s in stages if s is not None)


def available_furnaces(pi_df: pd.DataFrame) -> list:
    """Sorted list of furnace numbers detected in the Furnace section."""
    if pi_df is None or pi_df.empty:
        return []
    sub = pi_df[pi_df["Section"].str.upper() == "FURNACE"]
    nums = set()
    for t in sub["Generalized Description"]:
        nums |= extract_furnace_numbers(t)
    return sorted(nums)


def generate_pi_mapping(pi_df: pd.DataFrame,
                        cgc_stages: list,
                        prc_stages: list,
                        erc_stages: list,
                        furnaces: list) -> pd.DataFrame:
    """
    AUTOMATIC PI MAPPING GENERATION
    Builds the active tag mapping for the configured plant line-up:
      - Compressor sections (CGC/PRC/ERC): stage-numbered tags kept only
        for selected stages; stage-agnostic tags always kept.
      - Furnace section: furnace-numbered tags kept only for selected
        furnaces (range tags kept if ANY selected furnace is in range);
        furnace-agnostic tags always kept.
      - All other sections (Quench, Cold, ...) kept in full.
    """
    if pi_df is None or pi_df.empty:
        return pd.DataFrame(columns=PI_COLUMNS)

    stage_sel = {"CGC": set(cgc_stages or []),
                 "PRC": set(prc_stages or []),
                 "ERC": set(erc_stages or [])}
    furnace_sel = set(furnaces or [])

    def _keep(row) -> bool:
        section = str(row.get("Section", "")).upper()
        tag = str(row.get("Generalized Description", ""))
        if section in stage_sel:
            stg = extract_stage_number(tag)
            return True if stg is None else stg in stage_sel[section]
        if section == "FURNACE":
            f_nums = extract_furnace_numbers(tag)
            return True if not f_nums else bool(f_nums & furnace_sel)
        return True

    mask = pi_df.apply(_keep, axis=1)
    return pi_df[mask].reset_index(drop=True)


def fmt_num(val, force_sign: bool = False) -> str:
    """Display formatting rule: 0 decimals >= 1000, else 1 decimal."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return str(val)
    sign = "+" if force_sign else ""
    return f"{v:{sign}.0f}" if abs(v) >= 1000 else f"{v:{sign}.1f}"


# ---------------------------------------------------------------
# Seed ALL config sheets from disk once (upload in Tab-1 is an
# OPTIONAL override, not a requirement).
# ---------------------------------------------------------------
def _config_mtime_signature() -> float:
    """Newest mtime among candidate config files -- see autoload_config_from_disk."""
    newest = 0.0
    try:
        for p in _candidate_config_paths():
            try:
                newest = max(newest, os.path.getmtime(p))
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return newest


if not st.session_state.get("config_autoloaded", False):
    # ---------------------------------------------------------------
    # NOTE: automatic disk-based config loading is intentionally
    # DISABLED. The dashboard must never silently pick up whatever
    # Config_file_updated.xlsx happens to already sit in Data/<plant>/ --
    # the config (PI mapping, Model details / Predicted parameters,
    # Constraints, User Inputs, Column Order) must always come from an
    # explicit upload in the "🎛️ Configuration Source" section of the
    # ⚙️ What-if case setup tab for THIS session. That uploaded
    # workbook -- specifically its "Model details" sheet -- is what
    # drives which Predicted parameters get trained, since it's what
    # gets (re)written to Config_file_updated.xlsx on disk before the training
    # subprocess runs. See autoload_config_from_disk() above, which is
    # kept but no longer called automatically.
    # ---------------------------------------------------------------
    st.session_state["config_autoloaded"] = True

# ---------------------------------------------------------------
# Boot the historian. A brand-new/not-yet-trained plant legitimately
# has no historian data yet -- that must NOT block the whole app,
# since the Configuration Hub (tab1) is exactly where you set that
# plant up. So: never st.stop() here. Record the failure and let the
# What-if Dashboard tab (the only tab that actually needs `df`) show
# a friendly "train this plant first" notice instead.
# ---------------------------------------------------------------
HISTORIAN_ERROR = None
try:
    df = get_cached_process_data(PLANT_NAME)
except Exception as boot_err:  # noqa: BLE001
    HISTORIAN_ERROR = boot_err
    df = pd.DataFrame()

if not df.empty:
    tag_options = sorted(df.columns.astype(str).tolist())
else:
    # Best-effort fallback so Model Mapping / Constraints / User Inputs
    # editors still offer tag choices for a plant that has been trained
    # yet, as long as its raw training workbook has been uploaded.
    tag_options = []
    try:
        if os.path.isfile(TRAIN_WORKBOOK):
            _raw_xl = pd.ExcelFile(TRAIN_WORKBOOK)
            _cols = set()
            for _sheet in _raw_xl.sheet_names:
                _cols.update(pd.read_excel(_raw_xl, sheet_name=_sheet, nrows=0).columns.astype(str))
            tag_options = sorted(_cols)
    except Exception:  # noqa: BLE001
        tag_options = []

# ---------------------------------------------------------------
# Streamlit version compatibility: 'use_container_width' is
# deprecated on newer releases in favour of width='stretch'.
# ---------------------------------------------------------------
import inspect as _inspect
try:
    _HAS_WIDTH_KW = "width" in _inspect.signature(st.button).parameters
except Exception:  # noqa: BLE001
    _HAS_WIDTH_KW = False
FULL_WIDTH = {"width": "stretch"} if _HAS_WIDTH_KW else {"use_container_width": True}

try:
    _HAS_CONTAINER_BORDER = "border" in _inspect.signature(st.container).parameters
except Exception:  # noqa: BLE001
    _HAS_CONTAINER_BORDER = False


def _bordered_container():
    return st.container(border=True) if _HAS_CONTAINER_BORDER else st.container()



# =====================================================================
# APP TITLE + TOP-LEVEL TABS
# =====================================================================
st.title(f"{PLANT_NAME} What-if Dashboard")
st.caption("Ethylene plant What-if senario development · Configuration → Run What - if → Validation with historical data")

tab0, tab1, tab2 = st.tabs(["📖 Overview", "⚙️ What-if case setup", "📊 What-if Dashboard"])


# =====================================================================
# TAB 0 : OVERVIEW — README-style instructions for running the dashboard
# =====================================================================
with tab0:

    st.subheader("📖 What-If Platform — Overview")
    st.markdown(
        "Simulate *what-if* scenarios on the plant using historian data and trained "
        "models. Configure once, override process parameters, and instantly compare "
        "**Actual vs Estimated** outcomes — validated against real historical snapshots."
    )
    st.markdown(
        '<span class="wizard-chip">1️⃣ Configure</span> '
        '<span class="wizard-chip">2️⃣ Run What-if</span> '
        '<span class="wizard-chip">3️⃣ Validate with history</span>',
        unsafe_allow_html=True,
    )

    st.divider()

    # -----------------------------------------------------------------
    # Two ways to get configured
    # -----------------------------------------------------------------
    st.markdown("#### 🚀 Two Ways to Get Configured")
    _oc1, _oc2 = st.columns(2)
    with _oc1:
        st.markdown(
            "**📂 Option A — Upload a configuration**\n\n"
            "- Upload `Config_file_updated.xlsx` (optional, in **⚙️ What-if case setup**)\n"
            "- Process order, PI/Model Mapping, and Target Section are already defined\n"
            "- The **Target Section** step is skipped — no need to pick it again\n"
            "- Remaining steps are pre-filled; just review and continue to training"
        )
    with _oc2:
        st.markdown(
            "**🧭 Option B — Build it through the UI**\n\n"
            "- Follow the guided wizard from scratch, one step at a time\n"
            "- **Save & Continue** stays disabled until the current step is valid\n"
            "- Includes choosing the **Target Section** right after the process order\n"
            "- A progress bar and step numbers always show where you are"
        )

    st.divider()

    # -----------------------------------------------------------------
    # Case setup steps (concise reference)
    # -----------------------------------------------------------------
    st.markdown("#### 🧩 Case Setup Steps")
    st.markdown(
        "1. **Process Execution Order** — enter plant sections in actual sequence "
        "(e.g. `Furnace → Quench → CGC → ERC → PRC → Cold`)\n"
        "2. **Target Section** — pick the section to analyze; upstream sections are "
        "included automatically, downstream ones excluded *(skipped if a config was uploaded)*\n"
        "3. **PI Tag Mapping** — raw PI tag → readable name → section, scoped to the active section(s)\n"
        "4. **MV/DV/CV Tag List** *(optional)* — upload or build the list of manipulated/"
        "disturbance/controlled variables; prioritized in Model Mapping's input dropdown\n"
        "5. **Training Dataset** — upload historian data for model training\n"
        "6. **Correlation Matrix** *(optional)* — Pearson correlation of the uploaded "
        "training data, colour-highlighted, to spot related tags before Model Mapping\n"
        "7. **Model Mapping** — predicted parameters and the inputs each model uses\n"
        "8. **Constraints** *(optional)* — operating limits and bump/abort rules\n"
        "9. **User Inputs** *(optional)* — overridable parameters with allowed ranges\n"
        "10. **Column Order** *(optional)* — display order for the results table\n"
        "11. **Train Models** — train and unlock the What-if Dashboard"
    )
    st.caption(
        "💡 Every table supports **📋 Paste from Excel** — copy cells (no header row) "
        "and paste directly; rows adjust automatically, no need to pre-add blank rows."
    )

    st.divider()

    # -----------------------------------------------------------------
    # Running a scenario
    # -----------------------------------------------------------------
    st.markdown("#### 📊 Running a What-If Scenario")
    st.markdown(
        "- Pick a **Target Section**, historical **date**, and **timestamp** as your baseline\n"
        "- Enter override values in the sidebar for any parameter (blank = keep the actual value)\n"
        "- Click **Compute What-If Scenario** for KPI cards and the Actual vs Estimated table\n"
        "- Only parameters within the active scope (target section + upstream) are shown or predicted\n"
        "- Use the validation filters to compare against similar historical operating points"
    )

    st.divider()

# =====================================================================
# PART-2  |  TAB 1 : CONFIGURATION HUB
# =====================================================================
def _step_banner(letter: str, emoji: str, title: str, desc: str = ""):
    """Render a consistent numbered step header used across the setup tab."""
    sub = f'<p class="step-sub">{desc}</p>' if desc else ""
    st.markdown(
        f'''<div class="step-banner">
                <span class="step-badge">{letter}</span>
                <span class="step-emoji">{emoji}</span>
                <div>
                    <p class="step-title">{title}</p>
                    {sub}
                </div>
            </div>''',
        unsafe_allow_html=True,
    )


with tab1:

    st.subheader("⚙️ What-if Case Setup")

    # -----------------------------------------------------------------
    # OPTIONAL shortcut: pre-fill everything below from an existing
    # workbook. Entirely optional -- skip it to configure manually
    # through the guided steps.
    # -----------------------------------------------------------------
    with st.expander("📂 Load existing configuration (optional)", expanded=False):
        st.caption("Optional — pre-fills the steps below. Skip to configure manually.")
        uploaded_config = st.file_uploader(
            "Config_file_updated.xlsx", type=["xlsx"], label_visibility="collapsed",
        )
        if uploaded_config is not None:
            _upload_sig = f"{uploaded_config.name}:{uploaded_config.size}"
            if st.session_state.get("_last_config_upload_sig") == _upload_sig:
                # Already processed this exact upload on a prior rerun --
                # the file_uploader widget keeps returning it every rerun,
                # so without this guard we'd reprocess + st.rerun() forever.
                pass
            else:
                try:
                    excel_file = pd.ExcelFile(uploaded_config)
                    loaded = []
                    loaded_states = []
                    for sheet in excel_file.sheet_names:
                        if _norm_name(sheet) in ("targetsection", "target"):
                            try:
                                _ts_df = pd.read_excel(excel_file, sheet_name=sheet)
                                if not _ts_df.empty and len(_ts_df.columns):
                                    _ts_val = str(_ts_df.iloc[0, 0]).strip()
                                    if _ts_val and _ts_val.lower() != "nan":
                                        st.session_state["target_section"] = _ts_val
                                        loaded.append(sheet)
                            except Exception:  # noqa: BLE001
                                pass
                            continue
                        state_name = _match_sheet_to_state(sheet)
                        if state_name is None:
                            continue
                        sheet_df = (pd.read_excel(excel_file, sheet_name=sheet)
                                    .dropna(how="all").reset_index(drop=True))
                        if state_name == "pi_names_df":
                            sheet_df = normalize_pi_df(sheet_df)
                            st.session_state["pi_source"] = "uploaded workbook"
                        st.session_state[state_name] = sheet_df
                        loaded.append(sheet)
                        loaded_states.append(state_name)
                    st.session_state["_last_config_upload_sig"] = _upload_sig
                    if loaded:
                        st.session_state["config_file_uploaded"] = True
                        st.session_state["_cs_bulk_loaded"] = True
                        st.success(f"✅ Loaded: {', '.join(loaded)}")
                        if "model_details_df" in loaded_states:
                            st.session_state["config_uploaded_via_ui"] = True
                            st.session_state["model_mapping_initialized"] = True
                            st.session_state["editor_rev"] += 1
                        st.rerun()
                    else:
                        st.warning("No recognised sheets found in this workbook.")
                except Exception as e:  # noqa: BLE001
                    st.error(f"⚠️ Could not parse the workbook: {e}")

    with st.expander("🧙 Plant Configuration Wizard (optional)", expanded=False):
        pi_master = st.session_state["pi_names_df"]

        if pi_master.empty:
            st.caption("💡 Load a PI tag dictionary above to use this shortcut.")
        else:
            section_groups = segregate_tags_by_section(pi_master)
            sec_summary = "  ".join(
                f'<span class="wizard-chip">{sec}: {len(grp)}</span>'
                for sec, grp in sorted(section_groups.items())
            )
            st.markdown(f"**Tag dictionary loaded** — {len(pi_master)} tags across sections:", unsafe_allow_html=True)
            st.markdown(sec_summary, unsafe_allow_html=True)
            # st.markdown("<br>", unsafe_allow_html=True)

            cgc_all = available_stages(pi_master, "CGC")
            prc_all = available_stages(pi_master, "PRC")
            erc_all = available_stages(pi_master, "ERC")
            furnace_all = available_furnaces(pi_master)

            st.caption("Answer the line-up questions to auto-generate a PI mapping.")

            def _ask_count(label: str, detected: list, key: str) -> int:
                """Compact numeric answer box, e.g. number of CGC stages."""
                max_n = max(detected) if detected else 0
                if max_n == 0:
                    st.caption(f"⚠️ No numbered tags detected for this question.")
                    return 0
                # Keep the input box narrow — a full-width number_input looks oversized.
                box_col, _spacer = st.columns([1, 1])
                with box_col:
                    return int(st.number_input(
                        label, min_value=0, max_value=max_n, value=max_n, step=1, key=key,
                        help=f"Detected in the tag dictionary: up to {max_n}. "
                             "Answering N keeps tags numbered 1 to N.",
                    ))

            wz1, wz2 = st.columns(2)
            with wz1:
                st.markdown("##### 🌀 CGC — Cracked Gas Compressor")
                n_cgc = _ask_count("No. of stages", cgc_all, "wiz_cgc_n")
                st.markdown("##### 🧊 ERC — Ethylene Refrigeration")
                n_erc = _ask_count("No. of stages", erc_all, "wiz_erc_n")
            with wz2:
                st.markdown("##### ❄️ PRC — Propylene Refrigeration")
                n_prc = _ask_count("No. of stages", prc_all, "wiz_prc_n")
                st.markdown("##### 🔥 Furnaces")
                n_furnace = _ask_count("No. of furnaces", furnace_all, "wiz_furnace_n")

            # Answering "5" for CGC clubs CGC stage tags 1..5 under Section=CGC, etc.
            cgc_stages = [s for s in cgc_all if s <= n_cgc]
            prc_stages = [s for s in prc_all if s <= n_prc]
            erc_stages = [s for s in erc_all if s <= n_erc]
            furnaces = [f for f in furnace_all if f <= n_furnace]

            ans_chips = "  ".join(
                f'<span class="wizard-chip">{name}: {n}</span>'
                for name, n in [("CGC stages", n_cgc), ("PRC stages", n_prc),
                                ("ERC stages", n_erc), ("Furnaces", n_furnace)]
            )
            # st.markdown(f"**Your answers →** {ans_chips}", unsafe_allow_html=True)
            # st.markdown("<br>", unsafe_allow_html=True)

            gen_col, clr_col = st.columns([3, 1])
            with gen_col:
                run_wizard = st.button("⚡ Generate PI Mapping for this line-up", **FULL_WIDTH)
            with clr_col:
                if st.button("♻️ Reset mapping", **FULL_WIDTH):
                    st.session_state["generated_pi_mapping"] = pd.DataFrame(columns=PI_COLUMNS)
                    st.session_state["generated_tags"] = []
                    st.session_state["wizard_selection"] = {}
                    st.toast("Wizard mapping cleared.", icon="♻️")

            if run_wizard:
                mapping = generate_pi_mapping(pi_master, cgc_stages, prc_stages, erc_stages, furnaces)
                gen_tags = [t for t in mapping["Generalized Description"].dropna().unique()
                            if t in df.columns]
                st.session_state["generated_pi_mapping"] = mapping
                st.session_state["generated_tags"] = gen_tags
                st.session_state["wizard_selection"] = {
                    "CGC stages (answered)": [n_cgc], "PRC stages (answered)": [n_prc],
                    "ERC stages (answered)": [n_erc], "Furnaces (answered)": [n_furnace],
                    "CGC stages kept": cgc_stages, "PRC stages kept": prc_stages,
                    "ERC stages kept": erc_stages, "Furnaces kept": [f"F{n}" for n in furnaces],
                }
                st.toast("🎯 PI mapping generated!", icon="⚡")

            mapping = st.session_state["generated_pi_mapping"]
            if not mapping.empty:
                # m1, m2, m3 = st.columns(3)
                # m1.metric("Tags in generated mapping", len(mapping))
                # m2.metric("Tags excluded by line-up", len(pi_master) - len(mapping))
                # m3.metric("Tags matched in historian", len(st.session_state["generated_tags"]))

                # Clubbed section summary (tags grouped under CGC / PRC / ERC / Furnace ...)
                club_counts = mapping.groupby("Section").size().sort_values(ascending=False)
                club_chips = "  ".join(
                    f'<span class="wizard-chip">{sec}: {cnt} tags</span>'
                    for sec, cnt in club_counts.items()
                )
                st.markdown(f"**Clubbed by section →** {club_chips}", unsafe_allow_html=True)

                # with st.expander("🔎 Preview generated PI mapping (grouped by section)",
                #                  expanded=False):
                #     preview = mapping.sort_values(
                #         ["Section", "Generalized Description"]).reset_index(drop=True)
                #     sec_pick = st.selectbox(
                #         "Filter preview by section",
                #         options=["All"] + sorted(mapping["Section"].dropna().unique().tolist()),
                #         key="wiz_preview_section",
                #     )
                #     if sec_pick != "All":
                #         preview = preview[preview["Section"] == sec_pick].reset_index(drop=True)
                #     st.dataframe(preview, **FULL_WIDTH, height=320)
              
            
            
            
            
                with st.expander(
                    "🔎 Preview generated PI mapping (grouped by section)",
                    expanded=False
                ):
            
                    preview = mapping.sort_values(
                        ["Section", "Generalized Description"]
                    ).reset_index(drop=True)
            
            
                    sec_pick = st.selectbox(
                        "Filter preview by section",
                        options=[
                            "All"
                        ] + sorted(mapping["Section"].dropna().unique().tolist()),
                        key="wiz_preview_section",
                    )
            
            
                    if sec_pick != "All":
                        preview = preview[
                            preview["Section"] == sec_pick
                        ].reset_index(drop=True)


                    # Pi_tags column is intentionally kept EMPTY in the preview —
                    # the plant team fills in the raw PI tags manually (or via the
                    # uploaded config file later)
                    if "Pi_tags" in preview.columns:
                        preview["Pi_tags"] = ""
            
            
                    # Editable dropdown configuration
                    preview_cfg = {}
            
                    if "Pi_tags" in preview.columns:
                        preview_cfg["Pi_tags"] = st.column_config.TextColumn(
                            "Pi_tags",
                            help="Edit PI tag identifier"
                        )
            
            
                    if "Generalized Description" in preview.columns:
                        preview_cfg["Generalized Description"] = st.column_config.TextColumn(
                            "Generalized Description",
                            help="Edit parameter description"
                        )
            
            
                    if "Section" in preview.columns:
                        preview_cfg["Section"] = st.column_config.SelectboxColumn(
                            "Section",
                            options=[
                                "",
                                "CGC",
                                "PRC",
                                "ERC",
                                "Furnace",
                                "Quench",
                                "Cold"
                            ],
                            help="Select section"
                        )
            
            
                    # Editable preview table
                    edited_preview = st.data_editor(
                        preview,
                        column_config=preview_cfg,
                        key="wiz_editable_preview",
                        use_container_width=True,
                        height=320,
                        num_rows="dynamic"
                    )
            
            
                    # Apply changes
                    if st.button(
                        "💾 Update Generated Mapping",
                        key="update_generated_mapping"
                    ):
            
                        mapping = edited_preview.copy()
            
                        st.session_state["pi_mapping"] = mapping
            
                        st.success(
                            "Generated PI mapping updated successfully!"
                        )
            
            
            
            
            
            
            
            
            
            
            
            
            
            
            
                # ---------------- Mapping export ----------------
                exp1, exp2 = st.columns(2)
                with exp1:
                    def _sheet_or_placeholder_wiz(d):
                        return d if (d is not None and not d.empty) else pd.DataFrame([{"Equipment": None, "Selected": None}])
                    map_buf = io.BytesIO()
                    try:
                        with pd.ExcelWriter(map_buf, engine="openpyxl") as writer:
                            mapping.to_excel(writer, sheet_name=PI_SHEET, index=False)
                            sel_df = pd.DataFrame(
                                [(k, ", ".join(map(str, v))) for k, v in
                                 st.session_state["wizard_selection"].items()],
                                columns=["Equipment", "Selected"],
                            )
                            _sheet_or_placeholder_wiz(sel_df).to_excel(writer, sheet_name="Plant_lineup", index=False)
                        st.download_button(
                            "📥 Export mapping (.xlsx)",
                            data=map_buf.getvalue(),
                            file_name="Generated_PI_mapping.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            **FULL_WIDTH,
                        )
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Mapping export failed: {e}")
                with exp2:
                    st.download_button(
                        "📥 Export mapping (.csv)",
                        data=mapping.to_csv(index=False).encode("utf-8"),
                        file_name="Generated_PI_mapping.csv",
                        mime="text/csv",
                        **FULL_WIDTH,
                    )


    # -----------------------------------------------------------------
    # 2.3  Configuration editors — ONLY the two sheets required in the UI
    # -----------------------------------------------------------------
    def _apply_editor_delta(base_df: pd.DataFrame, delta: dict,
                            new_row_template: dict | None = None) -> pd.DataFrame:
        """Safely replays a st.data_editor delta onto a session DataFrame."""
        out = base_df.copy()
        try:
            if delta.get("deleted_rows"):
                keep = [i for i in range(len(out)) if i not in set(delta["deleted_rows"])]
                out = out.iloc[keep].reset_index(drop=True)
            for row in delta.get("added_rows", []):
                new_row = dict(new_row_template or {})
                new_row.update({k: v for k, v in row.items()
                                if k in out.columns or not out.columns.size})
                out = pd.concat([out, pd.DataFrame([new_row])], ignore_index=True)
            for idx, changes in (delta.get("edited_rows") or {}).items():
                idx = int(idx)
                if 0 <= idx < len(out):
                    for col, val in changes.items():
                        out.at[idx, col] = val
        except Exception:  # noqa: BLE001
            return base_df  # never corrupt config on a malformed delta
        return out

    def _panel_header(icon: str, title: str, desc: str, count: int, accent: str):
        st.markdown(
            f'''<div class="panel-header" style="--panel-accent-a: {accent}22;">
                    <span class="panel-icon">{icon}</span>
                    <div>
                        <p class="panel-title">{title}</p>
                        <p class="panel-desc">{desc}</p>
                    </div>
                    <span class="panel-count" style="background:{accent}22; color:{accent}; border:1px solid {accent}55;">
                        {count} row{'s' if count != 1 else ''}
                    </span>
                </div>''',
            unsafe_allow_html=True,
        )

    def _simple_editor(state_key: str, editor_key: str, column_config: dict,
                        panel: tuple | None = None):
        """Editable grid whose edits commit straight to session state.
        Coerces any TextColumn-configured column to string dtype first --
        values loaded from Excel (e.g. a 'Value'/'Remark' column that's
        all-numeric or all-blank) come in as float64/object and Streamlit
        refuses to bind those to a TextColumn otherwise.
        `panel`, if given, is (icon, title, description, accent_hex) and
        renders a colored header card above the grid instead of a bare table."""
        for _col, _cfg in column_config.items():
            _is_text = isinstance(_cfg, dict) and (_cfg.get("type_config") or {}).get("type") == "text"
            if _is_text and _col in st.session_state[state_key].columns:
                st.session_state[state_key][_col] = (
                    st.session_state[state_key][_col]
                    .apply(lambda v: "" if pd.isna(v) else str(v))
                    .astype(str)
                )

        if panel is not None:
            _icon, _title, _desc, _accent = panel
            _panel_header(_icon, _title, _desc, len(st.session_state[state_key]), _accent)

        def _cb():
            delta = st.session_state.get(editor_key)
            if delta:
                st.session_state[state_key] = _apply_editor_delta(
                    st.session_state[state_key], delta)
                # A reused widget key after a row is added/deleted can get
                # out of sync with the new row count (the next add then
                # silently fails to register) -- force a fresh key on the
                # very next render whenever the row count changes.
                if delta.get("added_rows") or delta.get("deleted_rows"):
                    st.session_state["editor_rev"] += 1
        st.markdown('<div class="panel-body-wrap">', unsafe_allow_html=True)
        st.data_editor(
            st.session_state[state_key],
            column_config=column_config,
            **FULL_WIDTH,
            num_rows="dynamic",
            key=editor_key,
            on_change=_cb,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    def _paste_from_excel(state_key: str, columns: list = None, label: str = "Paste from Excel"):
        """Small expander: paste tab-separated cells copied straight from Excel
        (no header row) and the table's row count adjusts automatically --
        no need to pre-create empty rows first. Works alongside the grid
        above; applying a paste bumps editor_rev so the grid refreshes."""
        cols = columns or list(st.session_state[state_key].columns)
        with st.expander(f"📋 {label}", expanded=False):
            st.caption("Copy cells from Excel (columns in order: "
                       f"{', '.join(cols)} — no header row) and paste below.")
            pasted = st.text_area(
                "Paste here", key=f"paste_{state_key}", height=120,
                label_visibility="collapsed",
                placeholder="Paste tab-separated rows here (as copied from Excel)...",
            )
            mode = st.radio(
                "Mode", ["Append to existing rows", "Replace all rows"],
                key=f"paste_mode_{state_key}", horizontal=True,
            )
            if st.button("✅ Apply paste", key=f"paste_apply_{state_key}"):
                text = pasted.strip("\n")
                if not text.strip():
                    st.warning("Paste some data first.")
                else:
                    rows = []
                    for line in text.split("\n"):
                        if not line.strip():
                            continue
                        cells = line.split("\t")
                        rows.append({c: (cells[i].strip() if i < len(cells) else "")
                                    for i, c in enumerate(cols)})
                    new_df = pd.DataFrame(rows, columns=cols)
                    if mode == "Replace all rows":
                        st.session_state[state_key] = new_df
                    else:
                        base = st.session_state[state_key]
                        st.session_state[state_key] = pd.concat(
                            [base, new_df], ignore_index=True)
                    st.session_state["editor_rev"] += 1
                    st.success(f"✅ {len(new_df)} row(s) pasted.")
                    st.rerun()
        if st.session_state.get(f"paste_{state_key}", "").strip():
            st.warning("⚠️ You have pasted text above that hasn't been applied yet — "
                       "open **📋 Paste from Excel** and click **Apply paste**, or it "
                       "won't be saved.")

    def _field_input(label: str, kind: str, value, key: str, options=None, help=None):
        """Renders one editable field as its own widget (used by the card view)."""
        if kind == "select":
            opts = list(options or [])
            if "" not in opts:
                opts = [""] + opts
            val = "" if pd.isna(value) else str(value)
            idx = opts.index(val) if val in opts else 0
            return st.selectbox(label, opts, index=idx, key=key, help=help)
        if kind == "number":
            try:
                num = float(value) if pd.notna(value) and str(value).strip() != "" else 0.0
            except (TypeError, ValueError):
                num = 0.0
            return st.number_input(label, value=num, key=key, help=help)
        val = "" if pd.isna(value) else str(value)
        return st.text_input(label, value=val, key=key, help=help)

    def _card_list_editor(state_key: str, field_specs: dict, panel: tuple, title_fn,
                          empty_hint: str = "No entries yet — add the first one below."):
        """Record-card alternative to the grid: one card per row with its
        fields as normal widgets, a delete button per card, and an
        'Add new entry' card at the bottom. Reads/writes the same
        session-state DataFrame as _simple_editor, so Save/Download and
        everything downstream works identically either way."""
        icon, title, desc, accent = panel
        df_state = st.session_state[state_key]
        _panel_header(icon, title, desc, len(df_state), accent)

        rev = st.session_state["editor_rev"]
        active_fields = {c: spec for c, spec in field_specs.items() if c in df_state.columns}
        n_cols = min(3, max(1, len(active_fields)))

        query = st.text_input(
            "Filter", key=f"filter_{state_key}_{rev}",
            placeholder="🔎 Type to filter these entries...", label_visibility="collapsed",
        )
        indices = list(df_state.index)
        if query.strip():
            q = query.strip().lower()
            indices = [i for i in indices
                       if any(q in str(df_state.loc[i, c]).lower() for c in active_fields)]

        if df_state.empty:
            st.info(empty_hint)
        elif not indices:
            st.caption("No entries match your filter.")

        delete_idx = None
        for idx in indices:
            row = df_state.loc[idx]
            with _bordered_container():
                head_col, del_col = st.columns([8, 1])
                with head_col:
                    st.markdown(f"**{title_fn(row)}**")
                with del_col:
                    if st.button("🗑️", key=f"del_{state_key}_{idx}_{rev}", help="Delete this entry"):
                        delete_idx = idx
                cols = st.columns(n_cols)
                for i, (col, spec) in enumerate(active_fields.items()):
                    with cols[i % n_cols]:
                        new_val = _field_input(
                            spec.get("label", col), spec.get("type", "text"),
                            row.get(col), key=f"{state_key}_{idx}_{col}_{rev}",
                            options=spec.get("options"), help=spec.get("help"),
                        )
                        df_state.at[idx, col] = new_val

        if delete_idx is not None:
            st.session_state[state_key] = df_state.drop(index=delete_idx).reset_index(drop=True)
            st.session_state["editor_rev"] += 1
            st.rerun()
        else:
            st.session_state[state_key] = df_state

        with _bordered_container():
            st.markdown("**➕ Add new entry**")
            cols = st.columns(n_cols)
            new_row = {}
            for i, (col, spec) in enumerate(active_fields.items()):
                with cols[i % n_cols]:
                    new_row[col] = _field_input(
                        spec.get("label", col), spec.get("type", "text"), "",
                        key=f"new_{state_key}_{col}_{rev}",
                        options=spec.get("options"), help=spec.get("help"),
                    )
            if st.button("➕ Add entry", key=f"add_{state_key}_{rev}", **FULL_WIDTH):
                base_cols = list(df_state.columns) if len(df_state.columns) else list(active_fields.keys())
                row_to_add = {c: new_row.get(c) for c in base_cols}
                st.session_state[state_key] = pd.concat(
                    [st.session_state[state_key], pd.DataFrame([row_to_add])], ignore_index=True
                )
                st.session_state["editor_rev"] += 1
                st.rerun()

    # -----------------------------------------------------------------
    # KPI strip -- quick at-a-glance counts for all 5 config sheets
    # -----------------------------------------------------------------
    _kpi_defs = [
        ("🏷️", len(st.session_state["pi_names_df"]), "PI Tags", "#38bdf8"),
        ("🧠", len(st.session_state["model_details_df"]), "Model Rows", "#818cf8"),
        ("🚧", len(st.session_state["constraints_df"]), "Constraints", "#f97316"),
        ("🎚️", len(st.session_state["user_inputs_df"]), "User Inputs", "#22c55e"),
        ("📋", len(st.session_state["display_order_df"]), "Column Order", "#14b8a6"),
        ("🔀", len(st.session_state["section_order_df"]), "Section Order", "#eab308"),
        ("🧾", len(st.session_state["mvdvcv_df"]), "MV/DV/CV Tags", "#a855f7"),
    ]
    st.markdown(
        '<div class="kpi-strip">' + "".join(
            f'''<div class="kpi-card" style="--kpi-accent: {accent};">
                    <div class="kpi-num">{icon} {count}</div>
                    <div class="kpi-label">{label}</div>
                </div>'''
            for icon, count, label, accent in _kpi_defs
        ) + '</div>',
        unsafe_allow_html=True,
    )

    # -----------------------------------------------------------------
    # The Configuration Hub is ALWAYS available -- it's how a plant's
    # entire Config_file_updated.xlsx (all 5 sheets) gets built and saved, with
    # or without ever uploading a workbook. Uploading remains an
    # optional way to pre-fill these tables (see the expander above);
    # everything can equally be typed/added directly in the editors below.
    # -----------------------------------------------------------------
    _view_mode = st.radio(
        "View", ["🗂️ Cards", "📊 Table"], index=1, horizontal=True,
        key="config_view_mode", label_visibility="collapsed",
    )
    _cards_mode = _view_mode.endswith("Cards")

    # -----------------------------------------------------------------
    # GUIDED, SEQUENTIAL STEP-BY-STEP CONFIGURATION WORKFLOW
    #   Step 1:  Process Execution Order
    #   Step 2:  Target Section (auto-includes all upstream sections)
    #   Step 3:  PI Tag Mapping        (scoped to the active section(s))
    #   Step 4:  MV/DV/CV Tag List     (optional)
    #   Step 5:  Training Dataset Upload
    #   Step 6:  Correlation Matrix    (optional)
    #   Step 7:  Model Mapping         (scoped to the active section(s))
    #   Step 8:  Constraints
    #   Step 9:  User Inputs
    #   Step 10: Column Order
    #   Step 11: Train Models
    # Only ONE step is shown at a time. "Save & Continue" stays disabled
    # until the current step validates. Uploading a full workbook (see
    # the expander above) still pre-fills everything at once -- in that
    # case every step already validates, so the wizard opens on the
    # last step, with a clickable breadcrumb to jump back and review or
    # edit any earlier step.
    # -----------------------------------------------------------------
    _STEP_LABELS = {
        1: "🔀 Process Order",
        2: "🎯 Target Section",
        3: "🏷️ PI Tag Mapping",
        4: "🧾 MV/DV/CV Tag List",
        5: "📤 Training Dataset",
        6: "📈 Correlation Matrix",
        7: "🧠 Model Mapping",
        8: "🚧 Constraints",
        9: "🎚️ User Inputs",
        10: "📋 Column Order",
        11: "🧠 Train Models",
    }
    _N_STEPS = len(_STEP_LABELS)

    def _scoped_editor(state_key, editor_key, column_config, panel, scope_mask_fn,
                        new_row_template=None):
        """Like _simple_editor, but only shows/edits rows for which
        scope_mask_fn(row) is True. Every row outside that scope is left
        completely untouched in st.session_state[state_key] and spliced
        back in unchanged after every edit -- so switching Target Section
        never loses data mapped to a different section."""
        full_df = st.session_state[state_key]
        for _col, _cfg in column_config.items():
            _is_text = isinstance(_cfg, dict) and (_cfg.get("type_config") or {}).get("type") == "text"
            if _is_text and _col in full_df.columns:
                full_df[_col] = full_df[_col].apply(lambda v: "" if pd.isna(v) else str(v)).astype(str)
        if full_df.empty:
            in_scope, out_scope = full_df.copy(), full_df.copy()
        else:
            mask = full_df.apply(scope_mask_fn, axis=1)
            in_scope = full_df[mask].reset_index(drop=True)
            out_scope = full_df[~mask].reset_index(drop=True)

        if panel is not None:
            _icon, _title, _desc, _accent = panel
            _panel_header(_icon, _title, _desc, len(in_scope), _accent)

        def _cb():
            delta = st.session_state.get(editor_key)
            if delta:
                merged = _apply_editor_delta(in_scope, delta, new_row_template)
                st.session_state[state_key] = pd.concat([out_scope, merged], ignore_index=True)
                if delta.get("added_rows") or delta.get("deleted_rows"):
                    st.session_state["editor_rev"] += 1

        st.markdown('<div class="panel-body-wrap">', unsafe_allow_html=True)
        st.data_editor(
            in_scope, column_config=column_config, **FULL_WIDTH,
            num_rows="dynamic", key=editor_key, on_change=_cb,
        )
        st.markdown('</div>', unsafe_allow_html=True)
        if len(out_scope):
            st.caption(f"ℹ️ {len(out_scope)} row(s) belonging to other sections are hidden "
                       f"here (left untouched) -- change the Target Section in Step 2 to edit them.")

    def _cs_allowed_secs() -> set:
        return {s.strip().lower() for s in
                allowed_sections_upto(get_section_order(), st.session_state.get("target_section"))}

    def _in_section_scope(row, allowed: set) -> bool:
        sec = str(row.get("Section", "")).strip().lower()
        if not sec or sec == "nan":
            for _fld in ("Generalized Description", "Pi_tags", "Predicted parameter",
                        "GeneralizedDescription", "Name"):
                _guess = infer_section(row.get(_fld, ""))
                if _guess:
                    sec = _guess.strip().lower()
                    break
        return (not sec) or (sec == "nan") or (sec in allowed)

    def _cs_tag_section_map() -> dict:
        m = {}
        pdf = st.session_state.get("pi_names_df")
        if pdf is not None and not pdf.empty and {"Generalized Description", "Section"}.issubset(pdf.columns):
            m.update(dict(zip(pdf["Generalized Description"].astype(str).str.strip(),
                              pdf["Section"].astype(str).str.strip())))
        mdf = st.session_state.get("model_details_df")
        if mdf is not None and not mdf.empty and {"Predicted parameter", "Section"}.issubset(mdf.columns):
            m.update(dict(zip(mdf["Predicted parameter"].astype(str).str.strip(),
                              mdf["Section"].astype(str).str.strip())))
        return m

    def _cs_scoped_tag_options() -> list:
        """tag_options restricted to the active process scope (Step 2's target
        section + everything upstream). Falls back to name-based inference
        (infer_section) for a tag with no explicit Section anywhere -- e.g. a
        raw input tag that's only ever used as a model INPUT, never its own
        'Predicted parameter' or PI Tag Mapping row -- so it's still scoped
        correctly instead of always being shown regardless of target section."""
        allowed = _cs_allowed_secs()
        if not allowed:
            return tag_options
        m = _cs_tag_section_map()

        def _tag_in_scope(t: str) -> bool:
            sec = m.get(t, "").strip().lower()
            if not sec:
                sec = infer_section(t).strip().lower()
            return (not sec) or (sec in allowed)

        return [t for t in tag_options if _tag_in_scope(t)]

    def _mvdvcv_tag_names() -> list:
        """MV/DV/CV Tag List's GeneralizedDescription values, scoped to the
        active process scope, in the list's own row order."""
        mdf = st.session_state.get("mvdvcv_df")
        if mdf is None or mdf.empty or "GeneralizedDescription" not in mdf.columns:
            return []
        allowed = _cs_allowed_secs()
        out = []
        for _, row in mdf.iterrows():
            name = str(row.get("GeneralizedDescription", "")).strip()
            if not name or name.lower() == "nan":
                continue
            if _in_section_scope(row, allowed):
                out.append(name)
        seen, deduped = set(), []
        for n in out:
            if n.lower() not in seen:
                seen.add(n.lower())
                deduped.append(n)
        return deduped

    def _cs_model_input_options() -> list:
        """Input-tag options for Model Mapping's dropdown, prioritized: MV/DV/CV
        Tag List tags first (highest priority, scoped to the active process
        scope), then every remaining scoped PI tag."""
        mv_tags = _mvdvcv_tag_names()
        mv_lower = {t.lower() for t in mv_tags}
        other_tags = [t for t in _cs_scoped_tag_options() if t.lower() not in mv_lower]
        return mv_tags + other_tags

    def _valid_step1() -> bool:
        so_df = st.session_state.get("section_order_df")
        if so_df is None or so_df.empty or "Section" not in so_df.columns:
            return False
        secs = [str(s).strip() for s in so_df["Section"]
                if str(s).strip() and str(s).strip().lower() != "nan"]
        # A genuine process *sequence* needs at least 2 sections, all distinct.
        return len(secs) >= 2 and len({s.lower() for s in secs}) == len(secs)

    def _valid_step2() -> bool:
        t = st.session_state.get("target_section")
        return bool(t) and t in get_section_order()

    def _valid_step3() -> bool:
        pdf = st.session_state.get("pi_names_df")
        if pdf is None or pdf.empty or not {"Pi_tags", "Generalized Description"}.issubset(pdf.columns):
            return False
        allowed = _cs_allowed_secs()
        scoped = pdf[pdf.apply(lambda r: _in_section_scope(r, allowed), axis=1)]
        tags = scoped["Pi_tags"].astype(str).str.strip()
        descs = scoped["Generalized Description"].astype(str).str.strip()
        valid_rows = scoped[(tags != "") & (tags.str.lower() != "nan") & (descs != "")]
        return len(valid_rows) >= 1

    def _valid_step5() -> bool:
        # Step 5 = Training Dataset (moved after MV/DV/CV Tag List)
        return bool(st.session_state.get("training_data_ready"))

    def _valid_optional_step(n: int) -> bool:
        # MV/DV/CV Tag List (4) / Correlation Matrix (6) / Constraints (8) /
        # User Inputs (9) / Column Order (10) stay genuinely optional -- an
        # empty/unreviewed sheet is legitimate, so there's nothing to
        # validate here. (Previously this required cs_ack_{n} to already
        # be True for the Continue button to be enabled -- but clicking
        # that same button was the only way to SET cs_ack_{n}, so the
        # button was permanently stuck disabled. Optional steps should
        # simply always be advanceable.)
        return True

    def _valid_step7() -> bool:
        # Step 7 = Model Mapping (moved down after Training Dataset / MV-DV-CV / Correlation Matrix)
        mdf = st.session_state.get("model_details_df")
        if mdf is None or mdf.empty or "Predicted parameter" not in mdf.columns:
            return False
        allowed = _cs_allowed_secs()
        scoped = mdf[mdf.apply(lambda r: _in_section_scope(r, allowed), axis=1)]
        preds = scoped["Predicted parameter"].astype(str).str.strip()
        valid_rows = scoped[(preds != "") & (preds.str.lower() != "nan")]
        return len(valid_rows) >= 1

    def _valid_step11() -> bool:
        # Step 11 = Train Models (final step)
        return bool(st.session_state.get("setup_complete"))

    _VALIDATORS = {1: _valid_step1, 2: _valid_step2, 3: _valid_step3,
                   4: lambda: _valid_optional_step(4), 5: _valid_step5,
                   6: lambda: _valid_optional_step(6), 7: _valid_step7,
                   8: lambda: _valid_optional_step(8), 9: lambda: _valid_optional_step(9),
                   10: lambda: _valid_optional_step(10), 11: _valid_step11}

    # How far a bulk upload's data alone would satisfy validation, step by
    # step -- used ONLY to fast-forward right after an upload (see below).
    def _fresh_validity_frontier() -> int:
        for _s in range(1, _N_STEPS + 1):
            if not _VALIDATORS[_s]():
                return _s
        return _N_STEPS

    # The furthest step the user has explicitly reached so far. This is a
    # one-way "high-water mark", NOT reactively recomputed from live data
    # validity on every render -- so editing data on the CURRENT step (e.g.
    # adding PI tags in Step 3) can never retroactively re-evaluate and
    # silently snap the user back to an earlier step. It only ever grows,
    # and only via an explicit "Save & Continue" click or a breadcrumb
    # click, both of which are themselves gated by that step's own
    # validator at the moment of the click.
    st.session_state.setdefault("cs_max_reached", 1)

    # A full workbook upload pre-fills everything in one shot -- in that
    # case ONLY, fast-forward to the furthest step its data already
    # satisfies, so the user lands on a "review" view instead of being
    # marched through several clicks.
    if st.session_state.get("_cs_bulk_loaded"):
        _bulk_frontier = _fresh_validity_frontier()
        st.session_state["cs_step"] = _bulk_frontier
        st.session_state["cs_max_reached"] = max(st.session_state["cs_max_reached"], _bulk_frontier)
        st.session_state["_cs_bulk_loaded"] = False

    cs_step = st.session_state.get("cs_step", 1)

    # If a config workbook was uploaded, the process order + target section
    # are already known from that upload -- Step 2 (Target Section) is
    # skipped entirely rather than asked again. Auto-default the target
    # section to the full scope (the last/most-downstream section) if the
    # uploaded workbook predates the "Target Section" sheet, so validation
    # still passes without asking the user anything.
    _upload_skips_step2 = bool(st.session_state.get("config_file_uploaded"))
    if _upload_skips_step2:
        _order_now = get_section_order()
        if _order_now and st.session_state.get("target_section") not in _order_now:
            st.session_state["target_section"] = _order_now[-1]
        if cs_step == 2:
            cs_step = 3
            st.session_state["cs_step"] = 3

    st.session_state["cs_max_reached"] = max(st.session_state["cs_max_reached"], cs_step)
    _unlocked_through = st.session_state["cs_max_reached"]
    st.session_state["cs_step"] = cs_step

    # --- Progress indicator + clickable breadcrumb (only up to _unlocked_through) ---
    # _visible_steps holds the INTERNAL step numbers actually shown (Step 2 is
    # dropped entirely when a config workbook was uploaded). _display_number
    # maps each internal step to its 1-based position in that visible
    # sequence, so the UI always reads "Step 1 of 8", "Step 2 of 8", ... with
    # no gaps -- never "Step 3 of 9" with an invisible missing Step 2.
    _visible_steps = [s for s in range(1, _N_STEPS + 1) if not (_upload_skips_step2 and s == 2)]
    _display_total = len(_visible_steps)
    _display_number = {s: i + 1 for i, s in enumerate(_visible_steps)}
    st.progress(_display_number[cs_step] / _display_total,
                text=f"Step {_display_number[cs_step]} of {_display_total}: {_STEP_LABELS[cs_step]}")
    _crumb_cols = st.columns(_display_total)
    for _col, _s in zip(_crumb_cols, _visible_steps):
        with _col:
            _reachable = _s <= _unlocked_through
            if _s < cs_step and _VALIDATORS[_s]():
                _prefix = "✅ "
            elif _s == cs_step:
                _prefix = "👉 "
            elif not _reachable:
                _prefix = "🔒 "
            else:
                _prefix = "⬜ "
            if st.button(f"{_prefix}{_display_number[_s]}", key=f"cs_jump_{_s}", disabled=not _reachable,
                         help=_STEP_LABELS[_s], **FULL_WIDTH):
                st.session_state["cs_step"] = _s
                st.rerun()
    st.divider()

    def _step_nav(step_n: int, valid: bool, invalid_msg: str):
        """Back / Save & Continue footer for one step."""
        nav_l, nav_r = st.columns([1, 1])
        with nav_l:
            _back_target = step_n - 1
            if _upload_skips_step2 and _back_target == 2:
                _back_target = 1
            if step_n > 1 and st.button("◀ Back", key=f"cs_back_{step_n}"):
                st.session_state["cs_step"] = _back_target
                st.rerun()
        with nav_r:
            label = "🏁 Finish" if step_n == _N_STEPS else "Save & Continue ▶"
            if st.button(label, key=f"cs_next_{step_n}", disabled=not valid, **FULL_WIDTH):
                st.session_state[f"cs_ack_{step_n}"] = True
                _next_target = step_n + 1
                if _upload_skips_step2 and _next_target == 2:
                    _next_target = 3
                if step_n < _N_STEPS:
                    st.session_state["cs_step"] = _next_target
                    st.rerun()
        if not valid:
            st.warning(f"⚠️ {invalid_msg}")

    # =================================================================
    # STEP 1 -- Process Execution Order
    # =================================================================
    if cs_step == 1:
        st.caption("Enter plant sections in actual process order (e.g. Furnace, Quench, CGC, ERC, PRC, Cold).")
        section_order_cfg = {
            "Sr.no": st.column_config.NumberColumn("Sr.no", help="1 = most upstream"),
            "Section": st.column_config.TextColumn("Section"),
        }
        section_order_field_specs = {
            "Sr.no": {"type": "number", "help": "1 = most upstream"},
            "Section": {"type": "text"},
        }
        _section_order_panel = ("🔀", "Process Flow Order",
                                "Upstream → downstream sequence.",
                                "#eab308")
        if _cards_mode:
            _card_list_editor(
                "section_order_df", section_order_field_specs, _section_order_panel,
                title_fn=lambda row: f"#{row.get('Sr.no')}: {row.get('Section') or '?'}",
                empty_hint="Add the first (most upstream) section below.",
            )
        else:
            _simple_editor(
                "section_order_df",
                f"ui_editor_section_order_r{st.session_state['editor_rev']}",
                section_order_cfg,
                panel=_section_order_panel,
            )
        _paste_from_excel("section_order_df", ["Sr.no", "Section"], "Paste from Excel")
        _preview_order = get_section_order()
        if _preview_order:
            st.caption("Order: " + " → ".join(f"`{s}`" for s in _preview_order))
        _step_nav(1, _valid_step1(),
                 "Add at least 2 distinct sections, in process order, before continuing.")

    # =================================================================
    # STEP 2 -- Target Section
    # =================================================================
    elif cs_step == 2:
        _order = get_section_order()
        st.caption(
            "Select the target section for this What-if study. The active process "
            "scope automatically becomes every upstream section plus this one -- "
            "downstream sections are excluded from PI Tag Mapping, Model Mapping, "
            "and prediction. You can still change this later from the 📊 What-if "
            "Dashboard tab before running a scenario."
        )
        if st.session_state.get("target_section") not in _order:
            st.session_state["target_section"] = _order[-1] if _order else None
        st.selectbox(
            "Target section", options=_order, key="target_section",
            help="Everything from the start of the Process Flow Order up to and "
                 "including this section becomes the active scope.",
        )
        _scope_now = allowed_sections_upto(_order, st.session_state.get("target_section"))
        _excluded_now = [s for s in _order if s not in _scope_now]
        st.markdown(
            "**Active scope (upstream → target):** " + " → ".join(f"`{s}`" for s in _scope_now) +
            (f"  \n**Excluded (downstream):** " + ", ".join(f"`{s}`" for s in _excluded_now)
             if _excluded_now else "")
        )
        _step_nav(2, _valid_step2(), "Select a target section before continuing.")

    # =================================================================
    # STEP 3 -- PI Tag Mapping (scoped to the active section(s))
    # =================================================================
    elif cs_step == 3:
        _scope = sorted(allowed_sections_upto(get_section_order(), st.session_state.get("target_section")))
        st.caption(
            f"Only PI tags belonging to the active scope (**{', '.join(_scope) or '—'}**) are "
            "shown below. Map at least one tag before continuing; unclassified tags "
            "(blank Section) are also shown here so you can classify them."
        )
        pi_cfg = {
            "Pi_tags": st.column_config.TextColumn("Pi_tags", help="Raw PI tag identifier"),
            "Generalized Description": st.column_config.TextColumn(
                "Generalized Description", help="Human-readable parameter name"),
            "Section": st.column_config.SelectboxColumn(
                "Section", options=[""] + get_section_order(),
                help="Plant area this tag belongs to"),
        }
        _pi_panel = ("🏷️", "PI Tag Mapping",
                     "Master PI dictionary (Pi_tags → Generalized Description → Section), "
                     "scoped to the active Target Section.",
                     "#38bdf8")
        _allowed = _cs_allowed_secs()
        _scoped_editor(
            "pi_names_df",
            f"ui_editor_pi_names_r{st.session_state['editor_rev']}",
            {k: v for k, v in pi_cfg.items() if k in st.session_state["pi_names_df"].columns},
            _pi_panel,
            scope_mask_fn=lambda r: _in_section_scope(r, _allowed),
        )
        _paste_from_excel("pi_names_df", ["Pi_tags", "Generalized Description", "Section"],
                          "Paste from Excel")
        _step_nav(3, _valid_step3(),
                 "Map at least one PI tag (Pi_tags + Generalized Description) in the "
                 "active scope before continuing.")

    # =================================================================
    # STEP 4 -- MV/DV/CV Tag List
    # =================================================================
    elif cs_step == 4:
        st.caption("Optional: upload an MV/DV/CV tag list, or build one below -- "
                   "these tags get top priority in Model Mapping's input dropdown.")

        with st.expander("📂 Upload MV/DV/CV tag list (optional)",
                          expanded=st.session_state["mvdvcv_df"].empty):
            st.caption("Expected columns: Name, GeneralizedDescription, Section, Type.")
            _mvdvcv_upload = st.file_uploader(
                "MV_DV_CV_taglist.xlsx", type=["xlsx", "xls"],
                key="mvdvcv_uploader", label_visibility="collapsed",
            )
            if _mvdvcv_upload is not None:
                _mv_sig = f"{_mvdvcv_upload.name}:{_mvdvcv_upload.size}"
                if st.session_state.get("_last_mvdvcv_upload_sig") != _mv_sig:
                    try:
                        _mv_xl = pd.ExcelFile(_mvdvcv_upload)
                        _mv_df = (pd.read_excel(_mv_xl, sheet_name=_mv_xl.sheet_names[0])
                                  .dropna(how="all").reset_index(drop=True))
                        # Tolerate minor header naming differences on upload
                        _rename_map = {}
                        for c in _mv_df.columns:
                            cl = str(c).strip().lower().replace(" ", "").replace("_", "")
                            if cl in ("name", "pitag", "tag"):
                                _rename_map[c] = "Name"
                            elif cl in ("generalizeddescription", "generaliseddescription", "description"):
                                _rename_map[c] = "GeneralizedDescription"
                            elif cl == "section":
                                _rename_map[c] = "Section"
                            elif cl == "type":
                                _rename_map[c] = "Type"
                        _mv_df = _mv_df.rename(columns=_rename_map)
                        for _need in ("Name", "GeneralizedDescription", "Section", "Type"):
                            if _need not in _mv_df.columns:
                                _mv_df[_need] = ""
                        st.session_state["mvdvcv_df"] = _mv_df[["Name", "GeneralizedDescription", "Section", "Type"]]
                        st.session_state["_last_mvdvcv_upload_sig"] = _mv_sig
                        st.session_state["editor_rev"] += 1
                        st.success(f"✅ Loaded {len(_mv_df)} tag(s).")
                        st.rerun()
                    except Exception as _mv_err:  # noqa: BLE001
                        st.error(f"⚠️ Could not read this workbook: {_mv_err}")

        st.markdown("###### Or build / edit the list here")
        mvdvcv_cfg = {
            "Name": st.column_config.TextColumn("Name", help="Raw PI tag identifier"),
            "GeneralizedDescription": st.column_config.TextColumn(
                "GeneralizedDescription", help="Human-readable parameter name -- must match "
                                                "the historian column name to be usable"),
            "Section": st.column_config.SelectboxColumn(
                "Section", options=[""] + get_section_order(), help="Plant area this tag belongs to"),
            "Type": st.column_config.SelectboxColumn(
                "Type", options=["", "MV", "DV", "CV"],
                help="Manipulated / Disturbance / Controlled variable"),
        }
        _mvdvcv_panel = ("🧾", "MV/DV/CV Tag List",
                        "Prioritized input-tag source for Model Mapping. Optional -- Model "
                        "Mapping still offers every PI tag either way.",
                        "#a855f7")
        _allowed_mv = _cs_allowed_secs()
        _scoped_editor(
            "mvdvcv_df",
            f"ui_editor_mvdvcv_r{st.session_state['editor_rev']}",
            mvdvcv_cfg,
            _mvdvcv_panel,
            scope_mask_fn=lambda r: _in_section_scope(r, _allowed_mv),
        )
        _paste_from_excel("mvdvcv_df", ["Name", "GeneralizedDescription", "Section", "Type"],
                          "Paste from Excel")
        _step_nav(4, _VALIDATORS[4](), "Click Save & Continue to confirm this step (can be left empty).")

    # =================================================================
    # STEP 5 -- Training Dataset Upload
    # =================================================================
    elif cs_step == 5:
        st.caption("Upload the training workbook ('PI data' / 'Furnace data' sheets).")
        dmc_upload = st.file_uploader(
            "DMC_Screen_tags_data.xlsx", type=["xlsx", "xls"],
            key="dmc_workbook_uploader", label_visibility="collapsed",
        )

        _workbook_on_disk = os.path.isfile(TRAIN_WORKBOOK)
        if _workbook_on_disk and dmc_upload is None:
            st.session_state["training_data_ready"] = True
            st.info(f"📄 Already on disk: `{TRAIN_WORKBOOK}` — upload a new file only to replace it.")

        if dmc_upload is not None:
            try:
                _xl = pd.ExcelFile(dmc_upload)
                _found_sheets = [s for s in ("PI data", "Furnace data") if s in _xl.sheet_names]
                _missing_sheets = [s for s in ("PI data", "Furnace data") if s not in _xl.sheet_names]
                if not _found_sheets:
                    st.error("🚨 Neither 'PI data' nor 'Furnace data' found — at least one is required.")
                else:
                    if _missing_sheets:
                        st.warning("⚠️ Missing: " + " or ".join(_missing_sheets) +
                                   " — parameters relying on it won't be trained.")
                    else:
                        st.success("✅ Both 'PI data' and 'Furnace data' present.")
                    if st.button("💾 Save training dataset", **FULL_WIDTH):
                        os.makedirs(TRAIN_DATA_DIR, exist_ok=True)
                        with open(TRAIN_WORKBOOK, "wb") as _f:
                            _f.write(dmc_upload.getvalue())
                        st.session_state["training_data_ready"] = True
                        st.success("✅ Training workbook saved.")
            except Exception as save_err:  # noqa: BLE001
                st.error(f"Failed to read/save the training workbook: {save_err}")

        _step_nav(5, _VALIDATORS[5](), "Save a training dataset before continuing.")

    # =================================================================
    # STEP 6 -- Correlation Matrix
    # =================================================================
    elif cs_step == 6:
        st.caption("Pearson correlation of the uploaded training data -- spot strongly "
                   "related tags before mapping model inputs in the next step.")

        _train_mtime = os.path.getmtime(TRAIN_WORKBOOK) if os.path.isfile(TRAIN_WORKBOOK) else 0.0
        df_corr, _n_numeric_cols, _n_rows = get_cached_corr_matrix(TRAIN_WORKBOOK, _train_mtime)

        if not os.path.isfile(TRAIN_WORKBOOK):
            st.warning("⚠️ No training dataset found yet -- go back to Step 5 and "
                       "upload/save one first.")
        elif df_corr is None:
            st.warning(f"⚠️ Only {_n_numeric_cols} numeric column(s) found -- need at "
                       "least 2 to compute a correlation matrix.")
        else:
            st.caption(f"{_n_numeric_cols} numeric column(s), {_n_rows} row(s) "
                       f"loaded from the training workbook. (Cached -- recomputes "
                       "automatically only when a new training dataset is saved.)")

            def _color_columns(val):
                if pd.isna(val):
                    return ""
                if val > 0.4:
                    return "background-color: #1b8a3a; color: white"
                elif val < -0.4:
                    return "background-color: #c0392b; color: white"
                return ""

            def _style_elementwise(styler, func):
                """pandas >=2.1 renamed Styler.applymap to Styler.map, and
                pandas 3.0 removed applymap entirely -- try the new name
                first, fall back to the old one for older pandas."""
                try:
                    return styler.map(func)
                except AttributeError:
                    return styler.applymap(func)

            st.dataframe(
                _style_elementwise(df_corr.style, _color_columns),
                **FULL_WIDTH, height=min(600, 42 + 32 * len(df_corr)),
            )
            st.caption("🟩 > 0.4 positive correlation   🟥 < -0.4 negative correlation")

            _dl_col, _save_col = st.columns(2)
            with _dl_col:
                st.download_button(
                    "📥 Download correlation matrix (.csv)",
                    data=df_corr.to_csv().encode("utf-8"),
                    file_name="correlation_matrix.csv", mime="text/csv",
                    **FULL_WIDTH,
                )
            with _save_col:
                if st.button("💾 Save color-conditioned .xlsx to Results", **FULL_WIDTH):
                    try:
                        os.makedirs(RESULTS_DIR, exist_ok=True)
                        _corr_path = os.path.join(
                            RESULTS_DIR, "correlation_with_color_conditioning.xlsx")
                        with pd.ExcelWriter(_corr_path, engine="openpyxl") as _writer:
                            _style_elementwise(df_corr.style, _color_columns).to_excel(
                                _writer, index=True)
                        st.success(f"✅ Saved to `{_corr_path}`.")
                    except Exception as _corr_err:  # noqa: BLE001
                        st.error(f"⚠️ Could not save the correlation workbook: {_corr_err}")

        _step_nav(6, _VALIDATORS[6](), "Click Save & Continue to continue (optional).")

    # =================================================================
    # STEP 7 -- Model Mapping (scoped to the active section(s))
    # =================================================================
    elif cs_step == 7:
        if "Section" not in st.session_state["model_details_df"].columns:
            _mdf = st.session_state["model_details_df"].copy()
            _insert_at = 1 if "Predicted parameter" in _mdf.columns else 0
            _mdf.insert(_insert_at, "Section", "")
            st.session_state["model_details_df"] = _mdf
        _scope = sorted(allowed_sections_upto(get_section_order(), st.session_state.get("target_section")))
        st.caption(f"Active scope: **{', '.join(_scope) or '—'}**. Downstream models are hidden.")
        _section_choices = [""] + get_section_order()
        _scoped_tags = _cs_model_input_options()  # MV/DV/CV tags first, then remaining PI tags
        model_cfg = {}
        for col in st.session_state["model_details_df"].columns:
            if "predicted" in col.lower():
                model_cfg[col] = st.column_config.TextColumn(
                    col, help="Name of the parameter this model predicts")
            elif col.strip().lower() == "section":
                model_cfg[col] = st.column_config.SelectboxColumn(
                    col, options=_section_choices,
                    help="Plant section this predicted parameter belongs to -- used "
                         "to scope What-if runs to a target section + its upstream sections.")
            elif any(k in col.lower() for k in ["input", "tag", "pi_tags", "source"]):
                model_cfg[col] = st.column_config.SelectboxColumn(
                    col, options=[""] + _scoped_tags, help=f"Select process tag for {col}")
        _model_panel = ("🧠", "Model Mapping",
                        "Predicted parameter → model input parameters, scoped to the "
                        "active Target Section. Type a new 'Predicted parameter' name to "
                        "define a model from scratch.",
                        "#818cf8")
        _allowed = _cs_allowed_secs()
        _scoped_editor(
            "model_details_df",
            f"ui_editor_model_details_r{st.session_state['editor_rev']}",
            model_cfg,
            _model_panel,
            scope_mask_fn=lambda r: _in_section_scope(r, _allowed),
        )
        _paste_from_excel("model_details_df", list(st.session_state["model_details_df"].columns),
                          "Paste from Excel")
        _step_nav(7, _valid_step7(),
                 "Map at least one predicted parameter in the active scope before continuing.")

    # =================================================================
    # STEP 8 -- Constraints (structure unchanged from before)
    # =================================================================
    elif cs_step == 8:
        with st.expander("ℹ️ How this works (simple explanation)", expanded=False):
            st.markdown(
                "Each row is a rule that watches one parameter.\n\n"
                "- **To push another parameter to its max when this one is low:** "
                "fill in **Linked Parameter** (the one to push up) and set "
                "**Action** to `bump_linked_to_max`.\n"
                "  - *Example:* if steam flow AND turbine RPM are both still "
                "below your limit, the RPM gets pushed up to its max automatically.\n\n"
                "- **To stop the run if this parameter goes too high (a safety limit):** "
                "set **Action** to `abort_if_exceeds`, and leave Linked Parameter blank.\n"
                "  - *Example:* if discharge pressure goes above your limit, the run stops "
                "instead of pushing the feed further."
            )
        _param_choices = [""] + sorted(set(
            list(st.session_state["constraints_df"].get("Parameter", pd.Series(dtype=str)).dropna().astype(str))
            + _cs_scoped_tag_options()
        ))
        constraints_cfg = {
            "Parameter": st.column_config.SelectboxColumn(
                "Parameter", options=_param_choices, help="The trigger/limited parameter"
            ),
            "user input value": st.column_config.NumberColumn(
                "user input value", help="Operating limit used in the constraint check"
            ),
            "Max vlaue": st.column_config.NumberColumn(
                "Max vlaue", help="Value to bump the Linked Parameter to when triggered"
            ),
            "Max value": st.column_config.NumberColumn(
                "Max value", help="Value to bump the Linked Parameter to when triggered"
            ),
            "UOM": st.column_config.TextColumn("UOM"),
            "Remark": st.column_config.TextColumn("Remark", help="Shown as the abort message, if any"),
            "Linked Parameter": st.column_config.SelectboxColumn(
                "Linked Parameter", options=_param_choices,
                help="Parameter to bump to its max when this row's trigger fires"
            ),
            "Action": st.column_config.SelectboxColumn(
                "Action", options=["", "bump_linked_to_max", "abort_if_exceeds"],
                help="bump_linked_to_max (default when Linked Parameter is set) or abort_if_exceeds"
            ),
        }
        _constraints_panel = ("🚧", "Constraints",
                              "Operating limits + the generalized 'bump' / 'abort' rules. "
                              "Optional -- leave empty if this scenario has none.",
                              "#f97316")

        def _constraint_title(row):
            action = str(row.get("Action") or "").strip()
            base = str(row.get("Parameter") or "?").strip() or "?"
            if action == "bump_linked_to_max" and str(row.get("Linked Parameter") or "").strip():
                return f"{base} → bump {row.get('Linked Parameter')} to max"
            if action == "abort_if_exceeds":
                return f"⛔ {base} — abort if exceeded"
            return base

        if _cards_mode:
            constraints_field_specs = {
                "Parameter": {"type": "select", "options": _param_choices, "help": "The trigger/limited parameter"},
                "user input value": {"type": "number", "label": "user input value",
                                      "help": "Operating limit used in the constraint check"},
                "Max vlaue": {"type": "number", "label": "Max vlaue",
                              "help": "Value to bump the Linked Parameter to when triggered"},
                "Max value": {"type": "number", "label": "Max value",
                              "help": "Value to bump the Linked Parameter to when triggered"},
                "UOM": {"type": "text"},
                "Remark": {"type": "text", "help": "Shown as the abort message, if any"},
                "Linked Parameter": {"type": "select", "options": _param_choices,
                                      "help": "Parameter to bump to its max when this row's trigger fires"},
                "Action": {"type": "select", "options": ["bump_linked_to_max", "abort_if_exceeds"],
                           "help": "bump_linked_to_max (default when Linked Parameter is set) or abort_if_exceeds"},
            }
            _card_list_editor(
                "constraints_df", constraints_field_specs, _constraints_panel,
                title_fn=_constraint_title,
                empty_hint="No constraints yet — add the first limit/rule below.",
            )
        else:
            _simple_editor(
                "constraints_df",
                f"ui_editor_constraints_r{st.session_state['editor_rev']}",
                {k: v for k, v in constraints_cfg.items() if k in st.session_state["constraints_df"].columns},
                panel=_constraints_panel,
            )
        _paste_from_excel("constraints_df", list(st.session_state["constraints_df"].columns),
                          "Paste from Excel")
        _step_nav(8, _VALIDATORS[8](),
                 "Click Save & Continue to confirm this step (Constraints can be left empty).")

    # =================================================================
    # STEP 9 -- User Inputs (structure unchanged from before)
    # =================================================================
    elif cs_step == 9:
        _scoped_tags6 = _cs_scoped_tag_options()
        user_inputs_cfg = {
            "Parameter": st.column_config.SelectboxColumn(
                "Parameter", options=[""] + _scoped_tags6, help="Tag the operator can override"
            ),
            "Value": st.column_config.TextColumn(
                "Value", help="Fixed override value, or 'None' to leave it predicted"
            ),
            "Lower Limit": st.column_config.NumberColumn("Lower Limit"),
            "Upper Limit": st.column_config.NumberColumn("Upper Limit"),
            "Remark": st.column_config.TextColumn("Remark"),
        }
        user_inputs_field_specs = {
            "Parameter": {"type": "select", "options": _scoped_tags6, "help": "Tag the operator can override"},
            "Value": {"type": "text", "help": "Fixed override value, or 'None' to leave it predicted"},
            "Lower Limit": {"type": "number"},
            "Upper Limit": {"type": "number"},
            "Remark": {"type": "text"},
        }
        _user_inputs_panel = ("🎚️", "User Inputs",
                              "Parameters the operator can override, with their allowed range. "
                              "Leave Value as 'None' for parameters that are only ever predicted. "
                              "Optional -- leave empty if none apply.",
                              "#22c55e")
        if _cards_mode:
            _card_list_editor(
                "user_inputs_df", user_inputs_field_specs, _user_inputs_panel,
                title_fn=lambda row: f"{(str(row.get('Parameter')).strip() or '?')} = {row.get('Value') or 'None'}",
                empty_hint="No overridable inputs yet — add the first one below.",
            )
        else:
            _simple_editor(
                "user_inputs_df",
                f"ui_editor_user_inputs_r{st.session_state['editor_rev']}",
                {k: v for k, v in user_inputs_cfg.items() if k in st.session_state["user_inputs_df"].columns},
                panel=_user_inputs_panel,
            )
        _paste_from_excel("user_inputs_df", list(st.session_state["user_inputs_df"].columns),
                          "Paste from Excel")
        _step_nav(9, _VALIDATORS[9](),
                 "Click Save & Continue to confirm this step (User Inputs can be left empty).")

    # =================================================================
    # STEP 10 -- Column Order (structure unchanged from before)
    # =================================================================
    elif cs_step == 10:
        _scoped_tags7 = _cs_scoped_tag_options()
        order_cfg = {
            "Sr.no": st.column_config.NumberColumn("Sr.no"),
            "Preferred columns": st.column_config.SelectboxColumn(
                "Preferred columns", options=[""] + _scoped_tags7
            ),
        }
        order_field_specs = {
            "Sr.no": {"type": "number"},
            "Preferred columns": {"type": "select", "options": _scoped_tags7},
        }
        _order_panel = ("📋", "Column Order",
                        "Controls the column order shown in the Actual vs Estimated results "
                        "table. Optional -- leave empty for the default order.",
                        "#14b8a6")
        if _cards_mode:
            _card_list_editor(
                "display_order_df", order_field_specs, _order_panel,
                title_fn=lambda row: f"#{row.get('Sr.no')}: {row.get('Preferred columns') or '?'}",
                empty_hint="No column order defined yet — add the first entry below.",
            )
        else:
            _simple_editor(
                "display_order_df",
                f"ui_editor_display_order_r{st.session_state['editor_rev']}",
                {k: v for k, v in order_cfg.items() if k in st.session_state["display_order_df"].columns},
                panel=_order_panel,
            )
        _paste_from_excel("display_order_df", ["Sr.no", "Preferred columns"], "Paste from Excel")
        _step_nav(10, _VALIDATORS[10](), "Click Save & Continue to continue (optional sheet).")
        if _VALIDATORS[10]():
            st.success("✅ Configuration complete.")

    # =================================================================
    # STEP 11 -- Train Models (+ Finish / Proceed to What-if Dashboard)
    # =================================================================
    elif cs_step == 11:
        st.caption(f"Trains each predicted parameter; saves .pkl files to `{MODEL_DIR}`.")

        # Training is required only when Raw_data_plus_simulated_data.xlsx
        # is absent -- if present, models were already trained (retraining
        # remains optional).
        _results_ready = os.path.isfile(RAW_SIM_FILE)
        _model_pkls = sorted(glob(os.path.join(MODEL_DIR, "*.pkl")))
        if _results_ready:
            st.session_state["models_trained"] = True

        _model_mapping_filled = not st.session_state["model_details_df"].dropna(how="all").empty
        _train_blockers = []
        if not os.path.isfile(MODEL_SCRIPT):
            _train_blockers.append(f"training script not found next to app (`{APP_DIR}`)")
        if not st.session_state["training_data_ready"]:
            _train_blockers.append("training dataset not saved (Step 5)")
        if not _model_mapping_filled:
            _train_blockers.append("Model Mapping (Step 7) is empty")

        if _results_ready:
            st.success(f"✅ Trained results found ({len(_model_pkls)} .pkl file(s)). Training not required.")
            if _train_blockers:
                st.caption("To retrain: " + " · ".join(_train_blockers))
            _train_btn_label = "🔁 Retrain models (optional)"
        else:
            if _train_blockers:
                st.warning("Before training: " + " · ".join(_train_blockers))
            _train_btn_label = "🧠 Train models"

        t_col1, t_col2 = st.columns([2, 1])
        with t_col2:
            if st.session_state["models_trained"]:
                st.success(f"✅ Ready ({len(_model_pkls)} .pkl)")
            else:
                st.info("⏳ Not trained yet")

        with t_col1:
            if st.button(_train_btn_label, disabled=bool(_train_blockers), **FULL_WIDTH):
                try:
                    os.makedirs(MODEL_DIR, exist_ok=True)
                    os.makedirs(TRAIN_DATA_DIR, exist_ok=True)
                    _env = os.environ.copy()
                    _env["MPLBACKEND"] = "Agg"
                    _env["CONFIG_DIR"] = CONFIG_DIR
                    with st.spinner("Training models — keep this tab open..."):
                        _proc = subprocess.run(
                            [sys.executable, MODEL_SCRIPT],
                            cwd=APP_DIR, env=_env, capture_output=True, text=True,
                        )
                    _model_pkls = sorted(glob(os.path.join(MODEL_DIR, "*.pkl")))
                    _results_ready = os.path.isfile(RAW_SIM_FILE)
                    if _proc.returncode == 0 and (_model_pkls or _results_ready):
                        st.session_state["models_trained"] = True
                        st.success(f"✅ Training finished — {len(_model_pkls)} .pkl file(s) saved.")
                        st.rerun()
                    else:
                        st.session_state["models_trained"] = bool(_model_pkls or _results_ready)
                        st.error(f"🚨 Training failed (exit code {_proc.returncode}).")
                        with st.expander("🔧 Training log"):
                            st.code((_proc.stdout or "")[-8000:] or "<no stdout>")
                            st.code((_proc.stderr or "")[-8000:] or "<no stderr>")
                except Exception as train_err:  # noqa: BLE001
                    st.error(f"🚨 Could not run the training script: {train_err}")
                    with st.expander("🔧 Full technical traceback"):
                        st.code(traceback.format_exc())

        _accuracy_csv = os.path.join(MODEL_DIR, "Model_accuracy_summary.csv")
        if os.path.isfile(_accuracy_csv):
            try:
                _accuracy_df = pd.read_csv(_accuracy_csv)
                with st.expander("📊 Model accuracy (RMSE / MAE / MAPE / R²)", expanded=False):
                    st.dataframe(_accuracy_df, **FULL_WIDTH, height=min(400, 42 + 35 * len(_accuracy_df)))
                    st.download_button(
                        "📥 Download accuracy summary (.csv)",
                        data=_accuracy_df.to_csv(index=False).encode("utf-8"),
                        file_name="Model_accuracy_summary.csv", mime="text/csv",
                    )
            except Exception as _acc_err:  # noqa: BLE001
                st.caption(f"⚠️ Could not read the saved accuracy summary: {_acc_err}")

        if st.session_state["setup_complete"]:
            st.success("✅ Setup confirmed — open the 📊 What-if Dashboard tab.")
            if st.button("🔒 Revise setup", **FULL_WIDTH):
                st.session_state["setup_complete"] = False
                st.rerun()
        else:
            _proceed_ready = st.session_state["models_trained"]
            if st.button("🚀 Finish & open What-if Dashboard",
                         disabled=not _proceed_ready, **FULL_WIDTH):
                st.session_state["setup_complete"] = True
                st.session_state["cs_ack_11"] = True
                st.session_state["_jump_to_dashboard"] = True
                st.toast("Setup confirmed — opening the 📊 What-if Dashboard…", icon="🚀")
                st.rerun()
            if not _proceed_ready:
                st.caption("Train models (or provide pre-trained results) before finishing.")

# =====================================================================
# PART-3  |  TAB 2 : WHAT-IF DASHBOARD
    # -----------------------------------------------------------------
    # 2.4  Config file generation — ALL FIVE sheets, saved straight into
    #      this plant's Data/<plant>/Config_file_updated.xlsx. No upload needed:
    #      whatever is in the editors above (typed by hand, wizard-
    #      generated, or auto-loaded) becomes the plant's live config.
    # -----------------------------------------------------------------
    def _sheet_or_placeholder(sheet_df: pd.DataFrame) -> pd.DataFrame:
        """pandas 3.x + openpyxl cannot write a 0-row sheet; pad one blank row."""
        if sheet_df is None or sheet_df.empty:
            cols = (list(sheet_df.columns)
                    if sheet_df is not None and len(sheet_df.columns) else ["_"])
            return pd.DataFrame([{c: None for c in cols}])
        return sheet_df

    _gen_map = st.session_state["generated_pi_mapping"]
    pi_sheet_out = _gen_map if not _gen_map.empty else st.session_state["pi_names_df"]
    pi_sheet_label = ("wizard-generated line-up" if not _gen_map.empty
                      else "full dictionary (run the wizard to filter it)")

    def _build_config_workbook() -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            _sheet_or_placeholder(pi_sheet_out).to_excel(writer, sheet_name=PI_SHEET, index=False)
            _sheet_or_placeholder(st.session_state["model_details_df"]).to_excel(writer, sheet_name="Model details", index=False)
            _sheet_or_placeholder(st.session_state["constraints_df"]).to_excel(writer, sheet_name="Constraints", index=False)
            _sheet_or_placeholder(st.session_state["user_inputs_df"]).to_excel(writer, sheet_name="user inputs", index=False)
            _sheet_or_placeholder(st.session_state["display_order_df"]).to_excel(writer, sheet_name="display_column_order", index=False)
            _sheet_or_placeholder(st.session_state["section_order_df"]).to_excel(writer, sheet_name="Section Order", index=False)
            _sheet_or_placeholder(st.session_state["mvdvcv_df"]).to_excel(writer, sheet_name="MV_DV_CV_taglist", index=False)
            pd.DataFrame({"Target Section": [st.session_state.get("target_section") or ""]}).to_excel(
                writer, sheet_name="Target Section", index=False)
        return buf.getvalue()

    # -----------------------------------------------------------------
    # SYNC TO SCRATCH: every edit in any of the 5 tabs above already
    # lands in st.session_state. Training (Step C) and What-if runs
    # (📊 tab) both need those sheets in an actual Config_file_updated.xlsx
    # on disk -- but that file is written ONLY to the throwaway,
    # per-session CONFIG_DIR scratch folder (see CONFIG_DIR/CONFIG_WORKBOOK
    # above), never into this plant's persistent Data/<plant>/ folder.
    # There is no "Save configuration" step for the user to click --
    # this keeps the scratch copy in sync automatically and silently.
    # -----------------------------------------------------------------
    def _config_content_signature() -> str:
        import hashlib
        h = hashlib.md5()
        for _df in (pi_sheet_out, st.session_state["model_details_df"],
                    st.session_state["constraints_df"], st.session_state["user_inputs_df"],
                    st.session_state["display_order_df"], st.session_state["section_order_df"],
                    st.session_state["mvdvcv_df"]):
            h.update(pd.util.hash_pandas_object(_df, index=True).values.tobytes())
            h.update(str(list(_df.columns)).encode())
        h.update(str(st.session_state.get("target_section") or "").encode())
        return h.hexdigest()

    _current_sig = _config_content_signature()
    if st.session_state.get("_autosave_sig") != _current_sig:
        try:
            with open(CONFIG_WORKBOOK, "wb") as _f:
                _f.write(_build_config_workbook())
            st.session_state["_autosave_sig"] = _current_sig
        except Exception as _autosave_err:  # noqa: BLE001
            st.warning(f"⚠️ Could not sync the configuration for training/what-if use: {_autosave_err}")

    st.download_button(
        "📥 Download current configuration",
        data=_build_config_workbook(),
        file_name="Config_file_updated.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # -----------------------------------------------------------------
# =====================================================================
with tab2:

    # -----------------------------------------------------------------
    # GATE 0: this plant has no historian/model data yet (e.g. it was
    # just created and hasn't been trained). Nothing below this point
    # can run without `df`, so stop here with a clear pointer back to
    # the Configuration Hub rather than showing stale or another
    # plant's data.
    # -----------------------------------------------------------------
    if df.empty:
        st.title(f"{PLANT_NAME} What-if Dashboard")
        st.info(
            f"📭 **No historian/model data yet for `{PLANT_NAME}`.**\n\n"
            "This plant hasn't been trained yet. Go to the **⚙️ What-if case setup** "
            "tab, upload its training dataset, fill in the PI/Model Mapping, "
            "Constraints and User Inputs, then run Step C (train models)."
        )
        if HISTORIAN_ERROR is not None:
            with st.expander("🔧 Technical detail"):
                st.code(str(HISTORIAN_ERROR))
        st.stop()

    # -----------------------------------------------------------------
    # GATE 1: simulation overrides appear only after the user clicks
    # "🚀 Proceed to What-if Dashboard" in the What-if case setup tab.
    # st.stop() is safe here because this tab is the last block rendered.
    # -----------------------------------------------------------------
    if not st.session_state.get("setup_complete", False):
        st.info(
            "🔒 **Simulation overrides are locked.**\n\n"
            "Complete the **⚙️ What-if case setup** tab and click "
            "**🚀 Proceed to What-if Dashboard** there to unlock this page."
        )
        st.stop()

    user_inputs_df = st.session_state.get("user_inputs_df", pd.DataFrame())
    display_order_df = st.session_state.get("display_order_df", pd.DataFrame())
    generated_tags = st.session_state.get("generated_tags", [])

    # -----------------------------------------------------------------
    # 3.05  TARGET SECTION -- section-based process flow scoping.
    #       Selecting a target section here automatically includes every
    #       upstream section plus the target itself, and excludes every
    #       downstream section, both for which tags can be edited below
    #       and for which predicted-parameter models actually get run
    #       (enforced again, authoritatively, inside whatif_analysis()).
    # -----------------------------------------------------------------
    _section_order_list = get_section_order()

    _pi_df = st.session_state.get("pi_names_df", pd.DataFrame())
    _pi_section_map = {}
    if not _pi_df.empty and {"Generalized Description", "Section"}.issubset(_pi_df.columns):
        _pi_section_map = dict(zip(
            _pi_df["Generalized Description"].astype(str).str.strip(),
            _pi_df["Section"].astype(str).str.strip(),
        ))

    _model_df = st.session_state.get("model_details_df", pd.DataFrame())
    _model_section_map = {}
    if not _model_df.empty and {"Predicted parameter", "Section"}.issubset(_model_df.columns):
        _model_section_map = dict(zip(
            _model_df["Predicted parameter"].astype(str).str.strip(),
            _model_df["Section"].astype(str).str.strip(),
        ))

    # Model Mapping wins on a name clash (a predicted parameter's own
    # declared section is more authoritative than a PI-tag guess).
    _param_section_map = {**_pi_section_map, **_model_section_map}

    target_section = None
    allowed_secs = list(_section_order_list)  # unrestricted until a target is chosen
    if _section_order_list:
        st.markdown("#### 🎯 Target Section")
        if st.session_state.get("target_section") not in _section_order_list:
            st.session_state["target_section"] = _section_order_list[-1]
        target_section = st.selectbox(
            "Run the What-if analysis up to which section?",
            options=_section_order_list,
            help="Follows the plant's Process Flow Order (⚙️ What-if case setup → "
                 "🔀 Process Flow Order). Only this section and everything upstream "
                 "of it are available below for editing, and only their models are "
                 "predicted -- downstream sections are excluded entirely. Defaults "
                 "to whatever was chosen in Step 2 of the case setup wizard.",
            key="target_section",
        )
        allowed_secs = allowed_sections_upto(_section_order_list, target_section)
        _excluded_secs = [s for s in _section_order_list if s not in allowed_secs]
        st.caption(
            "✅ Included (upstream → target): " + " → ".join(f"`{s}`" for s in allowed_secs) +
            (f"  \n🚫 Excluded (downstream): " + ", ".join(f"`{s}`" for s in _excluded_secs)
             if _excluded_secs else "")
        )

    _allowed_secs_lower = {s.strip().lower() for s in allowed_secs}

    def _in_target_scope(tag) -> bool:
        """True if `tag` belongs to the target section or an upstream one.
        Looks up an explicit Section first (PI Tag Mapping / Model Mapping);
        if the tag has none there (e.g. a raw input tag like PRC_turbine_RPM
        that's only ever used as an *input* to another model, never listed
        as its own 'Predicted parameter' or given its own PI Tag Mapping
        row), falls back to a name-based guess (infer_section) so it's still
        correctly scoped instead of always being shown. Only a tag that
        matches NO section at all, by either method, is kept unconditionally."""
        if not _allowed_secs_lower:
            return True
        key = str(tag).strip()
        sec = _param_section_map.get(key, "").strip().lower()
        if not sec:
            sec = infer_section(key).strip().lower()
        return (not sec) or (sec in _allowed_secs_lower)

    # -----------------------------------------------------------------
    # 3.1  Parameter source resolution
    #      Priority: wizard-generated tags -> auto-loaded config sheet
    #                -> full historian dropdown fallback.
    #      Limits: config 'user inputs' sheet when available for a tag,
    #              otherwise historical min/max.
    #      Every source below is additionally scoped to allowed_secs --
    #      a tag/parameter belonging to a downstream section never
    #      appears as editable, per the section-based What-if requirement.
    # -----------------------------------------------------------------
    config_limits: dict = {}
    if {"Parameter", "Lower Limit", "Upper Limit"}.issubset(user_inputs_df.columns):
        _dl = user_inputs_df.copy()
        _dl["Parameter"] = _dl["Parameter"].astype(str).str.strip()
        _dl = _dl[_dl["Parameter"].str.lower() != "nan"]
        config_limits = (_dl.set_index("Parameter")
                         [["Lower Limit", "Upper Limit"]].to_dict("index"))
    _hidden_downstream = [p for p in config_limits if not _in_target_scope(p)]
    config_limits = {p: v for p, v in config_limits.items() if _in_target_scope(p)}

    def _limits_for(tags: list) -> dict:
        """Config-sheet limits first, historical min/max as fallback."""
        out = {}
        for tag in tags:
            cfg = config_limits.get(tag)
            lo = pd.to_numeric(pd.Series([cfg.get("Lower Limit")]), errors="coerce").iloc[0] if cfg else None
            hi = pd.to_numeric(pd.Series([cfg.get("Upper Limit")]), errors="coerce").iloc[0] if cfg else None
            if pd.notna(lo) and pd.notna(hi):
                out[tag] = {"Lower Limit": float(lo), "Upper Limit": float(hi)}
            elif tag in df.columns and pd.api.types.is_numeric_dtype(df[tag]):
                out[tag] = {"Lower Limit": float(df[tag].min()),
                            "Upper Limit": float(df[tag].max())}
            else:
                out[tag] = {"Lower Limit": 0.0, "Upper Limit": 1e6}
        return out

    limits_dict: dict = {}
    user_defined_input_tags: list = []

    _generated_tags_scoped = sorted(t for t in generated_tags if _in_target_scope(t))
    _tag_options_scoped = [t for t in tag_options if _in_target_scope(t)]

    if generated_tags:
        # --- Source A: GENERATED TAG SELECTION (Plant Configuration Wizard) ---
        st.markdown("#### ⚡ Tag Source: Wizard Mapping")
        user_defined_input_tags = st.multiselect(
            "Generated tags (from plant line-up)",
            options=_generated_tags_scoped,
            default=[],
            help="Tags produced by the Plant Configuration Wizard that also exist "
                 "in the historian, scoped to the selected Target Section. Pick the "
                 "ones you want to override.",
        )
        limits_dict = _limits_for(user_defined_input_tags)
        if not user_defined_input_tags:
            st.info("💡 A wizard-generated mapping is active. Pick tags from "
                    "**'Generated tags'** above — the simulation override "
                    "inputs will appear in the **left sidebar**.")

    elif config_limits:
        # --- Source B: auto-loaded config 'user inputs' sheet ---
        st.markdown("#### 📋 Tag Source: Config Sheet")
        user_defined_input_tags = list(config_limits.keys())
        limits_dict = _limits_for(user_defined_input_tags)
        if _hidden_downstream:
            st.caption(f"🚫 {len(_hidden_downstream)} downstream parameter(s) hidden "
                       f"for the selected Target Section.")

    else:
        # --- Source C: full historian dropdown fallback ---
        st.markdown("#### 🏷️ Dynamic Tag Selection")
        user_defined_input_tags = st.multiselect(
            "User defined inputs",
            options=_tag_options_scoped,
            default=[],
            help="No configuration found. Select process tags from the historian "
                 "list -- scoped to the selected Target Section -- to simulate "
                 "scenarios manually.",
        )
        limits_dict = _limits_for(user_defined_input_tags)
        if not user_defined_input_tags:
            st.info("💡 **Quick Start:** answer the wizard questions in the "
                    "⚙️ What-if case setup tab, or choose metrics from "
                    "**'User defined inputs'** above — the simulation override "
                    "inputs will appear in the **left sidebar**.")

    # -----------------------------------------------------------------
    # 3.2  Timestamp selection (date -> snapshot)
    # -----------------------------------------------------------------
    sel_col1, sel_col2 = st.columns(2)
    with sel_col1:
        available_dates = sorted(pd.Series(df.index.date).unique())
        selected_date = st.selectbox(
            "Historical Target Date", available_dates,
            index=len(available_dates) - 1,  # default to most recent day
        )
    with sel_col2:
        day_stamps = sorted(df.index[df.index.date == selected_date])
        timestamp_options = [ts.strftime("%Y-%m-%d %H:%M:%S") for ts in day_stamps]
        selected_time_str = st.selectbox(
            "Process Snapshot Timestamp", timestamp_options,
            index=len(timestamp_options) - 1,
            key="timestamp_selector",
        )

    if not timestamp_options:
        st.warning("No historian snapshots available for the selected date.")
        st.stop()

    selected_time = pd.Timestamp(selected_time_str)

    # -----------------------------------------------------------------
    # 3.3  Baseline values at the selected snapshot
    # -----------------------------------------------------------------
    with st.expander("🔎 Baseline Process Values at Selected Timestamp", expanded=False):
        try:
            active_tags = ([t for t in user_defined_input_tags if t in df.columns]
                           or df.columns.tolist())
            baseline = df.loc[[selected_time], active_tags].T
            baseline.columns = ["Current Value"]
            baseline = baseline.apply(pd.to_numeric, errors="coerce").round(2)
            st.dataframe(baseline, **FULL_WIDTH, height=280)
        except KeyError:
            st.error("⚠️ Selected snapshot not found in the historian index.")

    # -----------------------------------------------------------------
    # 3.4  User override inputs (validated against limits)
    #      Rendered in the LEFT SIDEBAR. Tag selection stays in the
    #      main tab so it is clearly visible after proceeding.
    # -----------------------------------------------------------------
    user_inputs = []
    if user_defined_input_tags:
        st.sidebar.markdown("### 🔧 Simulation Overrides")
        st.sidebar.caption("Enter a target value to override — leave blank "
                           "to keep the actual (baseline) value.")

    for param in user_defined_input_tags:
        limits = limits_dict.get(param) or {}
        try:
            lower = float(limits.get("Lower Limit", 0.0))
        except (TypeError, ValueError):
            lower = 0.0
        try:
            upper = float(limits.get("Upper Limit", 1e6))
        except (TypeError, ValueError):
            upper = 1e6

        st.sidebar.markdown(f"**{param}**")
        st.sidebar.caption(f"Boundary range: {lower:,.2f} → {upper:,.2f}")

        raw = st.sidebar.text_input(
            "Override target value", value="", key=f"ovr_{param}",
            placeholder="blank = keep actual", label_visibility="collapsed",
        )

        val_float = np.nan
        if raw.strip():
            try:
                val_float = float(raw)
                if not (lower <= val_float <= upper):
                    st.sidebar.error(f"Value must be between {lower:,.2f} and {upper:,.2f}")
                    val_float = np.nan
            except ValueError:
                st.sidebar.error("Numeric input required")
                val_float = np.nan

        user_inputs.append({"Parameter": param, "Value": val_float})

    user_input_df = pd.DataFrame(user_inputs, columns=["Parameter", "Value"])
    n_overrides = int(user_input_df["Value"].notna().sum()) if not user_input_df.empty else 0

    # -----------------------------------------------------------------
    # 3.5  whatif_analysis execution
    # -----------------------------------------------------------------
    run_label = (f"🚀 Compute What-If Scenario  ({n_overrides} override"
                 f"{'s' if n_overrides != 1 else ''} active)")
    if st.button(run_label):
        if whatif_analysis is None:
            st.error("The what-if engine is unavailable (whatif_runner import failed).")
        else:
            with st.spinner("Processing operational scenario model rules..."):
                try:
                    st.session_state["result"] = whatif_analysis(
                        df, selected_time, user_input_df,
                        plant_name=PLANT_NAME, plant_dir=CONFIG_DIR, results_dir=RESULTS_DIR,
                        target_section=target_section, section_order=_section_order_list,
                    )
                    st.session_state["selected_time"] = selected_time
                except Exception as run_err:  # noqa: BLE001
                    st.session_state.pop("result", None)
                    st.error(f"🚨 What-if analysis failed: {run_err}")
                    with st.expander("🔧 Full technical traceback"):
                        st.code(traceback.format_exc())

    # =====================================================================
    # PART-4  |  RESULTS : KPI CARDS, COMPARISON TABLE, VALIDATION, EXPORT
    # =====================================================================
    if "result" in st.session_state and st.session_state["result"] is not None:
        result = st.session_state["result"]
        selected_time_download = st.session_state.get("selected_time", selected_time)

        # Accept either a Styler or a plain DataFrame from the engine
        if _PdStyler is not None and isinstance(result, _PdStyler):
            result_df = result.data.copy()
        elif isinstance(result, pd.DataFrame):
            result_df = result.copy()
        else:
            st.error("The what-if engine returned an unsupported result type "
                     f"({type(result).__name__}). Expected DataFrame or Styler.")
            st.stop()

        result_df.drop(columns=["Timestamp"], errors="ignore", inplace=True)

        if {"actual", "estimated"}.issubset(result_df.index):
            result_df.loc["Change"] = (
                pd.to_numeric(result_df.loc["estimated"], errors="coerce")
                - pd.to_numeric(result_df.loc["actual"], errors="coerce")
            )
        else:
            st.warning("Result is missing 'actual'/'estimated' rows — "
                       "the Change row and KPI deltas cannot be computed.")

        transpose_df = result_df.T
        transpose_df = transpose_df[~transpose_df.index.duplicated(keep="first")]

        # Reporting order (falls back gracefully if no ordering configured)
        preferred_order = (
            display_order_df["Preferred columns"].dropna().tolist()
            if ("Preferred columns" in display_order_df.columns
                and not display_order_df.empty) else []
        )
        preferred_existing = [c for c in preferred_order if c in transpose_df.index]
        remaining = [c for c in transpose_df.index if c not in preferred_existing]
        transpose_df = transpose_df.loc[preferred_existing + remaining]

        # Restrict every downstream result (KPI cards, comparison table,
        # CSV export -- all derived from transpose_df below) to the active
        # process scope: the selected Target Section plus everything
        # upstream of it. A parameter with no known Section is kept, so
        # unclassified/legacy tags never silently disappear.
        _n_before_scope = len(transpose_df)
        transpose_df = transpose_df[transpose_df.index.map(_in_target_scope)]
        _n_hidden_downstream = _n_before_scope - len(transpose_df)
        if _n_hidden_downstream > 0:
            st.caption(f"🚫 {_n_hidden_downstream} downstream parameter(s) outside the "
                       f"active scope are hidden from these results.")

        # -----------------------------------------------------------------
        # 4.1  KPI cards
        # -----------------------------------------------------------------
        # KPI cards = the union of, in display order:
        #   1. every "Predicted parameter" this plant's config defines
        #      (Model details sheet),
        #   2. every "Parameter" the plant declares an operating limit
        #      for (Constraints sheet), and
        #   3. calculated plant-level variables the plant's formulas
        #      plug-in exposes via KPI_PARAMETERS (e.g. Total_Power_(KW),
        #      Total_required_steam_flow_(TPH)) -- these are derived by
        #      hooks, so they appear in neither config sheet.
        # Nothing here is a fixed YANPET_OLF1 tag list: a different plant
        # gets its own KPI cards automatically from its own config sheets
        # and (optionally) its own plug-in's KPI_PARAMETERS.
        _model_details_for_kpis = st.session_state.get("model_details_df", pd.DataFrame())
        if "Predicted parameter" in _model_details_for_kpis.columns:
            KPI_TAGS = (
                _model_details_for_kpis["Predicted parameter"]
                .dropna().astype(str).str.strip().tolist()
            )
        else:
            KPI_TAGS = []

        # 2. Constraint parameters -- anything the plant bothers to put an
        # operating limit on is, by definition, worth watching as a KPI.
        _constraints_for_kpis = st.session_state.get("constraints_df", pd.DataFrame())
        if "Parameter" in _constraints_for_kpis.columns:
            KPI_TAGS += (
                _constraints_for_kpis["Parameter"]
                .dropna().astype(str).str.strip().tolist()
            )

        # 3. Calculated variables declared by the plant's formulas plug-in,
        # plus any plant-declared KPI tile substitutions (KPI_REPLACEMENTS:
        # raw config tag -> the derived/calculated tag worth showing, e.g.
        # PRC_turbine_steam_flow -> PRC_turbine_Calculated_Steam_flow_TPH).
        _kpi_calc, _kpi_repl = [], {}
        if load_plant_formulas is not None:
            try:
                _plugin_for_kpis = load_plant_formulas(PLANT_NAME)
                _kpi_calc = [str(p).strip() for p in
                             (getattr(_plugin_for_kpis, "KPI_PARAMETERS", []) or [])]
                _kpi_repl = {str(k).strip(): str(v).strip() for k, v in
                             (getattr(_plugin_for_kpis, "KPI_REPLACEMENTS", {}) or {}).items()}
            except Exception:  # noqa: BLE001
                _kpi_calc, _kpi_repl = [], {}
        if not _kpi_calc:
            # Fallback for plants whose plug-in predates KPI_PARAMETERS:
            # show the well-known hook-derived totals if the results
            # actually contain them.
            _kpi_calc = [c for c in ("Total_Power_(KW)", "Total_required_steam_flow_(TPH)")
                         if c in transpose_df.index]
        KPI_TAGS += _kpi_calc

        # Apply the plug-in's tile substitutions (only swap when the
        # replacement actually exists in the results, so a plant whose
        # hooks didn't run keeps the raw tag's tile instead of losing it).
        KPI_TAGS = [
            _kpi_repl[t] if t in _kpi_repl and _kpi_repl[t] in transpose_df.index else t
            for t in KPI_TAGS
        ]

        # De-duplicate preserving order (a parameter that is both
        # predicted AND constrained gets exactly one tile).
        KPI_TAGS = [t for t in dict.fromkeys(KPI_TAGS) if t]
        active_kpis = [t for t in KPI_TAGS if t in transpose_df.index]

        def render_kpi_card(kpi_tag: str):
            """Renders one executive KPI tile with a business-rule colour code."""
            try:
                act = float(transpose_df.at[kpi_tag, "actual"])
                est = float(transpose_df.at[kpi_tag, "estimated"])
                chg = float(transpose_df.at[kpi_tag, "Change"])
            except (KeyError, TypeError, ValueError):
                return
            if not (np.isfinite(act) and np.isfinite(est)):
                return

            if est < act:
                border, bg, txt = "#ef4444", "rgba(239,68,68,0.15)", "#f87171"
            elif est > act:
                border, bg, txt = "#10b981", "rgba(16,185,129,0.15)", "#34d399"
            else:
                border, bg, txt = "rgba(255,255,255,0.1)", "rgba(148,163,184,0.1)", "#94a3b8"

            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, #1e293b, #0f172a);
                border-left: 4px solid {border};
                border-top: 1px solid rgba(255,255,255,0.05);
                border-right: 1px solid rgba(255,255,255,0.05);
                border-bottom: 1px solid rgba(255,255,255,0.05);
                border-radius: 8px; padding: 16px; margin-bottom: 14px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                <div style="color:#94a3b8; font-size:11px; font-weight:600;
                            text-transform:uppercase; letter-spacing:.03em;
                            margin-bottom:6px; white-space:nowrap; overflow:hidden;
                            text-overflow:ellipsis;" title="{kpi_tag}">
                    🏷️ {kpi_tag.replace('_', ' ')}
                </div>
                <div class="kpi-value" style="color:#f8fafc; font-size:26px;
                            font-weight:800; line-height:1.2; margin-bottom:8px;">
                    {fmt_num(est)}
                </div>
                <div style="display:inline-block; padding:3px 8px; border-radius:4px;
                            font-size:15px; font-weight:700;
                            background-color:{bg}; color:{txt};">
                    {fmt_num(chg, force_sign=True)} vs Act ({fmt_num(act)})
                </div>
            </div>
            """, unsafe_allow_html=True)

        if active_kpis:
            st.markdown("#### 📊 Key Performance Indicators")
            for chunk in [active_kpis[i:i + 4] for i in range(0, len(active_kpis), 4)]:
                for col, kpi in zip(st.columns(len(chunk)), chunk):
                    with col:
                        render_kpi_card(kpi)

        # -----------------------------------------------------------------
        # 4.2  Actual vs Estimated table with Change highlighting
        # -----------------------------------------------------------------
        st.markdown('<br><h3>📈 Actual vs Estimated Scenario Output</h3>',
                    unsafe_allow_html=True)

        display_df = transpose_df.map(
            lambda x: f"{x:.2f}".rstrip("0").rstrip(".")
            if isinstance(x, (int, float, np.number)) and pd.notna(x) else x
        )

        def highlight_change_only(row):
            styles = []
            for col in row.index:
                if str(col).lower() == "change":
                    try:
                        v = float(row[col])
                    except (TypeError, ValueError):
                        styles.append("")
                        continue
                    if v < 0:
                        styles.append("color:#ef4444; font-weight:600; "
                                      "background-color:rgba(239,68,68,0.08);")
                    elif v > 0:
                        styles.append("color:#10b981; font-weight:600; "
                                      "background-color:rgba(16,185,129,0.08);")
                    else:
                        styles.append("color:#94a3b8; font-weight:500;")
                else:
                    styles.append("")
            return styles

        st.dataframe(display_df.style.apply(highlight_change_only, axis=1),
                     **FULL_WIDTH, height=480)

        # -----------------------------------------------------------------
        # 4.3  Scenario CSV export
        # -----------------------------------------------------------------
        download_df = display_df.copy().reset_index()
        download_df.rename(columns={"index": "Parameter"}, inplace=True)
        download_df.insert(0, "Selected Timestamp", str(selected_time_download))

        st.download_button(
            "📥 Export Baseline vs Simulation Matrix (.CSV)",
            data=download_df.to_csv(index=False).encode("utf-8"),
            file_name="WhatIf_Result.csv",
            mime="text/csv",
            **FULL_WIDTH,
        )

        # -----------------------------------------------------------------
        # 4.4  Historical validation filters + unified export
        # -----------------------------------------------------------------
        st.sidebar.markdown("### 🔍 Validation Filters")

        # -----------------------------------------------------------------
        # URL persistence for validation-filter settings.
        # st.session_state dies on a browser refresh, so the chosen filter
        # parameters and their min/max (or category) settings are mirrored
        # into a single JSON query parameter ('vf') in the URL. Refreshing
        # the page -- or bookmarking / sharing the URL -- restores the
        # exact same validation setup. Works on both the modern
        # st.query_params API and the older experimental one.
        # -----------------------------------------------------------------
        def _read_vf_state() -> dict:
            raw = None
            try:
                raw = st.query_params.get("vf")
            except Exception:  # noqa: BLE001  (older Streamlit)
                try:
                    vals = st.experimental_get_query_params().get("vf")
                    raw = vals[0] if vals else None
                except Exception:  # noqa: BLE001
                    raw = None
            if not raw:
                return {}
            try:
                state = json.loads(raw)
                return state if isinstance(state, dict) else {}
            except (ValueError, TypeError):
                return {}

        def _write_vf_state(state: dict):
            payload = json.dumps(state, separators=(",", ":"))
            try:
                if st.query_params.get("vf") != payload:
                    st.query_params["vf"] = payload
            except Exception:  # noqa: BLE001  (older Streamlit)
                try:
                    qp = st.experimental_get_query_params()
                    if (qp.get("vf") or [None])[0] != payload:
                        qp["vf"] = payload
                        st.experimental_set_query_params(**qp)
                except Exception:  # noqa: BLE001
                    pass

        _vf_saved = _read_vf_state()
        _saved_tags = [str(t) for t in _vf_saved.get("tags", []) if str(t) in df.columns]
        _saved_ranges = _vf_saved.get("ranges", {}) if isinstance(_vf_saved.get("ranges"), dict) else {}
        _saved_cats = _vf_saved.get("cats", {}) if isinstance(_vf_saved.get("cats"), dict) else {}

        # Suggested defaults = parameters this plant's own config actually
        # defines limits for (Constraints sheet), falling back to its
        # Predicted parameters if Constraints is empty -- not a fixed
        # YANPET_OLF1 tag list, so a different plant's own filter
        # parameters (PRC or otherwise) show up automatically.
        _constraints_for_val = st.session_state.get("constraints_df", pd.DataFrame())
        if "Parameter" in _constraints_for_val.columns and not _constraints_for_val.empty:
            VALIDATION_TAGS = (
                _constraints_for_val["Parameter"].dropna().astype(str).str.strip().tolist()
            )
        else:
            VALIDATION_TAGS = list(KPI_TAGS)
        VALIDATION_TAGS = [t for t in dict.fromkeys(VALIDATION_TAGS) if t]
        _default_val_tags = [c for c in VALIDATION_TAGS if c in df.columns]

        # The user picks WHICH parameters to filter the historical data on:
        # any historian column is selectable (config-suggested tags listed
        # first). A URL-restored selection wins over the config defaults.
        _tag_choices = _default_val_tags + [c for c in df.columns if c not in _default_val_tags]
        available_val_tags = st.sidebar.multiselect(
            "Parameters for data filtering",
            options=_tag_choices,
            default=(_saved_tags or _default_val_tags),
            key="validation_filter_tags",
            help="Historical snapshots are filtered on these parameters. "
                 "Your selection and the ranges below are saved in the URL, "
                 "so they survive a page refresh and can be bookmarked/shared.",
        )

        if not available_val_tags:
            st.info("Select at least one parameter in the sidebar's Validation "
                    "Filters to build the correlated historical validation set.")
        else:
            filter_values = {}
            for tag in available_val_tags:
                if pd.api.types.is_numeric_dtype(df[tag]):
                    g_min, g_max = float(df[tag].min()), float(df[tag].max())
                    try:  # URL-restored range wins over the data's full span
                        s_lo, s_hi = _saved_ranges.get(tag, (g_min, g_max))
                        init_lo, init_hi = float(s_lo), float(s_hi)
                    except (TypeError, ValueError):
                        init_lo, init_hi = g_min, g_max
                    st.sidebar.markdown(f"**Filter {tag}**")
                    f1, f2 = st.sidebar.columns(2)
                    with f1:
                        min_val = st.number_input("Min", value=init_lo, key=f"{tag}_min")
                    with f2:
                        max_val = st.number_input("Max", value=init_hi, key=f"{tag}_max")
                    filter_values[tag] = (min_val, max_val)
                else:
                    uniq = df[tag].dropna().unique().tolist()
                    _cat_default = [c for c in _saved_cats.get(tag, uniq) if c in uniq] or uniq
                    filter_values[tag] = st.sidebar.multiselect(
                        f"Select {tag}", options=uniq, default=_cat_default,
                        key=f"{tag}_cats")

            # Mirror the current settings into the URL so a refresh
            # restores them exactly.
            _write_vf_state({
                "tags": list(available_val_tags),
                "ranges": {t: [float(v[0]), float(v[1])]
                           for t, v in filter_values.items()
                           if isinstance(v, tuple)},
                "cats": {t: list(v) for t, v in filter_values.items()
                         if not isinstance(v, tuple)},
            })

            df_filtered = df.copy()
            for tag, criteria in filter_values.items():
                if pd.api.types.is_numeric_dtype(df_filtered[tag]):
                    lo, hi = criteria
                    df_filtered = df_filtered[
                        (df_filtered[tag] >= lo) & (df_filtered[tag] <= hi)]
                else:
                    df_filtered = df_filtered[df_filtered[tag].isin(criteria)]

            st.markdown('<br><h3>🔍 Correlated Historical Validation Sets</h3>',
                        unsafe_allow_html=True)

            if df_filtered.empty:
                st.warning("No historical snapshots match the current validation "
                           "filters — widen the ranges in the sidebar.")
            else:
                col_pref = [c for c in preferred_order if c in df_filtered.columns]
                col_rest = [c for c in df_filtered.columns if c not in col_pref]
                df_filtered = df_filtered[col_pref + col_rest]

                df_display = df_filtered.map(
                    lambda x: f"{x:.2f}".rstrip("0").rstrip(".")
                    if isinstance(x, (int, float, np.number)) and pd.notna(x) else x
                ).T
                df_display.index.name = "Parameter"

                st.caption(f"{df_filtered.shape[0]} matching historical snapshot(s)")
                st.dataframe(df_display, **FULL_WIDTH)

                try:
                    combined_df = pd.merge(
                        download_df, df_display.reset_index(),
                        on="Parameter", how="inner")
                    st.download_button(
                        "📥 Export Unified Comparison & Historical Validation Data (.CSV)",
                        data=combined_df.to_csv(index=False).encode("utf-8"),
                        file_name="filtered_validation_data.csv",
                        mime="text/csv",
                        **FULL_WIDTH,
                    )
                except Exception as merge_err:  # noqa: BLE001
                    st.error(f"Could not build the unified export: {merge_err}")


# =====================================================================
# AUTO-SWITCH TO THE WHAT-IF DASHBOARD TAB
# After "🚀 Proceed to What-if Dashboard" is clicked, st.rerun() re-runs
# the script and st.tabs() re-opens on the setup tab (there is no
# server-side API to pick the active tab). This injects a one-shot,
# client-side click on the 3rd button of the FIRST tab-list — i.e. the
# top-level "Overview / What-if case setup / What-if Dashboard" bar,
# NOT the nested config-editor tabs inside the setup tab — so the
# dashboard opens automatically. The flag is cleared right away so
# subsequent reruns never pull the user off whatever tab they're on.
# =====================================================================
if st.session_state.get("_jump_to_dashboard"):
    st.session_state["_jump_to_dashboard"] = False
    components.html(
        """
        <script>
        (function () {
            function jump(attempt) {
                const doc = window.parent.document;
                const lists = doc.querySelectorAll('div[data-baseweb="tab-list"]');
                if (lists.length) {
                    const btns = lists[0].querySelectorAll('button[data-baseweb="tab"]');
                    if (btns.length >= 3) { btns[2].click(); return; }
                }
                if (attempt < 25) { setTimeout(function () { jump(attempt + 1); }, 100); }
            }
            jump(0);
        })();
        </script>
        """,
        height=0,
    )