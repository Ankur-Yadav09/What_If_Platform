import { apiClient } from './client'
import type {
  AccuracySummaryResult,
  ColumnOrderRow,
  ConstraintsRow,
  CorrelationMatrixResult,
  DetectedCounts,
  FormulaRow,
  FormulaValidateResult,
  GenerateMappingResult,
  ModelDetailsRow,
  ModelMappingResult,
  MvDvCvTagRow,
  PiMappingRow,
  SectionOrderRow,
  TagOptionsResult,
  TargetSectionResult,
  TrainingDataUploadResult,
  UserInputsRow,
  ValidationFilterCriterion,
  ValidationFilterResult,
  WhatIfConfigStatus,
  WhatIfModelStatus,
  WhatIfScenarioResult,
} from './types'

// ---------------------------------------------------------------------------
// Case setup: config / wizard / model-mapping / model-status
// ---------------------------------------------------------------------------

export async function getConfigStatus(): Promise<WhatIfConfigStatus> {
  const { data } = await apiClient.get<WhatIfConfigStatus>('/what-if/config/status')
  return data
}

export async function getPiMapping(): Promise<PiMappingRow[]> {
  const { data } = await apiClient.get<{ rows: PiMappingRow[] }>('/what-if/config/pi-mapping')
  return data.rows
}

export async function uploadConfig(file: File): Promise<WhatIfConfigStatus> {
  const form = new FormData()
  form.append('file', file)
  // No explicit Content-Type here — axios/the browser must generate it (with
  // the required multipart boundary) from the FormData object itself. Setting
  // 'multipart/form-data' without a boundary produces a malformed request
  // body that FastAPI's multipart parser can't split into fields, which
  // surfaces as a generic "could not parse the workbook" error even though
  // the file itself is fine.
  const { data } = await apiClient.post<WhatIfConfigStatus>('/what-if/config/upload', form)
  return data
}

export async function getDetectedCounts(): Promise<DetectedCounts> {
  const { data } = await apiClient.get<DetectedCounts>('/what-if/wizard/detected-counts')
  return data
}

export interface GenerateMappingRequest {
  cgc_stages: number
  prc_stages: number
  erc_stages: number
  furnaces: number
}

export async function generateMapping(body: GenerateMappingRequest): Promise<GenerateMappingResult> {
  const { data } = await apiClient.post<GenerateMappingResult>('/what-if/wizard/generate-mapping', body)
  return data
}

export async function commitMapping(rows: PiMappingRow[]): Promise<PiMappingRow[]> {
  const { data } = await apiClient.put<{ rows: PiMappingRow[] }>('/what-if/config/mapping', { rows })
  return data.rows
}

export async function getModelMapping(): Promise<ModelMappingResult> {
  const { data } = await apiClient.get<ModelMappingResult>('/what-if/config/model-mapping')
  return data
}

export async function commitModelMapping(rows: ModelDetailsRow[]): Promise<ModelDetailsRow[]> {
  const { data } = await apiClient.put<{ rows: ModelDetailsRow[] }>('/what-if/config/model-mapping', { rows })
  return data.rows
}

// First-Principle rows' Formula Editor (Model Definition) -- one row per
// Predicted Parameter with its math expression. Saving auto-populates that
// row's Input parameter_1..8 in Model details with the formula's referenced
// variable names server-side (see commit_formulas/_sync_formula_inputs in
// backend/app/services/what_if_service.py), so no separate client-side sync
// is needed here.
export async function getFormulas(): Promise<FormulaRow[]> {
  const { data } = await apiClient.get<{ rows: FormulaRow[] }>('/what-if/config/formulas')
  return data.rows
}

export async function commitFormulas(rows: FormulaRow[]): Promise<FormulaRow[]> {
  const { data } = await apiClient.put<{ rows: FormulaRow[] }>('/what-if/config/formulas', { rows })
  return data.rows
}

