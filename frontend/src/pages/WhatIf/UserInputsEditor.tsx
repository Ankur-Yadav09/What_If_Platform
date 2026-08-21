import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitUserInputs, getUserInputs } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import type { UserInputsRow } from '../../api/types'

const VALUE_FIELDS: (keyof UserInputsRow)[] = ['Lower Limit', 'Upper Limit']

interface UserInputsEditorProps {
  /** Parameter dropdown options (section-scoped tags). Falls back to a
   * free-text input when omitted. */
  tagOptions?: string[]
  /** Called after a successful save — lets the parent tab strip advance to
   * the next section (Results Layout) automatically. */
  onSaved?: () => void
}

// Editor for the "user inputs" sheet: the tags that get a Simulation
// Overrides text box on the Dashboard, with their default value and
// override bounds.
export function UserInputsEditor({ tagOptions, onSaved }: UserInputsEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-user-inputs'], queryFn: getUserInputs })
  const [rows, setRows] = useState<UserInputsRow[]>([])

  useEffect(() => {
    if (query.data) setRows(query.data)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitUserInputs,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-user-inputs'], result)
      onSaved?.()
    },
  })

  if (query.isLoading) return <p className="caption">Loading user inputs…</p>

  function updateCell(index: number, field: keyof UserInputsRow, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [field]: value }
    setRows(next)
  }

  function addRow() {
    setRows([...rows, { Parameter: '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
  }

  return (
    <div>
      <p className="caption">Default value and override bounds for each tag exposed as a Simulation Override.</p>
      <div style={{ overflowX: 'auto' }}>
        <table className="table-compact">
          <thead>
            <tr>
              <th>Parameter</th>
              {VALUE_FIELDS.map((f) => (
                <th key={f}>{f}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td>
                  {tagOptions ? (
                    <select
                      value={row.Parameter}
                      onChange={(e) => updateCell(i, 'Parameter', e.target.value)}
                      style={{ width: 200 }}
                    >
                      <option value="">—</option>
                      {tagOptions.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={row.Parameter}
                      onChange={(e) => updateCell(i, 'Parameter', e.target.value)}
                      style={{ width: 200 }}
                    />
                  )}
                </td>
                {VALUE_FIELDS.map((f) => (
                  <td key={f}>
                    <input
                      type="text"
                      value={row[f] ?? ''}
                      onChange={(e) => updateCell(i, f, e.target.value)}
                      style={{ width: f === 'Remark' ? 220 : 130 }}
                    />
                  </td>
                ))}
                <td>
                  <button className="chip" onClick={() => removeRow(i)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Parameter
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save User Inputs</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">User inputs updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
