export interface DatasetSummary {
  name: string
  uploaded_at: string
  rows: number
  cols: number
  plant?: string | null
  unit?: string | null
  status?: string
}

export interface DatasetPreview {
  name: string
  shape: [number, number]
  columns: string[]
  head: Record<string, unknown>[]
}

export interface SavedModelSummary {
  name: string
  saved_at: string
  input_dim: number
  output_dim: number
  algorithm: string | null
  dataset_name: string | null
  avg_r2: number | null
  avg_rmse: number | null
  avg_mae: number | null
  train_r2: number | null
  train_rmse: number | null
  train_mae: number | null
  x_cols: string[]
  y_cols: string[]
  selected_for: string[]
}

export interface OverviewResponse {
  datasets: DatasetSummary[]
  saved_models: SavedModelSummary[]
}

export interface FeatureStat {
  Feature: string
  'Missing Count': number
  'Missing %': number
  Min: number | null
  Mean: number | null
  Max: number | null
}

export interface ProjectSummary {
  project_id: string
  dataset_name: string
  x_cols: string[]
  y_cols: string[]
  created_at: string
  n_train: number
  n_test: number
  config: Record<string, unknown>
}

export interface ApplyPreprocessingResponse {
  project_id: string
  dataset_name: string
  x_cols: string[]
  y_cols: string[]
  n_train: number
  n_test: number
}

export interface JobStatus {
  id: string
  status: 'pending' | 'running' | 'done' | 'error'
  progress: { current?: number; total?: number; message?: string }
  error: string | null
  done: boolean
  result: unknown
}

export interface FeatureConsensusRow {
  Rank: number
  Feature: string
  FinalScore: number
  PredictiveStrength: number
  StabilityScore: number
  SelectionFreq: number
  VIF: number | null
  CorrWithTarget: number | null
  Recommendation: string
  ElasticNetSelected: boolean | null
  MulticollinearWith?: string | null
}

export interface MethodResultOut {
  name: string
  method_id: string
  category: string
  selected_features: string[]
  notes: string
  success: boolean
  raw_scores: Record<string, number>
  all_scores: Record<string, number>
  per_target_scores: Record<string, Record<string, number>>
}

export interface FeatureSelectionResult {
  mode: 'combined' | 'per_target'
  consensus: FeatureConsensusRow[]
  recommended_features: string[]
  optional_features: string[]
  features_to_remove: string[]
  per_feature_reasoning: Record<string, string>
  dataset_info: {
    n_rows: number
    n_raw_features: number
    n_clean_features: number
    n_targets: number
    target_names: string[]
    constant_features: string[]
    missing_pct_x: number
    missing_pct_y: number
    vif_skipped?: boolean
    permutation_skipped?: boolean
  }
  method_results: MethodResultOut[]
  vif: { Feature: string; VIF: number | null; VIF_Level: string }[]
  corr_with_target: Record<string, unknown>[]
  feature_target_map?: Record<string, string[]>
  per_target_summary?: Record<string, { recommended_features: string[]; optional_features: string[] }>
}

export interface FeatureDetail {
  column: string
  empty: boolean
  dtype?: string
  distribution_label?: string
  n_total: number
  n_missing: number
  n_unique?: number
  n_duplicate_rows?: number
  n_outliers_iqr?: number
  mean?: number
  median?: number
  std?: number
  min?: number
  max?: number
  skew?: number
  kurtosis?: number
  histogram?: { counts: number[]; bin_edges: number[] }
  boxplot?: { min: number; q1: number; median: number; q3: number; max: number }
}

export interface TrainingResult {
  model_name: string
  algorithm: string
  avg_r2: number
  avg_rmse: number
  avg_mae: number
  train_r2: number
  train_rmse: number
  train_mae: number
  actual_epochs: number | null
  early_stopped: boolean
  epoch_recon_losses: number[]
  epoch_pred_losses: number[]
  val_recon_losses: number[]
  val_pred_losses: number[]
}

// ---------------------------------------------------------------------------
// What-If Analysis module
// ---------------------------------------------------------------------------

export interface WhatIfCase {
  case_id: string
  name: string
  created_at: string
  last_opened_at: string
}

export interface WhatIfConfigStatus {
  pi_mapping_present: boolean
  pi_mapping_row_count: number
  model_details_present: boolean
  model_details_row_count: number
  source_path: string | null
}

export interface PiMappingRow {
  Pi_tags: string
  'Generalized Description': string
  Section: string
}

export interface ModelDetailsRow {
  'Predicted parameter': string
  [key: string]: string | undefined
}

export interface DetectedCounts {
  cgc_max: number
  prc_max: number
  erc_max: number
  furnace_max: number
}

export interface GenerateMappingResult {
  rows: PiMappingRow[]
  section_counts: Record<string, number>
  wizard_selection: Record<string, unknown>
}

export interface ModelMappingResult {
  rows: ModelDetailsRow[]
  historian_tags: string[]
}

export interface FormulaRow {
  'Predicted parameter': string
  Formula: string
}

export interface FormulaValidateResult {
  valid: boolean
  errors: string[]
  variables: string[]
}

export interface TrainingDataUploadResult {
  saved: boolean
  sheets_found: string[]
  missing_sheets: string[]
}

export interface WhatIfModelStatus {
  all_present: boolean
  tags_ok: string[]
  tags_missing: string[]
  pkl_count: number
  required_pkl_count: number
  raw_sim_present: boolean
  training_data_present: boolean
  model_mapping_filled: boolean
  can_train: boolean
  train_blockers: string[]
  training_required: boolean
}

export interface WhatIfTrainResult {
  success: boolean
  returncode: number
  stdout_tail: string
  stderr_tail: string
  pkl_count: number
  all_present: boolean
  raw_sim_present: boolean
}

export interface TagOptionsResult {
  tags: string[]
  all_tags: string[]
  source: 'wizard' | 'config' | 'historian'
  limits: Record<string, { lower: number; upper: number }>
}

export interface WhatIfScenarioRow {
  parameter: string
  actual: unknown
  estimated: unknown
  change: number | null
}

export interface WhatIfKpi {
  tag: string
  actual: number
  estimated: number
  change: number
}

export interface WhatIfScenarioResult {
  constraint_hit: boolean
  constraint_message: string | null
  rows: WhatIfScenarioRow[]
  kpis: WhatIfKpi[]
}

export interface ValidationFilterCriterion {
  min?: number | null
  max?: number | null
  values?: unknown[] | null
}

export interface ValidationFilterResult {
  rows: Record<string, unknown>[]
  match_count: number
}

export interface SectionOrderRow {
  'Sr.no': number | string
  Section: string
}

export interface MvDvCvTagRow {
  Name: string
  GeneralizedDescription: string
  Section: string
  Type: string
}

export interface ConstraintsRow {
  Parameter: string
  'user input value': number | string
  'Max vlaue'?: number | string
  'Max value'?: number | string
  UOM?: string
  Remark?: string
  'Linked Parameter'?: string
  Action?: string
}

export interface UserInputsRow {
  Parameter: string
  Value?: number | string
  'Lower Limit'?: number | string
  'Upper Limit'?: number | string
  Remark?: string
}

export interface ColumnOrderRow {
  'Sr.no': number | string
  'Preferred columns': string
}

export interface TargetSectionResult {
  section_order: string[]
  target_section: string | null
  active_scope: string[]
  excluded_sections: string[]
}

export interface CorrelationMatrixResult {
  columns: string[]
  matrix: (number | null)[][]
  n_rows: number
}

export interface AccuracySummaryResult {
  rows: Record<string, unknown>[]
  available: boolean
}
