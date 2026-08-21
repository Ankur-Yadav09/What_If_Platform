"""
src/data/database.py
====================
SQLite-backed dataset versioning layer.

Each uploaded dataset is serialised as Parquet (via pyarrow) and stored as a
BLOB in the ``datasets`` table.  This lets users switch between datasets
without re-uploading files on every session restart.

Datasets are isolated per What-If "case" (see whatif_cases below) — a
dataset uploaded while case A is active is invisible to case B, and the two
may reuse the same name independently (see _migrate_datasets_case_scoping()).

Schema
------
datasets(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    upload_time TEXT,
    num_rows    INTEGER,
    num_cols    INTEGER,
    data        BLOB,
    plant       TEXT,
    unit        TEXT,
    case_id     TEXT NOT NULL DEFAULT 'default',
    UNIQUE(case_id, name)
)

Public API
----------
init_db()
save_dataset_to_db(name, df, case_id=DEFAULT_CASE_ID)
list_datasets_from_db(case_id=DEFAULT_CASE_ID)          → list[tuple]
load_dataset_from_db(name, case_id=DEFAULT_CASE_ID)     → DataFrame | None
delete_dataset_from_db(name, case_id=DEFAULT_CASE_ID)
"""
from __future__ import annotations

import datetime
import io
import json
import sqlite3
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config.settings import DB_PATH

# The un-nested, flat Data/Results/saved_models layout every path in this
# repo already used before per-case isolation existed — resolving to this
# id is a complete no-op relative to that pre-existing layout, so nothing
# has to move on disk for existing installs (see src/whatif/paths.py's
# _case_dir() and src/persistence/model_store.py's mirror of it).
DEFAULT_CASE_ID = "default"

# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Idempotently add a column to an existing table (SQLite has no
    ``ADD COLUMN IF NOT EXISTS``). Safe to call on every startup — existing
    rows get ``NULL`` for the new column, nothing is dropped or rewritten."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _migrate_datasets_case_scoping(conn: sqlite3.Connection) -> None:
    """One-time schema rebuild: datasets.name was UNIQUE globally, but two
    different cases legitimately want to reuse the same dataset name (e.g.
    re-uploading "YANPET_Data.xlsx" fresh into every new case) -- the
    uniqueness needs to move to (case_id, name). SQLite can't ALTER a
    UNIQUE constraint in place, so this rebuilds the table: reconstruct
    every existing column from PRAGMA table_info (so plant/unit, added via
    _ensure_column further up, come along automatically) plus a new
    case_id column, copy every existing row across as case_id='default'
    (zero data movement for existing installs), drop the old table, rename.
    Guarded by checking whether case_id already exists, so this only ever
    runs once per database."""
    info = conn.execute("PRAGMA table_info(datasets)").fetchall()
    existing_cols = [row[1] for row in info]
    if "case_id" in existing_cols:
        return  # already migrated

    col_defs = [
        f"{name} {coltype} PRIMARY KEY AUTOINCREMENT" if pk else f"{name} {coltype}"
        for (_cid, name, coltype, _notnull, _dflt, pk) in info
    ]
    col_defs.append(f"case_id TEXT NOT NULL DEFAULT '{DEFAULT_CASE_ID}'")
    col_list = ", ".join(existing_cols)

    conn.execute(f"CREATE TABLE datasets_new ({', '.join(col_defs)}, UNIQUE(case_id, name))")
    conn.execute(f"INSERT INTO datasets_new ({col_list}) SELECT {col_list} FROM datasets")
    conn.execute("DROP TABLE datasets")
    conn.execute("ALTER TABLE datasets_new RENAME TO datasets")


