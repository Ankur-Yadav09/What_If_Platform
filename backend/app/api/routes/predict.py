from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.app.api.deps import require_valid_case_id
from backend.app.schemas.predict import PredictRequest, PredictResponse
from backend.app.services.predict_service import run_predict

router = APIRouter(tags=["predict"], dependencies=[Depends(require_valid_case_id)])


@router.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, case_id: str = Query("default")) -> PredictResponse:
    result = run_predict(
        model_name=body.model_name,
        source=body.source,
        project_id=body.project_id,
        dataset_name=body.dataset_name,
        row_start=body.row_start,
        row_end=body.row_end,
        case_id=case_id,
    )
    return PredictResponse(**result)
