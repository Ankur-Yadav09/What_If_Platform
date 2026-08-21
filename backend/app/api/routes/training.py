from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.app.jobs.manager import job_manager
from backend.app.schemas.training import TrainingRequest
from backend.app.services.training_service import prepare_training_job

router = APIRouter(prefix="/training", tags=["training"])


@router.post("/jobs", status_code=202)
def submit_training(body: TrainingRequest, case_id: str = Query("default")) -> dict:
    try:
        target, progress_mode = prepare_training_job(
            body.project_id, body.algorithm, body.hyperparameters, case_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = job_manager.submit(target, progress_mode=progress_mode)
    return {"job_id": job_id}