def init_db() -> None:
    """Create all required tables if they do not already exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    UNIQUE,
                upload_time TEXT,
                num_rows    INTEGER,
                num_cols    INTEGER,
                data        BLOB
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_registry (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name   TEXT,
                algorithm    TEXT,
                created_at   TEXT,
                dataset_name TEXT,
                x_cols       TEXT,
                y_cols       TEXT,
                avg_r2       REAL,
                avg_rmse     REAL,
                avg_mae      REAL,
                file_path    TEXT
            )
            """
        )
        # Added for the "Connect Process Data" page's Plant/System-Unit
        # metadata. list_datasets_from_db() below deliberately keeps its
        # original 4-column SELECT unchanged (Streamlit's upload.py builds a
        # fixed-width DataFrame from it) — see list_datasets_with_metadata().
        _ensure_column(conn, "datasets", "plant", "TEXT")
        _ensure_column(conn, "datasets", "unit", "TEXT")
        _migrate_datasets_case_scoping(conn)
        # Train-set metrics, added alongside the original test-set avg_r2/
        # avg_rmse/avg_mae so overfitting is visible without a live,
        # leakage-prone recompute (see overview_service.py's retired
        # get_model_performance()). Existing rows get NULL, shown as "—".
        _ensure_column(conn, "model_registry", "train_r2", "REAL")
        _ensure_column(conn, "model_registry", "train_rmse", "REAL")
        _ensure_column(conn, "model_registry", "train_mae", "REAL")
        # Which saved Soft Sensor model (model_registry/saved_models) is the
        # active predictor for a given What-If "Predicted parameter" — the
        # single, narrow bridge between the two otherwise-separate
        # persistence worlds (see ARCHITECTURE.md §4). One row per
        # (case_id, parameter); selecting a new model for the same parameter
        # in the same case replaces this row rather than adding another (see
        # set_model_selection() — enforced in application code via an
        # explicit DELETE+INSERT, not a composite PRIMARY KEY, since this
        # table already shipped with a single-column `parameter` PK and
        # SQLite can't cheaply change a PK on an existing table).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatif_model_selection (
                parameter   TEXT PRIMARY KEY,
                model_name  TEXT NOT NULL,
                selected_at TEXT NOT NULL
            )
            """
        )
        # Isolates Soft Sensor's trained-model layer (model_registry,
        # saved_models/ on disk) and the What-If model-selection bridge
        # per What-If "case" (see whatif_cases below) — every existing row
        # defaults to DEFAULT_CASE_ID, i.e. today's single shared model list,
        # so nothing changes for existing installs until a second case exists.
        _ensure_column(conn, "model_registry", "case_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_CASE_ID}'")
        _ensure_column(conn, "whatif_model_selection", "case_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_CASE_ID}'")
        # What-If "cases" — folder-per-case isolation modeled on the
        # legacy Streamlit reference app's multi-plant structure (see
        # src/whatif/paths.py's _case_dir()), applied here to isolated
        # scenario setups for the same single plant rather than different
        # plants. case_id is the sanitized, folder-safe identifier used
        # directly as the Data/<case_id> and Results/<case_id> folder name.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whatif_cases (
                case_id        TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                last_opened_at TEXT NOT NULL
            )
            """
        )
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT OR IGNORE INTO whatif_cases (case_id, name, created_at, last_opened_at) VALUES (?, ?, ?, ?)",
            (DEFAULT_CASE_ID, "Default Case", now, now),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def _sanitize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """Resolve mixed-type object columns so PyArrow can serialise to Parquet.

    For each object column:
    - If all non-null values are numeric, cast to float.
    - Otherwise, cast every value to str (None preserved for nulls).
    """
    df = df.copy()
    for col in df.columns:
        if df[col].dtype != object:
            continue
        as_num = pd.to_numeric(df[col], errors="coerce")
        non_null = df[col].notna()
        if non_null.sum() == 0 or as_num[non_null].notna().all():
            df[col] = as_num
        else:
            df[col] = df[col].apply(lambda x: str(x) if pd.notna(x) else None)
    return df