// Syntax/whitelist-only check (src/whatif/formula_eval.py) -- no historian
// row needed, safe to call on every keystroke (debounced) for live feedback
// before Save.
export async function validateFormula(formula: string): Promise<FormulaValidateResult> {
  const { data } = await apiClient.post<FormulaValidateResult>('/what-if/config/formulas/validate', { formula })
  return data
}

export async function exportConfig(
  piMappingRows: PiMappingRow[],
  modelDetailsRows: ModelDetailsRow[],
  format: 'xlsx' | 'csv',
): Promise<Blob> {
  const { data } = await apiClient.post(
    '/what-if/config/export',
    { pi_mapping_rows: piMappingRows, model_details_rows: modelDetailsRows, format },
    { responseType: 'blob' },
  )
  return data
}

export async function uploadTrainingData(file: File): Promise<TrainingDataUploadResult> {
  const form = new FormData()
  form.append('file', file)
  // See uploadConfig's comment above — no explicit Content-Type for FormData bodies.
  const { data } = await apiClient.post<TrainingDataUploadResult>('/what-if/training-data/upload', form)
  return data
}

export async function getModelsStatus(): Promise<WhatIfModelStatus> {
  const { data } = await apiClient.get<WhatIfModelStatus>('/what-if/models/status')
  return data
}

export async function trainModels(): Promise<string> {
  const { data } = await apiClient.post<{ job_id: string }>('/what-if/models/train')
  return data.job_id
}

export async function getAccuracySummary(): Promise<AccuracySummaryResult> {
  const { data } = await apiClient.get<AccuracySummaryResult>('/what-if/models/accuracy-summary')
  return data
}

// ---------------------------------------------------------------------------
// New config sheets: Section Order, MV/DV/CV taglist, Constraints, User
// Inputs, Column Order, Target Section — same stateless get/commit pattern
// as PI mapping / model mapping above.
// ---------------------------------------------------------------------------

export async function getSectionOrder(): Promise<SectionOrderRow[]> {
  const { data } = await apiClient.get<{ rows: SectionOrderRow[] }>('/what-if/config/section-order')
  return data.rows
}

export async function commitSectionOrder(rows: SectionOrderRow[]): Promise<SectionOrderRow[]> {
  const { data } = await apiClient.put<{ rows: SectionOrderRow[] }>('/what-if/config/section-order', { rows })
  return data.rows
}

export async function getMvDvCvTaglist(): Promise<MvDvCvTagRow[]> {
  const { data } = await apiClient.get<{ rows: MvDvCvTagRow[] }>('/what-if/config/mv-dv-cv-taglist')
  return data.rows
}

export async function commitMvDvCvTaglist(rows: MvDvCvTagRow[]): Promise<MvDvCvTagRow[]> {
  const { data } = await apiClient.put<{ rows: MvDvCvTagRow[] }>('/what-if/config/mv-dv-cv-taglist', { rows })
  return data.rows
}

export async function getConstraints(): Promise<ConstraintsRow[]> {
  const { data } = await apiClient.get<{ rows: ConstraintsRow[] }>('/what-if/config/constraints')
  return data.rows
}

export async function commitConstraints(rows: ConstraintsRow[]): Promise<ConstraintsRow[]> {
  const { data } = await apiClient.put<{ rows: ConstraintsRow[] }>('/what-if/config/constraints', { rows })
  return data.rows
}

export async function getUserInputs(): Promise<UserInputsRow[]> {
  const { data } = await apiClient.get<{ rows: UserInputsRow[] }>('/what-if/config/user-inputs')
  return data.rows
}

export async function commitUserInputs(rows: UserInputsRow[]): Promise<UserInputsRow[]> {
  const { data } = await apiClient.put<{ rows: UserInputsRow[] }>('/what-if/config/user-inputs', { rows })
  return data.rows
}

export async function getColumnOrder(): Promise<ColumnOrderRow[]> {
  const { data } = await apiClient.get<{ rows: ColumnOrderRow[] }>('/what-if/config/column-order')
  return data.rows
}

