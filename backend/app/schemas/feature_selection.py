from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class FeatureSelectionRequest(BaseModel):
    dataset_name: str
    y_cols: List[str]
    x_cols: Optional[List[str]] = None  # default: all numeric columns except y_cols
    top_k: int = 10
    enabled_methods: Optional[List[str]] = None
    corr_threshold: float = 0.85
    vif_threshold: float = 10.0
    per_target: bool = False
    # Generic (default, False): candidate X columns = all numeric columns
    # except the selected Y's, shared across every target.
    # Process-aware (True): for each Y, only columns appearing BEFORE it in
    # the dataset's original column order are eligible candidates — models
    # an upstream-to-downstream process layout where a downstream sensor
    # can't legitimately predict an upstream target.
    process_aware: bool = False


class JobIdResponse(BaseModel):
    job_id: str
