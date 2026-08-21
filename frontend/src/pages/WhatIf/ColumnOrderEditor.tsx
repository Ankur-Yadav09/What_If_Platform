import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitColumnOrder, getColumnOrder } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { optionsWithCurrentValue } from './caseSetupHelpers'
import type { ColumnOrderRow } from '../../api/types'

interface ColumnOrderEditorProps {
  /** "Preferred columns" dropdown options (section-scoped PI tags). Falls
   * back to a free-text input when omitted. Preferred Columns routinely
   * also names computed/derived parameters (predicted parameters, KPI
   * totals) that aren't PI tags at all — those wouldn't match any <option>
   * here, so optionsWithCurrentValue() below keeps an already-saved value
   * selectable regardless, instead of silently rendering as a blank
   * selection. */
  tagOptions?: string[]
}

// Editor for "display_column_order": the preferred column order for the
// Actual-vs-Estimated table and CSV exports.
export function ColumnOrderEditor({ tagOptions }: ColumnOrderEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-column-order'], queryFn: getColumnOrder })
  const [rows, setRows] = useState<ColumnOrderRow[]>([])

  useEffect(() => {
    if (query.data) setRows(query.data)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitColumnOrder,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-column-order'], result)
    },
  })

  if (query.isLoading) return <p className="caption">Loading column order…</p>

  function updateCell(index: number, field: keyof ColumnOrderRow, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [field]: value }
    setRows(next)
  }

  function addRow() {
    setRows([...rows, { 'Sr.no': rows.length + 1, 'Preferred columns': '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
  }

  return (
    <div>
      <p className="caption">Preferred column display order for the Actual-vs-Estimated table and CSV exports.</p>
      <table className="table-compact">
        <thead>
          <tr>
            <th>Sr.no</th>
            <th>Preferred columns</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td>
                <input
                  type="number"
                  value={row['Sr.no']}
                  onChange={(e) => updateCell(i, 'Sr.no', e.target.value)}
                  style={{ width: 70 }}
                />
              </td>
              <td>
                {tagOptions ? (
                  <select
                    value={row['Preferred columns']}
                    onChange={(e) => updateCell(i, 'Preferred columns', e.target.value)}
                    style={{ width: 260 }}
                  >
                    <option value="">—</option>
                    {optionsWithCurrentValue(tagOptions, row['Preferred columns']).map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={row['Preferred columns']}
                    onChange={(e) => updateCell(i, 'Preferred columns', e.target.value)}
                    style={{ width: 260 }}
                  />
                )}
              </td>
              <td>
                <button className="chip" onClick={() => removeRow(i)}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Column
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save Column Order</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">Column order updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