export async function commitColumnOrder(rows: ColumnOrderRow[]): Promise<ColumnOrderRow[]> {
  const { data } = await apiClient.put<{ rows: ColumnOrderRow[] }>('/what-if/config/column-order', { rows })
  return data.rows
}

export async function getTargetSection(): Promise<TargetSectionResult> {
  const { data } = await apiClient.get<TargetSectionResult>('/what-if/config/target-section')
  return data
}

export async function setTargetSection(targetSection: string | null): Promise<TargetSectionResult> {
  const { data } = await apiClient.put<TargetSectionResult>('/what-if/config/target-section', {
    target_section: targetSection,
  })
  return data
}

export interface SaveConfigRequest {
  pi_mapping_rows: PiMappingRow[]
  model_details_rows: ModelDetailsRow[]
  constraints_rows: ConstraintsRow[]
  user_inputs_rows: UserInputsRow[]
  display_order_rows: ColumnOrderRow[]
  section_order_rows: SectionOrderRow[]
  mvdvcv_rows: MvDvCvTagRow[]
  target_section: string | null
}

export async function saveConfig(body: SaveConfigRequest): Promise<WhatIfConfigStatus> {
  const { data } = await apiClient.post<WhatIfConfigStatus>('/what-if/config/save', body)
  return data
}

/** Downloads all 8 sheets as Config_file.xlsx — the wizard's always-available
 * "Download current configuration" action, distinct from saveConfig (which
 * persists to disk) and MappingPreviewGrid's own lighter export of just the
 * generated PI mapping preview. */
export async function exportFullConfig(body: SaveConfigRequest): Promise<Blob> {
  const { data } = await apiClient.post('/what-if/config/export', { ...body, format: 'xlsx' }, { responseType: 'blob' })
  return data
}

export async function getCorrelationMatrix(): Promise<CorrelationMatrixResult> {
  const { data } = await apiClient.get<CorrelationMatrixResult>('/what-if/config/correlation-matrix')
  return data
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export async function getTagOptions(generatedTags: string[], targetSection?: string | null): Promise<TagOptionsResult> {
  const { data } = await apiClient.post<TagOptionsResult>('/what-if/dashboard/tag-options', {
    generated_tags: generatedTags,
    target_section: targetSection ?? null,
  })
  return data
}

export async function getDates(): Promise<string[]> {
  const { data } = await apiClient.get<{ dates: string[] }>('/what-if/dashboard/dates')
  return data.dates
}

export async function getTimestamps(date: string): Promise<string[]> {
  const { data } = await apiClient.get<{ timestamps: string[] }>('/what-if/dashboard/timestamps', {
    params: { date },
  })
  return data.timestamps
}

export async function getBaseline(timestamp: string, tags: string[]): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get<{ values: Record<string, unknown> }>('/what-if/dashboard/baseline', {
    params: { timestamp, tags: tags.join(',') },
  })
  return data.values
}

export interface RunScenarioRequest {
  timestamp: string
  overrides: { parameter: string; value: number }[]
  write_actual_vs_estimated_xlsx?: boolean
  target_section?: string | null
}

export async function runScenario(body: RunScenarioRequest): Promise<WhatIfScenarioResult> {
  const { data } = await apiClient.post<WhatIfScenarioResult>('/what-if/dashboard/compute', body)
  return data
}

export async function runValidationFilter(
  filters: Record<string, ValidationFilterCriterion>,
  targetSection?: string | null,
): Promise<ValidationFilterResult> {
  const { data } = await apiClient.post<ValidationFilterResult>('/what-if/dashboard/validation-filter', {
    filters,
    target_section: targetSection ?? null,
  })
  return data
}

export async function exportScenarioCsv(
  timestamp: string,
  rows: { parameter: string; actual: unknown; estimated: unknown; change: number | null }[],
  validationRows?: Record<string, unknown>[],
): Promise<Blob> {
  const { data } = await apiClient.post(
    '/what-if/dashboard/export-csv',
    { timestamp, rows, validation_rows: validationRows ?? null },
    { responseType: 'blob' },
  )
  return data
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
