import { apiClient } from './client'

export interface FeatureSelectionRequest {
  dataset_name: string
  y_cols: string[]
  x_cols?: string[]
  top_k: number
  corr_threshold: number
  vif_threshold: number
  per_target: boolean
  process_aware: boolean
  /** Which of the 5 core scoring methods to run — omit (undefined) to let
   * the backend auto-select its own default subset (see
   * src/feature_selection/auto_selector.py's enabled_methods docstring:
   * "None = auto-select"). The Configure pathway's "Methods Selection" tab
   * sends this explicitly; Automated intentionally leaves it unset. */
  enabled_methods?: string[]
}

export async function submitFeatureSelection(body: FeatureSelectionRequest): Promise<string> {
  const { data } = await apiClient.post<{ job_id: string }>('/feature-selection/jobs', body)
  return data.job_id
}
