from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from backend.app.schemas.datasets import DatasetSummary


class SavedModelSummary(BaseModel):
    name: str
    saved_at: str
    input_dim: int
    output_dim: int
    algorithm: Optional[str] = None
    dataset_name: Optional[str] = None
    avg_r2: Optional[float] = None
    avg_rmse: Optional[float] = None
    avg_mae: Optional[float] = None
    train_r2: Optional[float] = None
    train_rmse: Optional[float] = None
    train_mae: Optional[float] = None
    x_cols: List[str] = []
    y_cols: List[str] = []
    selected_for: List[str] = []


class OverviewResponse(BaseModel):
    datasets: List[DatasetSummary]
    saved_models: List[SavedModelSummary]


class SelectModelRequest(BaseModel):
    parameter: str
    model_name: str


class ClearSelectionRequest(BaseModel):
    parameter: str
