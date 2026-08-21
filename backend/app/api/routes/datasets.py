from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Form, Query, UploadFile

from backend.app.schemas.datasets import DatasetListResponse, DatasetPreview, DatasetSummary
from backend.app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/upload", response_model=DatasetSummary, status_code=201)
async def upload_dataset(
    file: UploadFile,
    dataset_name: Optional[str] = Form(None),
    plant: Optional[str] = Form(None),
    unit: Optional[str] = Form(None),
    case_id: str = Query("default"),
) -> DatasetSummary:
    return await dataset_service.upload_dataset(
        file, dataset_name=dataset_name, plant=plant, unit=unit, case_id=case_id
    )


@router.get("", response_model=DatasetListResponse)
def list_datasets(case_id: str = Query("default")) -> DatasetListResponse:
    return DatasetListResponse(datasets=dataset_service.list_datasets(case_id))


@router.get("/{name}/preview", response_model=DatasetPreview)
def get_dataset_preview(name: str, case_id: str = Query("default")) -> DatasetPreview:
    return dataset_service.get_dataset_preview(name, case_id)


@router.delete("/{name}", status_code=204)
def delete_dataset(name: str, case_id: str = Query("default")) -> None:
    dataset_service.delete_dataset(name, case_id)
