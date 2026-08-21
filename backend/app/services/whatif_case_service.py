"""
backend/app/services/whatif_case_service.py
=============================================
CRUD for the "cases" that scope What-If config, Kalman models, and the
Soft Sensor model-selection bridge to isolated folders/rows — modeled on
the legacy Streamlit reference app's multi-plant create/switch flow (see
src/whatif/paths.py's module docstring). Blank folders only: nothing is
copied/templated into a new case, matching the reference app's "build it
all fresh from Setup" behavior.
"""
from __future__ import annotations

import os
import sqlite3

from fastapi import HTTPException

from src.data import database
from src.whatif import paths

from backend.app.schemas import what_if as schemas


def list_cases() -> schemas.CasesListResponse:
    return schemas.CasesListResponse(cases=[schemas.WhatIfCase(**c) for c in database.list_cases()])


def create_case(body: schemas.CreateCaseRequest) -> schemas.WhatIfCase:
    case_id = database.sanitize_case_id(body.name)
    if not case_id:
        raise HTTPException(status_code=422, detail="Case name must contain at least one letter, digit, '_' or '-'.")
    if database.get_case(case_id) is not None:
        raise HTTPException(status_code=409, detail=f"A case named '{case_id}' already exists.")

    try:
        database.create_case(case_id, body.name.strip())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail=f"A case named '{case_id}' already exists.")

    data_dir, model_dir = paths.new_case_dirs(case_id)
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(model_dir, exist_ok=True)

    case = database.get_case(case_id)
    return schemas.WhatIfCase(**case)


def open_case(case_id: str) -> schemas.WhatIfCase:
    case = database.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    database.touch_case_opened(case_id)
    case = database.get_case(case_id)
    return schemas.WhatIfCase(**case)
