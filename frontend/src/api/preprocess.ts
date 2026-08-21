import { apiClient } from './client'
import type {
  ApplyPreprocessingResponse,
  CorrelationMatrixResult,
  FeatureDetail,
  FeatureStat,
  ProjectSummary,
} from './types'

export async function getFeatureStats(datasetName: string): Promise<FeatureStat[]> {
  const { data } = await apiClient.get<{ stats: FeatureStat[] }>(
    `/preprocess/${encodeURIComponent(datasetName)}/stats`,
  )
  return data.stats
}

// Pearson correlation over the dataset currently active in Connect Data —
// distinct from What-If Studio's own getCorrelationMatrix() in api/whatIf.ts,
// which reads the separate, case-scoped training workbook instead.
export async function getCorrelationMatrix(datasetName: string): Promise<CorrelationMatrixResult> {
  const { data } = await apiClient.get<CorrelationMatrixResult>(
    `/preprocess/${encodeURIComponent(datasetName)}/correlation-matrix`,
  )
  return data
}

// Same matrix as getCorrelationMatrix(), as a colored .xlsx (green > 0.4,
// red < -0.4 cell fills) — a plain CSV can't carry cell colors, only this
// server-rendered workbook can (see preprocess_service.py's Styler.map).
export async function exportCorrelationMatrix(datasetName: string): Promise<Blob> {
  const { data } = await apiClient.get(`/preprocess/${encodeURIComponent(datasetName)}/correlation-matrix/export`, {
    responseType: 'blob',
  })
  return data
}

export async function getFeatureDetail(datasetName: string, column: string): Promise<FeatureDetail> {
  const { data } = await apiClient.get<FeatureDetail>(
    `/preprocess/${encodeURIComponent(datasetName)}/feature-detail`,
    { params: { column } },
  )
  return data
}

export interface DomainFilterBounds {
  min: number
  max: number
}

export interface BasicCleaningRequest {
  dataset_name: string
  new_dataset_name?: string
  remove_missing_rows?: boolean
  remove_duplicates?: boolean
  remove_missing_cols?: boolean
  missing_col_threshold?: number
  remove_constant_cols?: boolean
  remove_nzv_cols?: boolean
  nzv_threshold?: number
  impute_method?: string
  impute_cols?: string[]
  custom_fill_value?: number
  outlier_method?: string
  outlier_cols?: string[]
  zscore_threshold?: number
  winsor_lo?: number
  winsor_hi?: number
  cap_multiplier?: number
  domain_filters?: Record<string, DomainFilterBounds>
}

export interface CleaningResponse {
  new_dataset_name: string
  before_rows: number
  after_rows: number
  before_cols?: number
  after_cols: number
  action_log?: string[]
  step_log?: string[]
}

export async function applyBasicCleaning(body: BasicCleaningRequest): Promise<CleaningResponse> {
  const { data } = await apiClient.post<CleaningResponse>('/preprocess/clean', body)
  return data
}

export async function applyAutomatedCleaning(
  datasetName: string,
  newDatasetName?: string,
): Promise<CleaningResponse> {
  const { data } = await apiClient.post<CleaningResponse>('/preprocess/automated', {
    dataset_name: datasetName,
    new_dataset_name: newDatasetName,
  })
  return data
}

export interface ApplyPreprocessingRequest {
  dataset_name: string
  x_cols: string[]
  y_cols: string[]
  imputation_method: string
  outlier_method: string
  split_method: string
  test_size: number
  stratify_bins?: number
}

export async function applyPreprocessing(
  body: ApplyPreprocessingRequest,
): Promise<ApplyPreprocessingResponse> {
  const { data } = await apiClient.post<ApplyPreprocessingResponse>('/preprocess/apply', body)
  return data
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const { data } = await apiClient.get<ProjectSummary[]>('/projects')
  return data
}
