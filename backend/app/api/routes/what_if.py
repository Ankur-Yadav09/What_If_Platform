from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import Response

from backend.app.schemas import what_if as schemas
from backend.app.services import what_if_service, whatif_case_service

router = APIRouter(prefix="/what-if", tags=["what-if"])


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@router.get("/cases", response_model=schemas.CasesListResponse)
def cases_list() -> schemas.CasesListResponse:
    return whatif_case_service.list_cases()


@router.post("/cases", response_model=schemas.WhatIfCase)
def cases_create(body: schemas.CreateCaseRequest) -> schemas.WhatIfCase:
    return whatif_case_service.create_case(body)


@router.post("/cases/{case_id}/open", response_model=schemas.WhatIfCase)
def cases_open(case_id: str) -> schemas.WhatIfCase:
    return whatif_case_service.open_case(case_id)


# ---------------------------------------------------------------------------
# Config / wizard / model-status (case setup)
#
# Every route below takes case_id as a query param defaulting to "default"
# (paths.py's DEFAULT_CASE_ID), so existing callers that don't send it keep
# reading/writing the original flat Data/Results layout unchanged.
# ---------------------------------------------------------------------------

@router.get("/config/status", response_model=schemas.ConfigStatusResponse)
def config_status(case_id: str = Query("default")) -> schemas.ConfigStatusResponse:
    return what_if_service.get_config_status(case_id)


