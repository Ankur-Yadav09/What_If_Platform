import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitModelMapping, getModelMapping } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { EditableComboBox } from '../../components/EditableComboBox'
import { inSectionScope, modelInputOptionsForSection, optionsWithCurrentValue } from './caseSetupHelpers'
import { useTouchedRowIndices } from './useTouchedRowIndices'
import { SECTION_OPTIONS } from './whatIfConstants'
import type { ModelDetailsRow, MvDvCvTagRow, PiMappingRow, SavedModelSummary } from '../../api/types'

// Exported so ModelConfigTab.tsx (Accept) and ExperimentHistoryPage.tsx (Use
// for What-If Analysis) can write a model's X features into these exact
// backend column names — see MODEL_DETAILS_COLUMNS in
// src/whatif/config_io.py (a fixed 8-slot schema; there's no room for more
// than INPUT_COLS.length features).
export const INPUT_COLS = Array.from({ length: 8 }, (_, i) => `Input parameter_${i + 1}`)

// Writes a model's X features into its Predicted Parameter's own Input
// parameter_1..8 cells (truncated to INPUT_COLS.length) so Model Definition
// reflects them without the user re-entering anything. Blanks any slots
// beyond xCols.length so re-syncing with fewer features doesn't leave stale
// tags behind from a previous model. Used both when Build Model's guided
// loop accepts a model and when Experimentation picks a different one for
// an already-configured parameter.
//
// If no row for targetY exists yet -- e.g. the model was trained directly
// from Build Model without going through Model Definition's "Configure
// Model" first, so Feature Discovery's target-Y picker was never locked to
// an existing row -- a new Data-model row (the default model type, see
// isDataModelRow) is appended instead of silently doing nothing. Otherwise
// a What-If Analysis selection for that parameter would be a dead entry:
// the engine's dependency graph is built purely from Model Definition rows,
// so a parameter absent there never runs at all.
export function withSyncedInputs(rows: ModelDetailsRow[], targetY: string, xCols: string[]): ModelDetailsRow[] {
  const trimmed = xCols.slice(0, INPUT_COLS.length)
  const inputs = Object.fromEntries(INPUT_COLS.map((col, i) => [col, trimmed[i] ?? '']))
  const matched = rows.some((r) => (r['Predicted parameter'] ?? '').toString().trim() === targetY)
  const synced = rows.map((r) =>
    (r['Predicted parameter'] ?? '').toString().trim() === targetY ? { ...r, ...inputs } : r,
  )
  return matched ? synced : [...synced, { 'Predicted parameter': targetY, Section: '', ...inputs }]
}
const STICKY_COL_WIDTH = 200
// Matches src/whatif/config_io.py::_is_data_model() exactly: blank/"Data
// model" is Kalman/Soft-Sensor-driven (the default); anything else — here,
// "First principle" — is simulation-owned. A First-Principle parameter's
// value comes from the plant physics plugin (src/whatif/plants/
// yanpet_olf1_formulas.py, matching Scripts/yanpet_olf1_formulas.py's HOOKS/
// SIMULATION contract) instead of a trained model — the engine skips Kalman/
// Soft-Sensor prediction for it entirely (src/whatif/engine.py::whatif_analysis).
const MODEL_TYPE_OPTIONS = ['', 'Data model', 'First principle']

// Same rule as src/whatif/config_io.py::_is_data_model() — only Data-model
// (or blank, the default) rows go through the AI Feature Discovery/Build
// Model pipeline; First-Principle rows have nothing to configure there.
export function isDataModelRow(row: ModelDetailsRow): boolean {
  const t = (row['model type'] ?? '').toString().trim().toLowerCase()
  return t === '' || t === 'data model'
}

// Every Saved Model whose y_cols includes this row's Predicted parameter
// (exact, trimmed string match — there's no foreign key between this
// free-typed field and Experiment History's y_cols today).
function matchesForRow(param: string, savedModels: SavedModelSummary[]): SavedModelSummary[] {
  if (!param) return []
  return savedModels.filter((m) => m.y_cols.some((y) => y.trim() === param))
}

// The one experiment "Selected for What-If Analysis" for this Predicted
// Parameter (server enforces at most one). Accepting a model in Build
// Model's guided loop always selects it (see ModelConfigTab.tsx), so this
// alone is "Model Ready" — no separate client-side acceptance tracking.
export function findSelectedModel(param: string, savedModels: SavedModelSummary[]): SavedModelSummary | undefined {
  if (!param) return undefined
  return savedModels.find((m) => m.y_cols.some((y) => y.trim() === param) && m.selected_for.includes(param))
}

