import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { clearModelSelection, deleteModel, getOverview, selectModelForParameter } from '../../api/overview'
import { Callout } from '../../components/Callout'
import type { SavedModelSummary } from '../../api/types'

function fmt(value: number | null): string {
  return value != null ? value.toFixed(3) : '—'
}

// The <details> reveal for X Features needs the FULL list actually visible
// (the table's cells are globally `white-space: nowrap`, see theme.css, so a
// plain clipped/ellipsis span never actually shows everything once
// expanded) — wrap every feature as its own chip so a long list flows onto
// multiple lines instead of being cut off or forcing the table wider than
// the viewport.
function FeatureChipList({ cols }: { cols: string[] }) {
  if (cols.length === 0) return <span className="caption">—</span>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem', maxWidth: 420 }}>
      {cols.map((c) => (
        <span
          key={c}
          className="badge cold"
          style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}
        >
          {c}
        </span>
      ))}
    </div>
  )
}

interface ExperimentRow {
  parameter: string
  model: SavedModelSummary
}

// One row per (parameter, model) pair — a multi-output model (y_cols.length
// > 1) contributes one row per parameter it predicts, since Experiment
// History tracks "by Predicted Parameter (Y)" per the spec, not by model.
// Sorted by parameter then newest-first within a parameter, so experiments
// for the same Y stay adjacent in the single table without needing a
// separate table per group.
function toExperimentRows(models: SavedModelSummary[]): ExperimentRow[] {
  const rows: ExperimentRow[] = []
  for (const m of models) {
    for (const y of m.y_cols) {
      rows.push({ parameter: y, model: m })
    }
  }
  rows.sort((a, b) => {
    const byParam = a.parameter.localeCompare(b.parameter)
    if (byParam !== 0) return byParam
    return a.model.saved_at < b.model.saved_at ? 1 : -1
  })
  return rows
}

