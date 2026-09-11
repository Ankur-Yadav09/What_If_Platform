import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { applyBasicCleaning } from '../../api/preprocess'
import { Callout } from '../../components/Callout'
import { SectionBanner } from '../../components/SectionBanner'
import { Tabs } from '../../components/Tabs'
import type { FeatureStat } from '../../api/types'
import type { CleaningResponse } from '../../api/preprocess'

const IMPUTE_METHODS = ['Mean', 'Median', 'Forward Fill', 'Backward Fill', 'Custom Value']
const OUTLIER_METHODS = [
  'IQR Capping',
  'Z-Score Capping',
  'Winsorization',
  'Capping/Flooring (custom IQR multiplier)',
  'Remove Outliers (IQR)',
  'Remove Outliers (Z-Score)',
]

interface BasicPreprocessingTabProps {
  datasetName: string
  numericCols: string[]
  stats: FeatureStat[]
  onCleaned: (result: CleaningResponse) => void
}

interface DomainFilterRow {
  id: string
  tag: string
  min: number | ''
  max: number | ''
}

interface ImputeRuleRow {
  id: string
  tag: string
  method: string
  customFillValue: number
}

interface OutlierRuleRow {
  id: string
  tag: string
  method: string
  zscoreThreshold: number
  winsorLo: number
  winsorHi: number
  capMultiplier: number
}

function clampPct(v: number | ''): number | '' {
  if (v === '' || Number.isNaN(v)) return ''
  return Math.min(100, Math.max(0, v))
}

