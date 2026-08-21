"""
backend/app/services/dataset_service.py
==========================================
Thin adapter over src.data.database — every function is parameterized by an
explicit dataset `name`, scoped to a `case_id` (the (case_id, name) pair is
the `datasets` table's real key — see database.py's module docstring).
There is no "active dataset" concept here: nothing is cached in this
process between requests. See §2 ("Identifiers") of the migration plan.
"""
from __future__ import annotations

import io
import json
from typing import Optional

import pandas as pd
from fastapi import HTTPException, UploadFile

from src.data.database import (
    DEFAULT_CASE_ID,
    delete_dataset_from_db,
    list_datasets_from_db,
    list_datasets_with_metadata,
    load_dataset_from_db,
    save_dataset_to_db,
)
from backend.app.schemas.datasets import DatasetPreview, DatasetSummary


def _row_to_summary(row: tuple) -> DatasetSummary:
    # list_datasets_with_metadata() rows: (name, uploaded_at, rows, cols, plant, unit)
    name, uploaded_at, rows, cols, plant, unit = row
    return DatasetSummary(
        name=name,
        uploaded_at=uploaded_at,
        rows=rows,
        cols=cols,
        plant=plant,
        unit=unit,
        # Computed fresh, not persisted: a dataset only ever reaches this list
        # after a successful save, so "Ready" is accurate until proven
        # otherwise — real failures (e.g. a PyArrow-incompatible blob) surface
        # at preview/use time via get_dataset_preview's 422, not here.
        status="Ready",
    )


def _find_summary(name: str, case_id: str = DEFAULT_CASE_ID) -> DatasetSummary:
    for row in list_datasets_with_metadata(case_id):
        if row[0] == name:
            return _row_to_summary(row)
    raise HTTPException(status_code=404, detail=f"Dataset '{name}' not found.")


async def upload_dataset(
    file: UploadFile,
    dataset_name: Optional[str] = None,
    plant: Optional[str] = None,
    unit: Optional[str] = None,
    case_id: str = DEFAULT_CASE_ID,
) -> DatasetSummary:
    file_bytes = await file.read()
    filename = file.filename or "upload"
    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not parse '{filename}': {exc}"
        ) from exc

    resolved_name = dataset_name or filename
    save_dataset_to_db(resolved_name, df, plant=plant, unit=unit, case_id=case_id)
    return _find_summary(resolved_name, case_id)


def list_datasets(case_id: str = DEFAULT_CASE_ID) -> list[DatasetSummary]:
    return [_row_to_summary(row) for row in list_datasets_with_metadata(case_id)]


def get_dataset_preview(name: str, case_id: str = DEFAULT_CASE_ID) -> DatasetPreview:
    _find_summary(name, case_id)  # 404 if unknown, before touching the (possibly large) blob
    df = load_dataset_from_db(name, case_id)
    if df is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not load '{name}' — the stored data is incompatible "
                "with the current PyArrow version. Please delete this entry "
                "and re-upload the file."
            ),
        )
    head = df.head(10).copy()
    # A dataset that's been through Automated/Basic Preprocessing may carry a
    # real datetime64 column (cast_to_numeric() now preserves e.g.
    # "Timestamp" as one instead of destroying it -- see its docstring in
    # src/data/preprocessing.py). Format those as plain "YYYY-MM-DD HH:MM:SS"
    # strings before JSON-encoding, rather than the verbose ISO-with-
    # milliseconds pandas' to_json(date_format="iso") would otherwise
    # produce (e.g. "2025-01-01T00:00:00.000") -- .where(...) keeps a
    # missing timestamp as null instead of the literal string "NaT".
    for col in head.select_dtypes(include=["datetime64"]).columns:
        head[col] = head[col].dt.strftime("%Y-%m-%d %H:%M:%S").where(head[col].notna(), None)
    # NaN/NaT/numpy scalars aren't directly JSON-serializable — round-trip
    # through pandas' own JSON encoder, which already handles all of this.
    head_records = json.loads(head.to_json(orient="records"))
    return DatasetPreview(
        name=name,
        shape=list(df.shape),
        columns=df.columns.tolist(),
        head=head_records,
    )


def delete_dataset(name: str, case_id: str = DEFAULT_CASE_ID) -> None:
    _find_summary(name, case_id)  # 404 if unknown
    delete_dataset_from_db(name, case_id)
