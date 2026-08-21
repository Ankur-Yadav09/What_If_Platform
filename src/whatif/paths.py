"""
src/whatif/paths.py
====================
Resolves absolute filesystem paths for the What-If Analysis module's
file-based config/model/historian storage (Data/, Results/), anchored to
the repo root rather than the process's current working directory.

This fixes the one fragile bit of the original Scripts/whatif_runner.py:
it used paths relative to os.getcwd() at call time (e.g. "..\\Data"),
which only worked because Streamlit was always launched from Scripts/.
A FastAPI process may be launched from anywhere, so every path here is
computed from this file's own location instead.

Case isolation (added alongside src/data/database.py's whatif_cases table)
mirrors the legacy Streamlit reference app's multi-plant folder convention
(Scripts/Whatif_streamlit_dashboard_updated.py's _resolve_plant_dir /
DATA_BASE_DIR/<PLANT_NAME>) — applied here to isolated scenario "cases" for
the same single plant rather than different plants: Data/<case_id>/... and
Results/<case_id>/... when a nested case folder exists, falling back to the
original flat Data/Results layout otherwise. DEFAULT_CASE_ID resolves to
that original flat layout unchanged, so every existing on-disk file keeps
working with zero migration.
"""
from __future__ import annotations

import os

from config import settings
from src.data.database import DEFAULT_CASE_ID

# src/whatif/paths.py -> src/whatif -> src -> <repo root>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _abs(relative: str) -> str:
    return os.path.normpath(os.path.join(_REPO_ROOT, relative))


def _case_dir(base_dir: str, case_id: str) -> str:
    """`base_dir` scoped to `case_id`, mirroring the Streamlit reference's
    _resolve_plant_dir: the default case always uses the flat, un-nested
    base_dir; any other case_id uses base_dir/<case_id> (created on demand
    by whatif_case_service.create_case(), so it's expected to exist by the
    time this is called for a real case)."""
    if case_id == DEFAULT_CASE_ID:
        return base_dir
    return os.path.join(base_dir, case_id)


def data_dir(case_id: str = DEFAULT_CASE_ID) -> str:
    return _case_dir(_abs(settings.WHATIF_DATA_DIR), case_id)


def results_dir(case_id: str = DEFAULT_CASE_ID) -> str:
    return _case_dir(_abs(settings.WHATIF_RESULTS_DIR), case_id)


def model_dir(case_id: str = DEFAULT_CASE_ID) -> str:
    if case_id == DEFAULT_CASE_ID:
        return _abs(settings.WHATIF_MODEL_DIR)
    return os.path.join(results_dir(case_id), "Model")


def config_file(case_id: str = DEFAULT_CASE_ID) -> str:
    if case_id == DEFAULT_CASE_ID:
        return _abs(settings.WHATIF_CONFIG_FILE)
    return os.path.join(data_dir(case_id), os.path.basename(settings.WHATIF_CONFIG_FILE))


def training_workbook(case_id: str = DEFAULT_CASE_ID) -> str:
    if case_id == DEFAULT_CASE_ID:
        return _abs(settings.WHATIF_TRAINING_WORKBOOK)
    return os.path.join(data_dir(case_id), os.path.basename(settings.WHATIF_TRAINING_WORKBOOK))


def historian_file(case_id: str = DEFAULT_CASE_ID) -> str:
    if case_id == DEFAULT_CASE_ID:
        return _abs(settings.WHATIF_HISTORIAN_FILE)
    return os.path.join(results_dir(case_id), os.path.basename(settings.WHATIF_HISTORIAN_FILE))


def scripts_dir() -> str:
    return _abs("Scripts")


def whatif_train_script() -> str:
    """Case-independent, matching the Streamlit reference: the training
    script itself isn't per-plant/per-case, only the data it reads/writes is."""
    return os.path.join(scripts_dir(), "Model_development_and_static_whatif_testing_updated.py")


def new_case_dirs(case_id: str) -> tuple[str, str]:
    """(data_dir, model_dir) for a brand-new case — callers create these as
    empty folders (no files copied/templated, matching the Streamlit
    reference's "build it all from Setup" new-plant flow) before the case
    is usable."""
    return data_dir(case_id), model_dir(case_id)


def actual_vs_estimated_file(suffix: str, case_id: str = DEFAULT_CASE_ID) -> str:
    """Per-request output filename (never the fixed original name, to avoid
    concurrent-request overwrites — see engine.py's write_actual_vs_estimated_xlsx)."""
    return os.path.join(results_dir(case_id), f"Actual_vs_estimated_what_if_{suffix}.xlsx")
