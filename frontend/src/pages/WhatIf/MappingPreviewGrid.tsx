import { useMemo, useState } from 'react'
import { downloadBlob, exportConfig } from '../../api/whatIf'
import { SECTION_OPTIONS } from './whatIfConstants'
import type { ModelDetailsRow, PiMappingRow } from '../../api/types'

interface MappingPreviewGridProps {
  rows: PiMappingRow[]
  onChange: (rows: PiMappingRow[]) => void
  onCommit: () => void
  modelDetailsRows: ModelDetailsRow[]
  sectionCounts: Record<string, number>
}

export function MappingPreviewGrid({ rows, onChange, onCommit, modelDetailsRows, sectionCounts }: MappingPreviewGridProps) {
  const [sectionFilter, setSectionFilter] = useState('All')

  const sections = useMemo(
    () => ['All', ...Array.from(new Set(rows.map((r) => r.Section))).sort()],
    [rows],
  )
  const visibleRows = sectionFilter === 'All' ? rows : rows.filter((r) => r.Section === sectionFilter)

  function updateRow(index: number, field: keyof PiMappingRow, value: string) {
    const target = visibleRows[index]
    const actualIndex = rows.indexOf(target)
    const next = [...rows]
    next[actualIndex] = { ...next[actualIndex], [field]: value }
    onChange(next)
  }

  function deleteRow(index: number) {
    const target = visibleRows[index]
    const actualIndex = rows.indexOf(target)
    onChange(rows.filter((_, i) => i !== actualIndex))
  }

  function addRow() {
    onChange([...rows, { Pi_tags: '', 'Generalized Description': '', Section: '' }])
  }

  const chips = Object.entries(sectionCounts).map(([sec, count]) => (
    <span key={sec} className="chip" style={{ cursor: 'default' }}>
      {sec}: {count} tags
    </span>
  ))

  async function handleExport(format: 'xlsx' | 'csv') {
    const blob = await exportConfig(rows, modelDetailsRows, format)
    downloadBlob(blob, format === 'xlsx' ? 'Generated_PI_mapping.xlsx' : 'Generated_PI_mapping.csv')
  }

  if (rows.length === 0) {
    return <p className="caption">Generate a mapping above to preview it here.</p>
  }

  return (
    <div>
      {chips.length > 0 && <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>{chips}</div>}

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
        <label className="caption">Filter preview by section</label>
        <select value={sectionFilter} onChange={(e) => setSectionFilter(e.target.value)}>
          {sections.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="data-table-scroll" style={{ overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
        <table className="table-compact">
          <thead>
            <tr>
              <th>Pi_tags</th>
              <th>Generalized Description</th>
              <th>Section</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    value={row.Pi_tags}
                    placeholder="fill in raw PI tag"
                    onChange={(e) => updateRow(i, 'Pi_tags', e.target.value)}
                    style={{ width: 170 }}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={row['Generalized Description']}
                    onChange={(e) => updateRow(i, 'Generalized Description', e.target.value)}
                    style={{ width: 200 }}
                  />
                </td>
                <td>
                  <select value={row.Section} onChange={(e) => updateRow(i, 'Section', e.target.value)}>
                    {SECTION_OPTIONS.map((s) => (
                      <option key={s} value={s}>{s || '—'}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <button className="chip" onClick={() => deleteRow(i)}>✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', flexWrap: 'wrap' }}>
        <button className="chip" onClick={addRow}>+ Add row</button>
        <button onClick={onCommit}>💾 Update Generated Mapping</button>
        <button className="chip" onClick={() => handleExport('xlsx')}>📥 Export mapping (.xlsx)</button>
        <button className="chip" onClick={() => handleExport('csv')}>📥 Export mapping (.csv)</button>
      </div>
    </div>
  )
}