@router.get("/config/pi-mapping", response_model=schemas.RowsResponse)
def config_pi_mapping(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_pi_mapping(case_id)


@router.post("/config/upload", response_model=schemas.ConfigStatusResponse)
async def config_upload(file: UploadFile, case_id: str = Query("default")) -> schemas.ConfigStatusResponse:
    return await what_if_service.upload_config(file, case_id)


@router.get("/wizard/detected-counts", response_model=schemas.DetectedCountsResponse)
def wizard_detected_counts(case_id: str = Query("default")) -> schemas.DetectedCountsResponse:
    return what_if_service.get_detected_counts(case_id)


@router.post("/wizard/generate-mapping", response_model=schemas.GenerateMappingResponse)
def wizard_generate_mapping(
    body: schemas.GenerateMappingRequest, case_id: str = Query("default")
) -> schemas.GenerateMappingResponse:
    return what_if_service.generate_mapping(body, case_id)


@router.put("/config/mapping", response_model=schemas.RowsResponse)
def config_commit_mapping(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_mapping(body, case_id)


@router.get("/config/model-mapping", response_model=schemas.ModelMappingResponse)
def config_get_model_mapping(case_id: str = Query("default")) -> schemas.ModelMappingResponse:
    return what_if_service.get_model_mapping(case_id)


@router.put("/config/model-mapping", response_model=schemas.RowsResponse)
def config_commit_model_mapping(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_model_mapping(body, case_id)


@router.get("/config/formulas", response_model=schemas.RowsResponse)
def config_get_formulas(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_formulas(case_id)


@router.put("/config/formulas", response_model=schemas.RowsResponse)
def config_commit_formulas(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_formulas(body, case_id)


@router.post("/config/formulas/validate", response_model=schemas.FormulaValidateResponse)
def config_validate_formula(body: schemas.FormulaValidateRequest) -> schemas.FormulaValidateResponse:
    return what_if_service.validate_formula(body)


@router.post("/config/export")
def config_export(body: schemas.ConfigExportRequest) -> Response:
    data, media_type, filename = what_if_service.export_config(body)
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/config/section-order", response_model=schemas.RowsResponse)
def config_section_order(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_section_order(case_id)


@router.put("/config/section-order", response_model=schemas.RowsResponse)
def config_commit_section_order(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_section_order(body, case_id)


@router.get("/config/mv-dv-cv-taglist", response_model=schemas.RowsResponse)
def config_mvdvcv_taglist(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_mvdvcv_taglist(case_id)


@router.put("/config/mv-dv-cv-taglist", response_model=schemas.RowsResponse)
def config_commit_mvdvcv_taglist(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_mvdvcv_taglist(body, case_id)


@router.get("/config/constraints", response_model=schemas.RowsResponse)
def config_constraints(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_constraints(case_id)


@router.put("/config/constraints", response_model=schemas.RowsResponse)
def config_commit_constraints(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_constraints(body, case_id)


@router.get("/config/user-inputs", response_model=schemas.RowsResponse)
def config_user_inputs(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_user_inputs(case_id)


@router.put("/config/user-inputs", response_model=schemas.RowsResponse)
def config_commit_user_inputs(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_user_inputs(body, case_id)


@router.get("/config/column-order", response_model=schemas.RowsResponse)
def config_column_order(case_id: str = Query("default")) -> schemas.RowsResponse:
    return what_if_service.get_column_order(case_id)


@router.put("/config/column-order", response_model=schemas.RowsResponse)
def config_commit_column_order(
    body: schemas.MappingRowsRequest, case_id: str = Query("default")
) -> schemas.RowsResponse:
    return what_if_service.commit_column_order(body, case_id)


@router.get("/config/target-section", response_model=schemas.TargetSectionResponse)
def config_target_section(case_id: str = Query("default")) -> schemas.TargetSectionResponse:
    return what_if_service.get_target_section(case_id)


@router.put("/config/target-section", response_model=schemas.TargetSectionResponse)
def config_set_target_section(
    body: schemas.TargetSectionRequest, case_id: str = Query("default")
) -> schemas.TargetSectionResponse:
    return what_if_service.set_target_section(body, case_id)


@router.post("/config/save", response_model=schemas.ConfigStatusResponse)
def config_save(body: schemas.ConfigSaveRequest, case_id: str = Query("default")) -> schemas.ConfigStatusResponse:
    return what_if_service.save_config(body, case_id)


@router.get("/config/correlation-matrix", response_model=schemas.CorrelationMatrixResponse)
def config_correlation_matrix(case_id: str = Query("default")) -> schemas.CorrelationMatrixResponse:
    return what_if_service.get_correlation_matrix(case_id)


@router.get("/models/accuracy-summary", response_model=schemas.AccuracySummaryResponse)
def models_accuracy_summary(case_id: str = Query("default")) -> schemas.AccuracySummaryResponse:
    return what_if_service.get_accuracy_summary(case_id)


@router.post("/training-data/upload", response_model=schemas.TrainingDataUploadResponse)
async def training_data_upload(
    file: UploadFile, case_id: str = Query("default")
) -> schemas.TrainingDataUploadResponse:
    return await what_if_service.upload_training_data(file, case_id)


@router.get("/models/status", response_model=schemas.ModelStatusResponse)
def models_status(case_id: str = Query("default")) -> schemas.ModelStatusResponse:
    return what_if_service.get_models_status(case_id)


@router.post("/models/train", response_model=schemas.TrainModelsResponse, status_code=202)
def models_train(case_id: str = Query("default")) -> schemas.TrainModelsResponse:
    job_id = what_if_service.train_models(case_id)
    return schemas.TrainModelsResponse(job_id=job_id)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.post("/dashboard/tag-options", response_model=schemas.TagOptionsResponse)
def dashboard_tag_options(
    body: schemas.TagOptionsRequest, case_id: str = Query("default")
) -> schemas.TagOptionsResponse:
    return what_if_service.get_tag_options(body, case_id)


@router.get("/dashboard/dates", response_model=schemas.DatesResponse)
def dashboard_dates(case_id: str = Query("default")) -> schemas.DatesResponse:
    return what_if_service.get_dates(case_id)


@router.get("/dashboard/timestamps", response_model=schemas.TimestampsResponse)
def dashboard_timestamps(date: str = Query(...), case_id: str = Query("default")) -> schemas.TimestampsResponse:
    return what_if_service.get_timestamps(date, case_id)


@router.get("/dashboard/baseline", response_model=schemas.BaselineResponse)
def dashboard_baseline(
    timestamp: str = Query(...),
    tags: Optional[str] = Query(None, description="Comma-separated tag list"),
    case_id: str = Query("default"),
) -> schemas.BaselineResponse:
    tag_list: List[str] = [t for t in (tags or "").split(",") if t]
    return what_if_service.get_baseline(timestamp, tag_list, case_id)


@router.post("/dashboard/compute", response_model=schemas.WhatIfScenarioResponse)
def dashboard_compute(
    body: schemas.WhatIfScenarioRequest, case_id: str = Query("default")
) -> schemas.WhatIfScenarioResponse:
    return what_if_service.run_scenario(body, case_id)


@router.post("/dashboard/validation-filter", response_model=schemas.ValidationFilterResponse)
def dashboard_validation_filter(
    body: schemas.ValidationFilterRequest, case_id: str = Query("default")
) -> schemas.ValidationFilterResponse:
    return what_if_service.run_validation_filter(body, case_id)


@router.post("/dashboard/export-csv")
def dashboard_export_csv(body: schemas.WhatIfExportCsvRequest) -> Response:
    data, media_type, filename = what_if_service.export_scenario_csv(body)
    return Response(
        content=data, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
