import { useMutation, useQuery } from '@tanstack/react-query'
import { memo, useMemo, useState } from 'react'
import { downloadBlob, exportScenarioCsv, runValidationFilter } from '../../api/whatIf'
import { DataTable } from '../../components/DataTable'
import type { ValidationFilterResult, WhatIfScenarioRow } from '../../api/types'

interface ValidationFiltersPanelProps {
  timestamp: string
  scenarioRows: WhatIfScenarioRow[]
  targetSection?: string | null
}

// Rendering every matching snapshot as real DOM (DataTable has no
// virtualization) is fine for a genuinely narrowed-down filter result, but
// with NO filters applied `run_validation_filter` returns the ENTIRE
// historian unfiltered (~8000 rows on this plant) — that's what was
// actually making this panel feel sluggish, not the surrounding re-renders.
// The table is transposed (one row per Parameter, one column per matched
// snapshot -- see ValidationResultsTable below), so this now caps rendered
// COLUMNS rather than rows; a wide table is harder to scan than a tall one,
// so the cap is tighter than the old row cap was. The true match_count is
// still shown, and export still uses the FULL, un-capped `results.rows` the
// server already returned.
const DISPLAY_COLUMN_CAP = 50

interface FilterEntry {
  tag: string
  min: number
  max: number
}

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}

// Same "round numbers, leave everything else alone" convention as
// ActualVsEstimatedTable.tsx's fmt() — historian values often carry many
// more decimals than are meaningful to read.
function fmt(value: unknown): string {
  if (typeof value === 'number') return value.toFixed(3)
  return value == null ? '' : String(value)
}

// The backend serializes Timestamp as ISO ("2025-01-22T10:00:00.000") —
// technically correct but not what a process engineer wants to read at a
// glance. Reformat to the same plain "YYYY-MM-DD HH:MM:SS" style used
// everywhere else in What-If Studio (e.g. the snapshot picker).
function formatTimestamp(value: unknown): string {
  if (typeof value !== 'string') return String(value ?? '')
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/.exec(value)
  return m ? `${m[1]} ${m[2]}` : value
}

