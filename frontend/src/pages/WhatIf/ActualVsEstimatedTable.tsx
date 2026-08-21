import { memo, useState } from 'react'
import { DataTable } from '../../components/DataTable'
import { downloadBlob } from '../../api/whatIf'
import { formatMetric } from '../../utils/formatMetric'
import type { WhatIfScenarioRow } from '../../api/types'

// Full, unrounded precision -- used only for the CSV export, which should
// keep exact figures regardless of how the on-screen table rounds them for
// readability (see fmtDisplay below).
function fmt(val: unknown): string {
  if (typeof val === 'number') return val.toFixed(3)
  return val == null ? '' : String(val)
}

// On-screen display: adaptive precision (see formatMetric) so a 6-figure
// value doesn't read like a raw sensor dump.
function fmtDisplay(val: unknown): string {
  if (typeof val === 'number') return formatMetric(val)
  return val == null ? '' : String(val)
}

function changeColor(change: number): string {
  if (change > 0) return 'var(--success-text)'
  if (change < 0) return 'var(--error-text)'
  return 'var(--text-caption)'
}

function asNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function toCsv(timestamp: string, rows: WhatIfScenarioRow[]): string {
  const header = ['Selected Timestamp', 'Parameter', 'Actual', 'Estimated', 'Change']
  const lines = [header.join(',')]
  for (const r of rows) {
    lines.push([timestamp, r.parameter, fmt(r.actual), fmt(r.estimated), r.change != null ? fmt(r.change) : ''].join(','))
  }
  return lines.join('\n')
}

interface ActualVsEstimatedTableProps {
  timestamp: string
  rows: WhatIfScenarioRow[]
}

// Memoized: this table doesn't depend on Simulation Overrides' typed values
// at all, but sits as a sibling under the same DashboardPage state — without
// memo, every keystroke there would re-render (and re-format) this whole
// table for no reason (see SimulationOverridesPanel.tsx's docstring).
export const ActualVsEstimatedTable = memo(function ActualVsEstimatedTable({ timestamp, rows }: ActualVsEstimatedTableProps) {
  const [filter, setFilter] = useState('')

  function exportCsv() {
    // Always the full, unfiltered set -- an on-screen search narrows what
    // you're looking at, not what you're allowed to export.
    const csv = toCsv(timestamp, rows)
    downloadBlob(new Blob([csv], { type: 'text/csv' }), 'WhatIf_Result.csv')
  }

  const visibleRows = filter.trim()
    ? rows.filter((r) => r.parameter.toLowerCase().includes(filter.trim().toLowerCase()))
    : rows

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <h3 style={{ marginBottom: 0 }}>📈 Actual vs Estimated Scenario Output</h3>
        {rows.length > 8 && (
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="🔍 Filter parameters…"
            style={{ maxWidth: 240 }}
          />
        )}
      </div>
      {filter.trim() && (
        <p className="caption" style={{ marginTop: '0.35rem' }}>
          {visibleRows.length} of {rows.length} match.
        </p>
      )}
      <DataTable
        columns={[
          { header: 'Parameter', render: (r) => r.parameter, sortValue: (r) => r.parameter },
          { header: 'Actual', render: (r) => fmtDisplay(r.actual), sortValue: (r) => asNum(r.actual) },
          { header: 'Estimated', render: (r) => fmtDisplay(r.estimated), sortValue: (r) => asNum(r.estimated) },
          {
            header: 'Change',
            render: (r) =>
              r.change == null ? (
                ''
              ) : (
                <span style={{ color: changeColor(r.change), fontWeight: 600 }}>
                  {r.change > 0 ? '▲ ' : r.change < 0 ? '▼ ' : ''}
                  {fmtDisplay(r.change)}
                </span>
              ),
            sortValue: (r) => r.change,
          },
        ]}
        rows={visibleRows}
        keyFn={(r) => r.parameter}
        maxVisibleRows={12}
        emptyMessage={`No parameters match "${filter}".`}
      />
      <button className="chip" style={{ marginTop: '1rem' }} onClick={exportCsv}>
        📥 Export Baseline vs Simulation Matrix (.CSV)
      </button>
    </div>
  )
})
