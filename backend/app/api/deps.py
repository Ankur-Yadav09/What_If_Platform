"""
backend/app/api/deps.py
=========================
Shared FastAPI dependencies.

`require_valid_case_id` closes a path-traversal gap: every case-scoped
route reads `case_id` off the query string and hands it, unvalidated,
down to `src/whatif/paths.py` (`os.path.join(base_dir, case_id)`) and to
`src/persistence/model_store.py` / `src/data/database.py`'s case-scoped
tables. `database.sanitize_case_id()` only ever ran at case *creation*
(`whatif_case_service.create_case()`) -- a request quoting an existing
case's id straight from the URL, e.g. `?case_id=../../../../Windows`,
was never re-checked and would resolve a path outside `Data/`/`Results/`.

This dependency re-checks `case_id` against the `whatif_cases` registry
on every request, before any route handler runs. Attach it to every
router whose routes take `case_id` via `dependencies=[Depends(...)]` on
the `APIRouter(...)` call, so validation happens once per request no
matter how many routes (or which future ones) read the query param.
"""
from __future__ import annotations

from fastapi import HTTPException, Query

from src.data.database import DEFAULT_CASE_ID, get_case


def require_valid_case_id(case_id: str = Query(DEFAULT_CASE_ID)) -> str:
    if case_id != DEFAULT_CASE_ID and get_case(case_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown case_id '{case_id}'.")
    return case_id