export function BasicPreprocessingTab({ datasetName, numericCols, stats, onCleaned }: BasicPreprocessingTabProps) {
  const queryClient = useQueryClient()

  // --- Remove Records/Columns ---
  const [removeMissingRows, setRemoveMissingRows] = useState(false)
  const [removeDuplicates, setRemoveDuplicates] = useState(false)
  const [removeMissingCols, setRemoveMissingCols] = useState(false)
  const [missingColThreshold, setMissingColThreshold] = useState<number | ''>('')
  const [removeConstantCols, setRemoveConstantCols] = useState(false)
  const [removeCvOutlierCols, setRemoveCvOutlierCols] = useState(false)
  const [cvLowThreshold, setCvLowThreshold] = useState<number | ''>('')
  const [cvHighThreshold, setCvHighThreshold] = useState<number | ''>('')

  // --- Missing Value Imputation ---
  const [imputeRows, setImputeRows] = useState<ImputeRuleRow[]>([])
  const nextImputeRowId = useRef(0)

  // --- Outlier Detection ---
  const [outlierRows, setOutlierRows] = useState<OutlierRuleRow[]>([])
  const nextOutlierRowId = useRef(0)

  // --- Domain Filters (Min–Max Filter) ---
  const [filterRows, setFilterRows] = useState<DomainFilterRow[]>([])
  const nextRowId = useRef(0)

  const statsByFeature = Object.fromEntries(stats.map((s) => [s.Feature, s]))

  function addFilterRow() {
    setFilterRows((prev) => [...prev, { id: `row-${nextRowId.current++}`, tag: '', min: '', max: '' }])
  }

  function removeFilterRow(id: string) {
    setFilterRows((prev) => prev.filter((r) => r.id !== id))
  }

  function updateFilterRow(id: string, patch: Partial<DomainFilterRow>) {
    setFilterRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  function selectFilterTag(id: string, tag: string) {
    const s = statsByFeature[tag]
    updateFilterRow(id, {
      tag,
      min: s ? (s.Min ?? '') : '',
      max: s ? (s.Max ?? '') : '',
    })
  }

  function addImputeRow() {
    setImputeRows((prev) => [
      ...prev,
      { id: `impute-row-${nextImputeRowId.current++}`, tag: '', method: 'Mean', customFillValue: 0 },
    ])
  }

  function removeImputeRow(id: string) {
    setImputeRows((prev) => prev.filter((r) => r.id !== id))
  }

  function updateImputeRow(id: string, patch: Partial<ImputeRuleRow>) {
    setImputeRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  function addOutlierRow() {
    setOutlierRows((prev) => [
      ...prev,
      {
        id: `outlier-row-${nextOutlierRowId.current++}`,
        tag: '',
        method: 'IQR Capping',
        zscoreThreshold: 3.0,
        winsorLo: 2.5,
        winsorHi: 97.5,
        capMultiplier: 1.5,
      },
    ])
  }

  function removeOutlierRow(id: string) {
    setOutlierRows((prev) => prev.filter((r) => r.id !== id))
  }

  function updateOutlierRow(id: string, patch: Partial<OutlierRuleRow>) {
    setOutlierRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  const cleanMutation = useMutation({
    mutationFn: applyBasicCleaning,
    onSuccess: (res) => {
      onCleaned(res)
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  const activeFilterRows = filterRows.filter((r) => r.tag)
  const activeImputeRows = imputeRows.filter((r) => r.tag)
  const activeOutlierRows = outlierRows.filter((r) => r.tag)

  const activeSteps: string[] = []
  if (activeFilterRows.length > 0) activeSteps.push(`Domain filters: ${activeFilterRows.length} tag(s)`)
  if (activeImputeRows.length > 0) activeSteps.push(`Impute: ${activeImputeRows.length} tag(s)`)
  if (removeMissingRows) activeSteps.push('Remove missing rows')
  if (removeDuplicates) activeSteps.push('Remove duplicates')
  if (removeMissingCols) activeSteps.push(`Remove columns (missing ≥ ${missingColThreshold}%)`)
  if (removeConstantCols) activeSteps.push('Remove constant columns')
  if (removeCvOutlierCols) activeSteps.push(`Remove columns (CV% < ${cvLowThreshold} or > ${cvHighThreshold})`)
  if (activeOutlierRows.length > 0) activeSteps.push(`Outliers: ${activeOutlierRows.length} tag(s)`)

  function apply() {
    const domain_filters =
      activeFilterRows.length > 0
        ? Object.fromEntries(
            activeFilterRows.map((r) => [r.tag, { min: r.min === '' ? 0 : r.min, max: r.max === '' ? 0 : r.max }]),
          )
        : undefined
    const impute_rules =
      activeImputeRows.length > 0
        ? Object.fromEntries(
            activeImputeRows.map((r) => [r.tag, { method: r.method, custom_fill_value: r.customFillValue }]),
          )
        : undefined
    const outlier_rules =
      activeOutlierRows.length > 0
        ? Object.fromEntries(
            activeOutlierRows.map((r) => [
              r.tag,
              {
                method: r.method,
                zscore_threshold: r.zscoreThreshold,
                winsor_lo: r.winsorLo,
                winsor_hi: r.winsorHi,
                cap_multiplier: r.capMultiplier,
              },
            ]),
          )
        : undefined
    cleanMutation.mutate({
      dataset_name: datasetName,
      domain_filters,
      impute_rules,
      remove_missing_rows: removeMissingRows,
      remove_duplicates: removeDuplicates,
      remove_missing_cols: removeMissingCols,
      missing_col_threshold: missingColThreshold === '' ? undefined : missingColThreshold,
      remove_constant_cols: removeConstantCols,
      remove_cv_outlier_cols: removeCvOutlierCols,
      cv_low_threshold: cvLowThreshold === '' ? undefined : cvLowThreshold,
      cv_high_threshold: cvHighThreshold === '' ? undefined : cvHighThreshold,
      outlier_rules,
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <SectionBanner
        icon="⚙️"
        title="Manual Preprocessing"
        subtitle="Domain Filters → Missing Value Imputation → Remove Records/Columns → Outlier Detection. Click 'Apply Cleaning' to save a new cleaned dataset."
      />

      <Tabs
        tabs={[
          {
            label: '📐 Domain Filters',
            content: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div>
                  <div style={{ fontWeight: 700 }}>Min–Max Filter</div>
                  <div className="caption">Use this to remove values outside expected operating limits.</div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {filterRows.map((row) => (
                    <div
                      key={row.id}
                      className="card"
                      style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', padding: '1rem', flexWrap: 'wrap' }}
                    >
                      <label style={{ flex: '1 1 200px' }}>
                        <div className="caption">Tag</div>
                        <select
                          value={row.tag}
                          onChange={(e) => selectFilterTag(row.id, e.target.value)}
                          style={{ width: '100%' }}
                        >
                          <option value="">Select tag</option>
                          {numericCols.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label style={{ flex: '1 1 140px' }}>
                        <div className="caption">Min value</div>
                        <input
                          type="number"
                          value={row.min}
                          onChange={(e) =>
                            updateFilterRow(row.id, { min: e.target.value === '' ? '' : Number(e.target.value) })
                          }
                          style={{ width: '100%' }}
                        />
                      </label>
                      <label style={{ flex: '1 1 140px' }}>
                        <div className="caption">Max value</div>
                        <input
                          type="number"
                          value={row.max}
                          onChange={(e) =>
                            updateFilterRow(row.id, { max: e.target.value === '' ? '' : Number(e.target.value) })
                          }
                          style={{ width: '100%' }}
                        />
                      </label>
                      <button
                        onClick={() => removeFilterRow(row.id)}
                        style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}
                      >
                        🗑️ Remove
                      </button>
                    </div>
                  ))}
                </div>

                <button onClick={addFilterRow} style={{ alignSelf: 'flex-start' }}>
                  + Add min–max rule
                </button>
              </div>
            ),
          },
          {
            label: '🔧 Missing Value Imputation',
            content: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div>
                  <div style={{ fontWeight: 700 }}>Imputation Rules</div>
                  <div className="caption">Fill missing values per column, each with its own method.</div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {imputeRows.map((row) => (
                    <div
                      key={row.id}
                      className="card"
                      style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', padding: '1rem', flexWrap: 'wrap' }}
                    >
                      <label style={{ flex: '1 1 200px' }}>
                        <div className="caption">Tag</div>
                        <select
                          value={row.tag}
                          onChange={(e) => updateImputeRow(row.id, { tag: e.target.value })}
                          style={{ width: '100%' }}
                        >
                          <option value="">Select tag</option>
                          {numericCols.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label style={{ flex: '1 1 160px' }}>
                        <div className="caption">Method</div>
                        <select
                          value={row.method}
                          onChange={(e) => updateImputeRow(row.id, { method: e.target.value })}
                          style={{ width: '100%' }}
                        >
                          {IMPUTE_METHODS.map((m) => (
                            <option key={m}>{m}</option>
                          ))}
                        </select>
                      </label>
                      {row.method === 'Custom Value' && (
                        <label style={{ flex: '1 1 120px' }}>
                          <div className="caption">Fill Value</div>
                          <input
                            type="number"
                            value={row.customFillValue}
                            onChange={(e) => updateImputeRow(row.id, { customFillValue: Number(e.target.value) })}
                            style={{ width: '100%' }}
                          />
                        </label>
                      )}
                      <button
                        onClick={() => removeImputeRow(row.id)}
                        style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}
                      >
                        🗑️ Remove
                      </button>
                    </div>
                  ))}
                </div>

                <button onClick={addImputeRow} style={{ alignSelf: 'flex-start' }}>
                  + Add imputation rule
                </button>
              </div>
            ),
          },
          {
            label: '🗑️ Remove Records/Columns',
            content: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ fontWeight: 700 }}>Record Removal</div>
                  <div style={{ display: 'flex', gap: '2rem' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <input type="checkbox" checked={removeMissingRows} onChange={(e) => setRemoveMissingRows(e.target.checked)} />
                      Remove rows with any missing values
                    </label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <input type="checkbox" checked={removeDuplicates} onChange={(e) => setRemoveDuplicates(e.target.checked)} />
                      Remove duplicate records
                    </label>
                  </div>
                </div>

                <div style={{ borderTop: '1px solid var(--border)' }} />

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  <div style={{ fontWeight: 700 }}>Column Removal</div>
                  <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <input type="checkbox" checked={removeMissingCols} onChange={(e) => setRemoveMissingCols(e.target.checked)} />
                      Remove columns with missing values ≥
                    </label>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={missingColThreshold}
                      onChange={(e) => setMissingColThreshold(clampPct(e.target.value === '' ? '' : Number(e.target.value)))}
                      style={{ width: 70 }}
                    />
                    %
                  </div>

                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <input type="checkbox" checked={removeConstantCols} onChange={(e) => setRemoveConstantCols(e.target.checked)} />
                    Remove constant columns (std = 0)
                  </label>

                  <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <input
                        type="checkbox"
                        checked={removeCvOutlierCols}
                        onChange={(e) => setRemoveCvOutlierCols(e.target.checked)}
                      />
                      Remove columns with CV% &lt;
                    </label>
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={100}
                      value={cvLowThreshold}
                      onChange={(e) => setCvLowThreshold(clampPct(e.target.value === '' ? '' : Number(e.target.value)))}
                      style={{ width: 70 }}
                    />
                    <span>or &gt;</span>
                    <input
                      type="number"
                      step={0.1}
                      min={0}
                      max={100}
                      value={cvHighThreshold}
                      onChange={(e) => setCvHighThreshold(clampPct(e.target.value === '' ? '' : Number(e.target.value)))}
                      style={{ width: 70 }}
                    />
                  </div>
                </div>
              </div>
            ),
          },
          {
            label: '📊 Outlier Detection',
            content: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div>
                  <div style={{ fontWeight: 700 }}>Outlier Rules</div>
                  <div className="caption">Treat outliers per column, each with its own method.</div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {outlierRows.map((row) => (
                    <div
                      key={row.id}
                      className="card"
                      style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', padding: '1rem', flexWrap: 'wrap' }}
                    >
                      <label style={{ flex: '1 1 200px' }}>
                        <div className="caption">Tag</div>
                        <select
                          value={row.tag}
                          onChange={(e) => updateOutlierRow(row.id, { tag: e.target.value })}
                          style={{ width: '100%' }}
                        >
                          <option value="">Select tag</option>
                          {numericCols.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label style={{ flex: '1 1 220px' }}>
                        <div className="caption">Method</div>
                        <select
                          value={row.method}
                          onChange={(e) => updateOutlierRow(row.id, { method: e.target.value })}
                          style={{ width: '100%' }}
                        >
                          {OUTLIER_METHODS.map((m) => (
                            <option key={m}>{m}</option>
                          ))}
                        </select>
                      </label>
                      {(row.method === 'Z-Score Capping' || row.method === 'Remove Outliers (Z-Score)') && (
                        <label style={{ flex: '1 1 120px' }}>
                          <div className="caption">Z-Score threshold</div>
                          <input
                            type="number"
                            value={row.zscoreThreshold}
                            onChange={(e) => updateOutlierRow(row.id, { zscoreThreshold: Number(e.target.value) })}
                            style={{ width: '100%' }}
                          />
                        </label>
                      )}
                      {row.method === 'Winsorization' && (
                        <>
                          <label style={{ flex: '1 1 100px' }}>
                            <div className="caption">Lower %</div>
                            <input
                              type="number"
                              value={row.winsorLo}
                              onChange={(e) => updateOutlierRow(row.id, { winsorLo: Number(e.target.value) })}
                              style={{ width: '100%' }}
                            />
                          </label>
                          <label style={{ flex: '1 1 100px' }}>
                            <div className="caption">Upper %</div>
                            <input
                              type="number"
                              value={row.winsorHi}
                              onChange={(e) => updateOutlierRow(row.id, { winsorHi: Number(e.target.value) })}
                              style={{ width: '100%' }}
                            />
                          </label>
                        </>
                      )}
                      {row.method === 'Capping/Flooring (custom IQR multiplier)' && (
                        <label style={{ flex: '1 1 120px' }}>
                          <div className="caption">IQR multiplier</div>
                          <input
                            type="number"
                            value={row.capMultiplier}
                            onChange={(e) => updateOutlierRow(row.id, { capMultiplier: Number(e.target.value) })}
                            style={{ width: '100%' }}
                          />
                        </label>
                      )}
                      <button
                        onClick={() => removeOutlierRow(row.id)}
                        style={{ color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}
                      >
                        🗑️ Remove
                      </button>
                    </div>
                  ))}
                </div>

                <button onClick={addOutlierRow} style={{ alignSelf: 'flex-start' }}>
                  + Add outlier rule
                </button>
              </div>
            ),
          },
        ]}
      />

      <div style={{ borderTop: '1px solid var(--border)', paddingTop: '1rem' }}>
        {activeSteps.length > 0 ? (
          <p className="caption">Configured steps: {activeSteps.join(' → ')}</p>
        ) : (
          <p className="caption">No preprocessing steps configured.</p>
        )}
        <button onClick={apply} disabled={cleanMutation.isPending}>
          {cleanMutation.isPending ? 'Applying…' : '✅ Apply Cleaning'}
        </button>

        {cleanMutation.isError && (
          <div style={{ marginTop: '0.75rem' }}>
            <Callout variant="error">Failed to apply cleaning.</Callout>
          </div>
        )}

        {cleanMutation.data && (
          <div style={{ marginTop: '0.75rem' }}>
            <Callout variant="success">
              Cleaning complete. Records: {cleanMutation.data.before_rows} → {cleanMutation.data.after_rows}. Saved as{' '}
              <code>{cleanMutation.data.new_dataset_name}</code>.
            </Callout>
            <ul className="caption">
              {(cleanMutation.data.action_log ?? []).map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