def save_dataset_to_db(
    name: str, df: pd.DataFrame, plant: Optional[str] = None, unit: Optional[str] = None,
    case_id: str = DEFAULT_CASE_ID,
) -> None:
    """
    Upsert a DataFrame into the database, scoped to case_id.

    If a dataset with the same *(case_id, name)* already exists it is
    replaced (INSERT OR REPLACE semantics) — note this also resets
    plant/unit to whatever is passed (or NULL if omitted), since REPLACE
    rewrites the whole row; existing callers that omit plant/unit are
    unaffected in practice since re-uploading the exact same filename into
    the same case is rare. The same name in a *different* case_id is a
    separate row entirely (see _migrate_datasets_case_scoping()).
    """
    blob = _sanitize_for_parquet(df).to_parquet()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO datasets
                (name, upload_time, num_rows, num_cols, data, plant, unit, case_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, now, len(df), len(df.columns), blob, plant, unit, case_id),
        )
        conn.commit()


def list_datasets_from_db(case_id: str = DEFAULT_CASE_ID) -> List[Tuple]:
    """
    Return summary rows for case_id ordered by most recently uploaded.

    Each row is ``(name, upload_time, num_rows, num_cols)``.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT name, upload_time, num_rows, num_cols "
            "FROM datasets WHERE case_id = ? ORDER BY upload_time DESC",
            (case_id,),
        ).fetchall()
    return rows


def list_datasets_with_metadata(case_id: str = DEFAULT_CASE_ID) -> List[Tuple]:
    """
    Like list_datasets_from_db(), plus Plant/System-Unit metadata.

    Each row is ``(name, upload_time, num_rows, num_cols, plant, unit)``.
    Kept as a separate function (rather than changing list_datasets_from_db's
    return shape) so Streamlit's upload.py — which builds a fixed 4-column
    DataFrame straight from list_datasets_from_db()'s rows — is unaffected.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT name, upload_time, num_rows, num_cols, plant, unit "
            "FROM datasets WHERE case_id = ? ORDER BY upload_time DESC",
            (case_id,),
        ).fetchall()
    return rows


def load_dataset_from_db(name: str, case_id: str = DEFAULT_CASE_ID) -> Optional[pd.DataFrame]:
    """
    Retrieve a DataFrame by (name, case_id).

    Returns ``None`` if the name is not found in this case or if the stored
    Parquet blob is incompatible with the current PyArrow version (e.g.
    saved by an older version). Callers should surface the None case to the
    user.
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT data FROM datasets WHERE name = ? AND case_id = ?", (name, case_id)
        ).fetchone()
    if row:
        try:
            return pd.read_parquet(io.BytesIO(row[0]))
        except Exception:
            return None
    return None


def delete_dataset_from_db(name: str, case_id: str = DEFAULT_CASE_ID) -> None:
    """Remove a dataset record (and its Parquet blob) by (name, case_id)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM datasets WHERE name = ? AND case_id = ?", (name, case_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


def save_model_to_registry(
    model_name: str,
    algorithm: str,
    dataset_name: str,
    x_cols: List[str],
    y_cols: List[str],
    avg_r2: float,
    avg_rmse: float,
    avg_mae: float,
    file_path: str,
    train_r2: Optional[float] = None,
    train_rmse: Optional[float] = None,
    train_mae: Optional[float] = None,
    case_id: str = DEFAULT_CASE_ID,
) -> int:
    """Insert a model record into the registry. Returns the new row id."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO model_registry
                (model_name, algorithm, created_at, dataset_name,
                 x_cols, y_cols, avg_r2, avg_rmse, avg_mae, file_path,
                 train_r2, train_rmse, train_mae, case_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                model_name, algorithm, now, dataset_name,
                json.dumps(x_cols), json.dumps(y_cols),
                round(float(avg_r2), 4), round(float(avg_rmse), 4), round(float(avg_mae), 4),
                file_path,
                round(float(train_r2), 4) if train_r2 is not None else None,
                round(float(train_rmse), 4) if train_rmse is not None else None,
                round(float(train_mae), 4) if train_mae is not None else None,
                case_id,
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_models_from_registry(case_id: str = DEFAULT_CASE_ID) -> List[Dict]:
    """Return all model registry records for `case_id`, most recent first."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, model_name, algorithm, created_at, dataset_name, "
            "x_cols, y_cols, avg_r2, avg_rmse, avg_mae, file_path, "
            "train_r2, train_rmse, train_mae "
            "FROM model_registry WHERE case_id = ? ORDER BY created_at DESC",
            (case_id,),
        ).fetchall()
    result = []
    for r in rows:
        result.append({
            "id":           r[0],
            "model_name":   r[1],
            "algorithm":    r[2],
            "created_at":   r[3],
            "dataset_name": r[4],
            "x_cols":       json.loads(r[5]) if r[5] else [],
            "y_cols":       json.loads(r[6]) if r[6] else [],
            "avg_r2":       r[7],
            "avg_rmse":     r[8],
            "avg_mae":      r[9],
            "file_path":    r[10],
            "train_r2":     r[11],
            "train_rmse":   r[12],
            "train_mae":    r[13],
        })
    return result