// Both an experiment tracking page (compare feature sets/algorithms/accuracy
// across every training run) and the model-selection page for What-If
// Analysis: "Use for What-If Analysis" marks one experiment per Predicted
// Parameter as the model What-If Analysis will actually run — see
// src/whatif/engine.py::predict_and_update_with_soft_sensor_model. Every
// past experiment stays visible for comparison even after a different one
// is selected, until explicitly deleted via the 🗑️ button (which removes
// it everywhere — all its rows here, plus any What-If selection pointing
// at it — since one model can appear under several Predicted Parameters).
export function ExperimentHistoryPage() {
  const queryClient = useQueryClient()
  const overviewQuery = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const [parameterFilter, setParameterFilter] = useState('')

  const selectMutation = useMutation({
    mutationFn: ({ parameter, modelName }: { parameter: string; modelName: string }) =>
      selectModelForParameter(parameter, modelName),
    onSuccess: (data) => queryClient.setQueryData(['overview'], data),
  })
  const clearMutation = useMutation({
    mutationFn: (parameter: string) => clearModelSelection(parameter),
    onSuccess: (data) => queryClient.setQueryData(['overview'], data),
  })
  const deleteMutation = useMutation({
    mutationFn: (modelName: string) => deleteModel(modelName),
    onSuccess: (data) => queryClient.setQueryData(['overview'], data),
  })

  function handleDelete(model: SavedModelSummary) {
    const scopeWarning =
      model.y_cols.length > 1
        ? ` It's used for ${model.y_cols.length} predicted parameters (${model.y_cols.join(', ')}) — all of them will lose this experiment.`
        : ''
    const selectedWarning = model.selected_for.length > 0 ? ' It is currently selected for What-If Analysis — that selection will be cleared.' : ''
    const ok = window.confirm(
      `Permanently delete experiment "${model.name}"? This cannot be undone.${scopeWarning}${selectedWarning}`,
    )
    if (ok) deleteMutation.mutate(model.name)
  }

  if (overviewQuery.isLoading) return <p className="caption">Loading experiment history…</p>
  if (overviewQuery.isError) return <p className="caption">Failed to load experiment history.</p>

  const models: SavedModelSummary[] = overviewQuery.data?.saved_models ?? []
  const allRows = toExperimentRows(models)
  const parameterNames = [...new Set(allRows.map((r) => r.parameter))].sort((a, b) => a.localeCompare(b))
  const rows = parameterFilter ? allRows.filter((r) => r.parameter === parameterFilter) : allRows

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <div>
        <h1>Experiment History</h1>
        <p className="caption">
          Every trained model, one row each. Mark one experiment per Predicted Parameter (Y) "Selected for What-If
          Analysis" — What-If Analysis then uses it automatically, no model choice needed there.
        </p>
      </div>

      {parameterNames.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <label className="caption" htmlFor="experiment-parameter-filter">
            Group by Predicted Parameter (Y)
          </label>
          <select
            id="experiment-parameter-filter"
            value={parameterFilter}
            onChange={(e) => setParameterFilter(e.target.value)}
          >
            <option value="">All parameters ({parameterNames.length})</option>
            {parameterNames.map((parameter) => (
              <option key={parameter} value={parameter}>
                {parameter}
              </option>
            ))}
          </select>
        </div>
      )}

      {rows.length === 0 ? (
        <Callout variant="info">Train a model to see its experiment history here.</Callout>
      ) : (
        <div className="card" style={{ padding: '1.5rem' }}>
          <div className="data-table-scroll" style={{ overflowX: 'auto', maxHeight: 560, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Predicted Parameter (Y)</th>
                  <th>Experiment</th>
                  <th>Algorithm</th>
                  <th>X Features</th>
                  <th>Train R²</th>
                  <th>Train RMSE</th>
                  <th>Train MAE</th>
                  <th>Test R²</th>
                  <th>Test RMSE</th>
                  <th>Test MAE</th>
                  <th>Trained At</th>
                  <th>What-If Analysis</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ parameter, model: m }) => {
                  const isSelected = m.selected_for.includes(parameter)
                  const pending =
                    (selectMutation.isPending && selectMutation.variables?.parameter === parameter) ||
                    (clearMutation.isPending && clearMutation.variables === parameter)
                  const deleting = deleteMutation.isPending && deleteMutation.variables === m.name
                  return (
                    <tr key={`${parameter}::${m.name}`}>
                      <td>{parameter}</td>
                      <td>
                        <code>{m.name}</code>
                      </td>
                      <td>{m.algorithm ?? '—'}</td>
                      <td style={{ whiteSpace: 'normal' }}>
                        <details>
                          <summary style={{ cursor: 'pointer', whiteSpace: 'nowrap' }}>
                            {m.x_cols.length} feature(s)
                          </summary>
                          <div style={{ marginTop: '0.5rem' }}>
                            <FeatureChipList cols={m.x_cols} />
                          </div>
                        </details>
                      </td>
                      <td>{fmt(m.train_r2)}</td>
                      <td>{fmt(m.train_rmse)}</td>
                      <td>{fmt(m.train_mae)}</td>
                      <td>{fmt(m.avg_r2)}</td>
                      <td>{fmt(m.avg_rmse)}</td>
                      <td>{fmt(m.avg_mae)}</td>
                      <td>{m.saved_at}</td>
                      <td>
                        {isSelected ? (
                          <span
                            className="pill active"
                            style={{ cursor: 'pointer' }}
                            title="Click to un-select and revert to the dedicated Kalman model"
                            onClick={() => !pending && clearMutation.mutate(parameter)}
                          >
                            ✓ Selected for What-If Analysis
                          </span>
                        ) : (
                          <button
                            className="chip"
                            disabled={pending}
                            onClick={() => selectMutation.mutate({ parameter, modelName: m.name })}
                          >
                            Use for What-If Analysis
                          </button>
                        )}
                      </td>
                      <td>
                        <button
                          className="chip"
                          disabled={deleting}
                          title="Permanently delete this experiment"
                          onClick={() => handleDelete(m)}
                        >
                          {deleting ? 'Deleting…' : '🗑️ Delete'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
