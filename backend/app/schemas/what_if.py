from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WhatIfCase(BaseModel):
    case_id: str
    name: str
    created_at: str
    last_opened_at: str


class CasesListResponse(BaseModel):
    cases: List[WhatIfCase]


class CreateCaseRequest(BaseModel):
    name: str


class ConfigStatusResponse(BaseModel):
    pi_mapping_present: bool
    pi_mapping_row_count: int
    model_details_present: bool
    model_details_row_count: int
    source_path: Optional[str] = None


class RowsResponse(BaseModel):
    rows: List[Dict[str, Any]]


class GenerateMappingRequest(BaseModel):
    cgc_stages: int = 0
    prc_stages: int = 0
    erc_stages: int = 0
    furnaces: int = 0


class GenerateMappingResponse(BaseModel):
    rows: List[Dict[str, Any]]
    section_counts: Dict[str, int]
    wizard_selection: Dict[str, Any]


class DetectedCountsResponse(BaseModel):
    cgc_max: int
    prc_max: int
    erc_max: int
    furnace_max: int


class MappingRowsRequest(BaseModel):
    rows: List[Dict[str, Any]]


class ModelMappingResponse(BaseModel):
    rows: List[Dict[str, Any]]
    historian_tags: List[str]


class FormulaValidateRequest(BaseModel):
    formula: str


class FormulaValidateResponse(BaseModel):
    valid: bool
    errors: List[str] = []
    variables: List[str] = []


class ConfigExportRequest(BaseModel):
    pi_mapping_rows: List[Dict[str, Any]]
    model_details_rows: List[Dict[str, Any]]
    constraints_rows: List[Dict[str, Any]] = []
    user_inputs_rows: List[Dict[str, Any]] = []
    display_order_rows: List[Dict[str, Any]] = []
    section_order_rows: List[Dict[str, Any]] = []
    mvdvcv_rows: List[Dict[str, Any]] = []
    formulas_rows: List[Dict[str, Any]] = []
    target_section: Optional[str] = None
    format: str = "xlsx"  # "xlsx" | "csv"


class TrainingDataUploadResponse(BaseModel):
    saved: bool
    sheets_found: List[str]
    missing_sheets: List[str]


class ModelStatusResponse(BaseModel):
    all_present: bool
    tags_ok: List[str]
    tags_missing: List[str]
    pkl_count: int
    required_pkl_count: int
    raw_sim_present: bool
    training_data_present: bool
    model_mapping_filled: bool
    can_train: bool
    train_blockers: List[str]
    training_required: bool


class TrainModelsResponse(BaseModel):
    job_id: str


class TrainModelsResult(BaseModel):
    success: bool
    returncode: int
    stdout_tail: str
    stderr_tail: str
    pkl_count: int
    all_present: bool
    raw_sim_present: bool


class TargetSectionResponse(BaseModel):
    section_order: List[str]
    target_section: Optional[str] = None
    active_scope: List[str]  # upstream sections + target, in process-flow order
    excluded_sections: List[str]  # downstream sections hidden by the current scope


class TargetSectionRequest(BaseModel):
    target_section: Optional[str] = None


class ConfigSaveRequest(BaseModel):
    """All 8 sheets in one call — the config workbook's single-shot
    persistence endpoint (config/save), as opposed to the download-only
    config/export."""
    pi_mapping_rows: List[Dict[str, Any]] = []
    model_details_rows: List[Dict[str, Any]] = []
    constraints_rows: List[Dict[str, Any]] = []
    user_inputs_rows: List[Dict[str, Any]] = []
    display_order_rows: List[Dict[str, Any]] = []
    section_order_rows: List[Dict[str, Any]] = []
    mvdvcv_rows: List[Dict[str, Any]] = []
    target_section: Optional[str] = None


class CorrelationMatrixResponse(BaseModel):
    columns: List[str]
    matrix: List[List[Optional[float]]]
    n_rows: int


class AccuracySummaryResponse(BaseModel):
    rows: List[Dict[str, Any]]
    available: bool


class TagOptionsRequest(BaseModel):
    # Wizard-generated tags, held client-side since there's no server session
    # in this design (see plan Section 6: config/mapping endpoints all take
    # full state per-request rather than relying on session state).
    generated_tags: List[str] = []
    target_section: Optional[str] = None


class TagOptionsResponse(BaseModel):
    tags: List[str]
    all_tags: List[str]
    source: str  # "wizard" | "config" | "historian"
    limits: Dict[str, Dict[str, float]]


class DatesResponse(BaseModel):
    dates: List[str]


class TimestampsResponse(BaseModel):
    timestamps: List[str]


class BaselineResponse(BaseModel):
    values: Dict[str, Any]


class OverrideInput(BaseModel):
    parameter: str
    value: float


class WhatIfScenarioRequest(BaseModel):
    timestamp: str
    overrides: List[OverrideInput] = []
    write_actual_vs_estimated_xlsx: bool = False
    target_section: Optional[str] = None


class WhatIfScenarioRow(BaseModel):
    parameter: str
    actual: Any = None
    estimated: Any = None
    change: Optional[float] = None


class WhatIfKpi(BaseModel):
    tag: str
    actual: float
    estimated: float
    change: float


class WhatIfScenarioResponse(BaseModel):
    constraint_hit: bool
    constraint_message: Optional[str] = None
    rows: List[WhatIfScenarioRow]
    kpis: List[WhatIfKpi]


class ValidationFilterCriterion(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    values: Optional[List[Any]] = None


class ValidationFilterRequest(BaseModel):
    filters: Dict[str, ValidationFilterCriterion]
    target_section: Optional[str] = None


class ValidationFilterResponse(BaseModel):
    rows: List[Dict[str, Any]]
    match_count: int


class WhatIfExportCsvRequest(BaseModel):
    timestamp: str
    rows: List[WhatIfScenarioRow]
    validation_rows: Optional[List[Dict[str, Any]]] = None