def delete_model_from_registry(model_id: int) -> None:
    """Remove a model registry entry by id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM model_registry WHERE id = ?", (model_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# What-If model selection (Experiment History "Use for What-If Analysis")
# ---------------------------------------------------------------------------


def set_model_selection(parameter: str, model_name: str, case_id: str = DEFAULT_CASE_ID) -> None:
    """Mark model_name as the active Soft Sensor model for parameter within
    case_id. Explicit DELETE+INSERT (rather than INSERT OR REPLACE against a
    PRIMARY KEY) is what guarantees only one experiment can be selected per
    (case_id, parameter) — see the case_id column's schema-bootstrap note."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM whatif_model_selection WHERE case_id = ? AND parameter = ?",
            (case_id, parameter),
        )
        conn.execute(
            """
            INSERT INTO whatif_model_selection (parameter, model_name, selected_at, case_id)
            VALUES (?, ?, ?, ?)
            """,
            (parameter, model_name, now, case_id),
        )
        conn.commit()


def clear_model_selection(parameter: str, case_id: str = DEFAULT_CASE_ID) -> None:
    """Remove any selection for parameter within case_id, reverting it to the
    dedicated Kalman-filter fallback path in src/whatif/engine.py."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "DELETE FROM whatif_model_selection WHERE case_id = ? AND parameter = ?",
            (case_id, parameter),
        )
        conn.commit()


def list_model_selections(case_id: str = DEFAULT_CASE_ID) -> Dict[str, str]:
    """Return {parameter: model_name} for every currently selected experiment
    within case_id."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT parameter, model_name FROM whatif_model_selection WHERE case_id = ?",
            (case_id,),
        ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# What-If cases — folder-per-case isolation (see DEFAULT_CASE_ID docstring
# and src/whatif/paths.py's _case_dir())
# ---------------------------------------------------------------------------


def sanitize_case_id(name: str) -> str:
    """Folder-safe case identifier from a user-typed display name — mirrors
    the legacy Streamlit reference app's plant-name sanitization exactly."""
    import re

    return re.sub(r"[^A-Za-z0-9_-]", "_", (name or "").strip())


def create_case(case_id: str, name: str) -> None:
    """Registers a new case. Raises sqlite3.IntegrityError if case_id already
    exists — callers should check list_cases()/get_case() first for a
    friendlier duplicate-name error."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO whatif_cases (case_id, name, created_at, last_opened_at) VALUES (?, ?, ?, ?)",
            (case_id, name, now, now),
        )
        conn.commit()


def list_cases() -> List[Dict]:
    """Every case, most recently opened first."""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT case_id, name, created_at, last_opened_at FROM whatif_cases ORDER BY last_opened_at DESC"
        ).fetchall()
    return [
        {"case_id": r[0], "name": r[1], "created_at": r[2], "last_opened_at": r[3]}
        for r in rows
    ]


def get_case(case_id: str) -> Optional[Dict]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT case_id, name, created_at, last_opened_at FROM whatif_cases WHERE case_id = ?",
            (case_id,),
        ).fetchone()
    if row is None:
        return None
    return {"case_id": row[0], "name": row[1], "created_at": row[2], "last_opened_at": row[3]}


def touch_case_opened(case_id: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE whatif_cases SET last_opened_at = ? WHERE case_id = ?", (now, case_id))
        conn.commit()