function FeatureChipList({ cols }: { cols: string[] }) {
  if (cols.length === 0) return <span className="caption">—</span>
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', maxWidth: 320 }}>
      {cols.map((c) => (
        <span key={c} className="badge cold" style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>
          {c}
        </span>
      ))}
    </div>
  )
}

// The highest input-column index actually filled on this one row (0 if
// none) — each row now discloses/expands its own input slots independently
// (see rowVisibleInputCounts), rather than one shared column count driving
// every row's width at once.
function filledInputCountForRow(row: ModelDetailsRow): number {
  for (let i = INPUT_COLS.length; i >= 1; i--) {
    if ((row[INPUT_COLS[i - 1]] ?? '').toString().trim()) return i
  }
  return 0
}

interface ModelMappingEditorProps {
  /** Restricts which rows are shown/editable to those in-scope. Omit for
   * the unscoped, full-sheet view used outside the wizard. */
  allowed?: Set<string>
  /** Raw PI tag dictionary and MV/DV/CV tag list — used to compute each
   * row's own Input dropdown options. MV/DV/CV tags whose Section matches
   * the row's chosen Section (or is upstream of it) are bumped to the top
   * as prioritized choices; every other tag still follows — nothing is
   * ever hidden from the dropdown, only reordered. Falls back to the full
   * historian tag list when omitted entirely. */
  piRows?: PiMappingRow[]
  mvdvcvRows?: MvDvCvTagRow[]
  sectionOptions?: string[]
  /** The plant's process-flow order (e.g. Furnace/Quench/CGC/PRC/ERC/Cold),
   * used to resolve "upstream of this row's Section" for prioritizing its
   * Input dropdown. Without it, only an exact Section match is prioritized. */
  sectionOrder?: string[]
  /** Every trained experiment (from GET /overview), used to show each row's
   * Status/Model-Ready state without any new backend field — matched
   * against 'Predicted parameter' by exact string. The row's actual
   * Input parameter_1..8 values (not this prop) are the source of truth for
   * what's displayed as its X features — see findSelectedModel/INPUT_COLS. */
  savedModels?: SavedModelSummary[]
  /** Suggested values for "Predicted parameter" (typically the active
   * dataset's numeric columns, plus any name already used by a saved
   * experiment or existing row) — shown via EditableComboBox's click-to-open
   * dropdown so the field stays free-text (First-Principle rows aren't
   * necessarily real dataset columns) while still offering a real,
   * click-visible list of known-good names (not a <datalist>, which most
   * browsers only reveal once you start typing). */
  predictedParameterOptions?: string[]
  /** Drives a row into the guided AI Feature Discovery -> Build Model loop
   * for its Predicted parameter. Omitted (or the row isn't a Data model, or
   * has no name yet) -> no "Configure Model" action shown. */
  onConfigureModel?: (predictedParameter: string) => void
  /** Opens the Formula Editor for a First-Principle row's Predicted
   * parameter. Omitted (or the row is a Data model, or has no name yet) ->
   * no "Define Formula" action shown -- mirrors onConfigureModel's gating,
   * just for the opposite Model Type. */
  onDefineFormula?: (predictedParameter: string) => void
}

