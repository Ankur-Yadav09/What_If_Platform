from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.schemas.overview import ClearSelectionRequest, OverviewResponse, SelectModelRequest
from backend.app.services import overview_service

router = APIRouter(tags=["overview"])


@router.get("/overview", response_model=OverviewResponse)
def get_overview(case_id: str = Query("default")) -> OverviewResponse:
    return overview_service.get_overview(case_id)


@router.post("/overview/select-model", response_model=OverviewResponse)
def select_model(payload: SelectModelRequest, case_id: str = Query("default")) -> OverviewResponse:
    try:
        return overview_service.select_model_for_parameter(payload.parameter, payload.model_name, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/overview/clear-selection", response_model=OverviewResponse)
def clear_selection(payload: ClearSelectionRequest, case_id: str = Query("default")) -> OverviewResponse:
    return overview_service.clear_model_selection(payload.parameter, case_id)


@router.delete("/overview/models/{model_name}", response_model=OverviewResponse)
def delete_model(model_name: str, case_id: str = Query("default")) -> OverviewResponse:
    return overview_service.delete_model(model_name, case_id)