// Isolated from the filter-editing controls above it and memoized on its own
// (props stay referentially stable while you're just editing filter
// criteria — see DISPLAY_COLUMN_CAP's comment) so typing a Min/Max value or
// adding/removing a filter row never touches this table until you actually
// click "Apply Filters".
//
// Transposed to match the merged export's shape (export_scenario_csv in
// what_if_service.py): one row per Parameter, one column per matched
// historical snapshot headed by that snapshot's own timestamp, instead of
// one row per snapshot / one column per tag.
const ValidationResultsTable = memo(function ValidationResultsTable({
  results,
  allTags,
  timestamp,
  scenarioRows,
}: {
  results: ValidationFilterResult
  allTags: string[]
  timestamp: string
  scenarioRows: WhatIfScenarioRow[]
}) {
  const [tagFilter, setTagFilter] = useState('')

  async function exportCsv() {
    // Always every tag column, regardless of the on-screen row search below
    // -- narrowing which parameters you're looking at shouldn't narrow what
    // you're allowed to export.
    const { blob, filename } = await exportScenarioCsv(timestamp, scenarioRows, results.rows)
    downloadBlob(blob, filename)
  }

  const visibleSnapshots = results.rows.slice(0, DISPLAY_COLUMN_CAP)

  const visibleTags = tagFilter.trim()
    ? allTags.filter((t) => t.toLowerCase().includes(tagFilter.trim().toLowerCase()))
    : allTags

  if (results.rows.length === 0) {
    return (
      <div style={{ marginTop: '1.5rem' }}>
        <h4 style={{ margin: 0 }}>Correlated Historical Validation Sets</h4>
        <p className="caption">No historical snapshots match these filters.</p>
        <button className="chip" style={{ marginTop: '1rem' }} onClick={exportCsv}>
          Export Unified Comparison &amp; Historical Validation Data (.CSV)
        </button>
      </div>
    )
  }

  return (
    <div style={{ marginTop: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <h4 style={{ margin: 0 }}>Correlated Historical Validation Sets</h4>
        {allTags.length > 6 && (
          <input
            type="text"
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            placeholder="Find a parameter…"
            style={{ maxWidth: 240 }}
          />
        )}
      </div>
      <p className="caption">
        {results.match_count} matching historical snapshot(s)
        {results.match_count > DISPLAY_COLUMN_CAP &&
          ` — showing the first ${DISPLAY_COLUMN_CAP} as columns here; narrow your filters to see specific ones, or export for the full set.`}
        {tagFilter.trim() && ` — showing ${visibleTags.length} of ${allTags.length} parameter rows matching "${tagFilter}".`}
      </p>
      <DataTable
        columns={[
          {
            header: 'Parameter',
            render: (tag: string) => tag,
            sortValue: (tag: string) => tag,
          },
          ...visibleSnapshots.map((snapshot) => ({
            header: formatTimestamp(snapshot.Timestamp),
            render: (tag: string) => fmt(snapshot[tag]),
            sortValue: (tag: string) => {
              const v = snapshot[tag]
              return typeof v === 'number' && Number.isFinite(v) ? v : null
            },
          })),
        ]}
        rows={visibleTags}
        keyFn={(tag) => tag}
        maxVisibleRows={8}
        stickyFirstColumn
      />
      <button className="chip" style={{ marginTop: '1rem' }} onClick={exportCsv}>
        Export Unified Comparison &amp; Historical Validation Data ({results.rows.length > 0 ? '.XLSX' : '.CSV'})
      </button>
    </div>
  )
})

// This is where Streamlit's st.sidebar "Validation Filters" panel lives in
// the React app — placed directly above the historical validation table it
// feeds, since the app's actual Sidebar is reserved for top-level nav.
//
// Memoized: this panel is a sibling of SimulationOverridesPanel under
// DashboardPage — without memo, every override keystroke would re-render it
// (and, transitively, its results table) for no reason.
export const ValidationFiltersPanel = memo(function ValidationFiltersPanel({ timestamp, scenarioRows, targetSection }: ValidationFiltersPanelProps) {
  // "+ Add Filter" appends a blank entry; picking a tag for it fills in that
  // tag's historical min/max as a starting range — same "+ Add X" row
  // pattern as ConstraintsEditor/UserInputsEditor, rather than a checkbox
  // multi-select of every tag at once.
  const [filters, setFilters] = useState<FilterEntry[]>([])

  const allQuery = useQuery({
    queryKey: ['whatif-validation-all', targetSection],
    queryFn: () => runValidationFilter({}, targetSection),
  })
  const filterMutation = useMutation({
    mutationFn: (body: Record<string, { min: number; max: number }>) => runValidationFilter(body, targetSection),
  })

  // Memoized so its array reference stays stable across renders that don't
  // touch allQuery.data (e.g. typing a Min/Max value) — otherwise a fresh
  // array every render would defeat ValidationResultsTable's memo below.
  const allTags = useMemo(
    () =>
      allQuery.data && allQuery.data.rows.length > 0
        ? Object.keys(allQuery.data.rows[0]).filter((k) => k !== 'Timestamp')
        : [],
    [allQuery.data],
  )

  function tagBounds(tag: string): { min: number; max: number } {
    const values = (allQuery.data?.rows ?? [])
      .map((r) => Number(r[tag]))
      .filter((v) => !Number.isNaN(v))
    return values.length
      ? { min: round3(Math.min(...values)), max: round3(Math.max(...values)) }
      : { min: 0, max: 0 }
  }

  function addFilter() {
    setFilters([...filters, { tag: '', min: 0, max: 0 }])
  }

  function selectTag(index: number, tag: string) {
    const next = [...filters]
    next[index] = tag ? { tag, ...tagBounds(tag) } : { tag: '', min: 0, max: 0 }
    setFilters(next)
  }

  function updateBound(index: number, field: 'min' | 'max', value: number) {
    const next = [...filters]
    next[index] = { ...next[index], [field]: value }
    setFilters(next)
  }

  function removeFilter(index: number) {
    setFilters(filters.filter((_, i) => i !== index))
  }

  const activeFilters = filters.filter((f) => f.tag)
  const results = filterMutation.data ?? allQuery.data

  function apply() {
    const body = Object.fromEntries(activeFilters.map((f) => [f.tag, { min: f.min, max: f.max }]))
    filterMutation.mutate(body)
  }

  return (
    <details className="card" style={{ padding: '1.5rem' }}>
      <summary style={{ cursor: 'pointer', fontWeight: 700, fontSize: '1.05rem' }}>
        Validation Filters — compare this scenario against similar historical snapshots (optional)
      </summary>
      <div style={{ marginTop: '1rem' }}>
        {allQuery.isLoading ? (
          <p className="caption">Loading historical validation data…</p>
        ) : allTags.length === 0 ? (
          <p className="caption">Validation tags are missing from the historian dataset.</p>
        ) : (
          <>
            {filters.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1rem' }}>
                {filters.map((f, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <select
                      value={f.tag}
                      onChange={(e) => selectTag(i, e.target.value)}
                      style={{ minWidth: 240 }}
                    >
                      <option value="">Select a tag…</option>
                      {allTags.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    {f.tag && (
                      <>
                        <label className="caption">
                          Min
                          <input
                            type="number"
                            value={f.min}
                            onChange={(e) => updateBound(i, 'min', Number(e.target.value))}
                            style={{ width: 110, marginLeft: '0.4rem' }}
                          />
                        </label>
                        <label className="caption">
                          Max
                          <input
                            type="number"
                            value={f.max}
                            onChange={(e) => updateBound(i, 'max', Number(e.target.value))}
                            style={{ width: 110, marginLeft: '0.4rem' }}
                          />
                        </label>
                      </>
                    )}
                    <button className="chip" onClick={() => removeFilter(i)}>
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <button className="chip" onClick={addFilter}>
                + Add Filter
              </button>
              {activeFilters.length > 0 && (
                <button onClick={apply} disabled={filterMutation.isPending}>
                  {filterMutation.isPending ? 'Filtering…' : 'Apply Filters'}
                </button>
              )}
            </div>
          </>
        )}

        {results && (
          <ValidationResultsTable results={results} allTags={allTags} timestamp={timestamp} scenarioRows={scenarioRows} />
        )}
      </div>
    </details>
  )
})