// Case Setup wizard Step 7: maps each predicted parameter to its Section and
// its ordered input feature tags. Rows outside the active scope stay in the
// dataset untouched, just hidden from view (see `allowed`). Each row's Input
// dropdowns prioritize tags matching its own Section (see modelInputOptionsForSection) —
// choosing a Section moves matching MV/DV/CV tags to the top; every tag is
// still selectable either way, nothing is hidden.
export function ModelMappingEditor({
  allowed,
  piRows,
  mvdvcvRows,
  sectionOptions,
  sectionOrder,
  savedModels,
  predictedParameterOptions,
  onConfigureModel,
  onDefineFormula,
}: ModelMappingEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-model-mapping'], queryFn: getModelMapping })
  const [rows, setRows] = useState<ModelDetailsRow[]>([])
  const { touched, markTouched, onRowRemoved } = useTouchedRowIndices()
  // Per-row "how many of the 8 input slots are expanded" -- defaults to
  // however many are actually filled (at least 1) the first time a row is
  // expanded; "+ Add Input" inside that row's disclosure reveals one more.
  // Keyed by row index, re-indexed on removeRow same as useTouchedRowIndices.
  const [rowVisibleInputCounts, setRowVisibleInputCounts] = useState<Record<number, number>>({})

  useEffect(() => {
    if (query.data) setRows(query.data.rows)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitModelMapping,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-model-mapping'], { rows: result, historian_tags: query.data?.historian_tags ?? [] })
    },
  })

  if (query.isLoading) return <p className="caption">Loading model mapping…</p>

  const fallbackOptions = query.data?.historian_tags ?? []
  function inputOptionsForRow(row: ModelDetailsRow): string[] {
    if (!piRows) return fallbackOptions
    return modelInputOptionsForSection(piRows, mvdvcvRows ?? [], row.Section, sectionOrder ?? [])
  }
  const sectionChoices = sectionOptions ?? SECTION_OPTIONS

  function visibleInputCountForRow(i: number): number {
    return rowVisibleInputCounts[i] ?? Math.max(1, filledInputCountForRow(rows[i]))
  }

  function expandRowInputs(i: number) {
    setRowVisibleInputCounts((prev) => ({
      ...prev,
      [i]: Math.min(INPUT_COLS.length, visibleInputCountForRow(i) + 1),
    }))
  }

  const visibleIndices = rows
    .map((_, i) => i)
    .filter(
      (i) => !allowed || touched.has(i) || inSectionScope(rows[i].Section, allowed, rows[i]['Predicted parameter']),
    )
  const hiddenCount = rows.length - visibleIndices.length

  function updateCell(index: number, col: string, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [col]: value }
    setRows(next)
    markTouched(index)
  }

  function addRow() {
    setRows([...rows, { 'Predicted parameter': '', Section: '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
    onRowRemoved(index)
    setRowVisibleInputCounts((prev) => {
      const next: Record<number, number> = {}
      for (const [key, value] of Object.entries(prev)) {
        const k = Number(key)
        if (k === index) continue
        next[k > index ? k - 1 : k] = value
      }
      return next
    })
  }

  return (
    <div>
      <p className="caption">
        Maps each predicted parameter to its Section and the ordered input feature tags its Kalman model consumes.
        "Predicted parameter" stays pinned on the left; input dropdowns list MV/DV/CV tags first, then the remaining
        scoped PI tags.
      </p>
      {rows.length === 0 && (
        <Callout variant="info">No predicted parameters yet — click "+ Add Parameter" below to add one.</Callout>
      )}
      <div className="data-table-scroll" style={{ overflowX: 'auto' }}>
        <table className="table-compact" style={{ tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th className="sticky-col" style={{ minWidth: STICKY_COL_WIDTH, width: STICKY_COL_WIDTH }}>
                Predicted parameter
              </th>
              <th style={{ width: 130 }}>Section</th>
              <th style={{ width: 150 }}>Model Type</th>
              <th style={{ width: 260 }}>Inputs</th>
              <th style={{ width: 150 }}>Status</th>
              <th style={{ width: 150 }} />
            </tr>
          </thead>
          <tbody>
            {visibleIndices.map((i) => {
              const rowInputOptions = inputOptionsForRow(rows[i])
              const param = (rows[i]['Predicted parameter'] ?? '').toString().trim()
              const matches = matchesForRow(param, savedModels ?? [])
              const selectedModel = findSelectedModel(param, savedModels ?? [])
              // The row's own persisted values are the source of truth for
              // display (what's actually in the config file/backend), not
              // selectedModel.x_cols directly -- these can differ if the
              // model has more X features than INPUT_COLS.length (8), since
              // only the first 8 get written on Accept (see ModelConfigTab).
              const filledInputs = INPUT_COLS.map((c) => (rows[i][c] ?? '').toString().trim()).filter(Boolean)
              const truncated = !!selectedModel && selectedModel.x_cols.length > INPUT_COLS.length
              const canConfigure = !!param && isDataModelRow(rows[i]) && !!onConfigureModel
              const canDefineFormula = !!param && !isDataModelRow(rows[i]) && !!onDefineFormula
              return (
              <tr key={i}>
                <td className="sticky-col" style={{ minWidth: STICKY_COL_WIDTH, verticalAlign: 'middle' }}>
                  <EditableComboBox
                    value={rows[i]['Predicted parameter']}
                    onChange={(next) => updateCell(i, 'Predicted parameter', next)}
                    options={predictedParameterOptions ?? []}
                  />
                </td>
                <td style={{ verticalAlign: 'middle' }}>
                  <select
                    value={rows[i].Section ?? ''}
                    onChange={(e) => updateCell(i, 'Section', e.target.value)}
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  >
                    {sectionChoices.map((s) => (
                      <option key={s} value={s}>
                        {s || '—'}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ verticalAlign: 'middle' }}>
                  <select
                    value={rows[i]['model type'] ?? ''}
                    onChange={(e) => updateCell(i, 'model type', e.target.value)}
                    style={{ width: '100%', boxSizing: 'border-box' }}
                  >
                    {MODEL_TYPE_OPTIONS.map((t) => (
                      <option key={t} value={t}>
                        {t || '—'}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ verticalAlign: 'middle' }}>
                  {selectedModel ? (
                    <>
                      <FeatureChipList cols={filledInputs} />
                      {truncated && (
                        <p className="caption" style={{ marginTop: '0.3rem' }}>
                          Showing {filledInputs.length} of {selectedModel.x_cols.length} features — up to{' '}
                          {INPUT_COLS.length} supported.
                        </p>
                      )}
                    </>
                  ) : (
                    <details>
                      <summary style={{ cursor: 'pointer' }}>
                        {filledInputs.length === 0
                          ? '+ Add Input'
                          : `${filledInputs.length} of ${INPUT_COLS.length} input${filledInputs.length === 1 ? '' : 's'} — edit`}
                      </summary>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.5rem' }}>
                        {INPUT_COLS.slice(0, visibleInputCountForRow(i)).map((c, idx) => (
                          <label key={c} style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                            <span className="caption">In {idx + 1}</span>
                            <select
                              value={rows[i][c] ?? ''}
                              onChange={(e) => updateCell(i, c, e.target.value)}
                              title={rows[i][c] || undefined}
                              style={{ width: '100%', boxSizing: 'border-box' }}
                            >
                              <option value="">—</option>
                              {optionsWithCurrentValue(rowInputOptions, rows[i][c]).map((t) => (
                                <option key={t} value={t}>
                                  {t}
                                </option>
                              ))}
                            </select>
                          </label>
                        ))}
                        {visibleInputCountForRow(i) < INPUT_COLS.length && (
                          <button className="chip" onClick={() => expandRowInputs(i)}>
                            + Add Input (In {visibleInputCountForRow(i) + 1})
                          </button>
                        )}
                      </div>
                    </details>
                  )}
                </td>
                <td style={{ verticalAlign: 'middle' }}>
                  {selectedModel ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                      <span className="pill active">✓ Model Ready</span>
                      <span className="caption">{selectedModel.algorithm ?? '—'}</span>
                    </div>
                  ) : matches.length > 0 ? (
                    <span className="pill">Trained, not selected</span>
                  ) : (
                    <span className="pill">Not configured</span>
                  )}
                </td>
                <td style={{ verticalAlign: 'middle' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                    {canConfigure && (
                      <button
                        disabled={commitMutation.isPending}
                        title={
                          selectedModel
                            ? 'Saves the model mapping, then reopens AI Feature Discovery to improve this parameter'
                            : 'Saves the model mapping, then opens AI Feature Discovery for this parameter'
                        }
                        onClick={() => commitMutation.mutate(rows, { onSuccess: () => onConfigureModel!(param) })}
                        style={{ width: '100%', padding: '0.45rem 0.6rem', fontSize: '0.82rem' }}
                      >
                        {selectedModel ? 'Reconfigure →' : 'Configure Model →'}
                      </button>
                    )}
                    {canDefineFormula && (
                      <button
                        disabled={commitMutation.isPending}
                        title="Saves the model mapping, then opens the Formula Editor for this parameter"
                        onClick={() => commitMutation.mutate(rows, { onSuccess: () => onDefineFormula!(param) })}
                        style={{ width: '100%', padding: '0.45rem 0.6rem', fontSize: '0.82rem' }}
                      >
                        Define Formula →
                      </button>
                    )}
                    <button
                      className="chip"
                      onClick={() => removeRow(i)}
                      style={{ width: '100%', padding: '0.4rem 0.6rem', fontSize: '0.82rem' }}
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {hiddenCount > 0 && (
        <p className="caption" style={{ marginTop: '0.5rem' }}>
          Active scope only — {hiddenCount} downstream model(s) hidden here.
        </p>
      )}
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Parameter
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save Model Mapping</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">Model mapping updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
