import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitConstraints, getConstraints } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import type { ConstraintsRow } from '../../api/types'

const VALUE_FIELDS: (keyof ConstraintsRow)[] = ['user input value', 'Max vlaue', 'UOM']
const ACTIONS = ['', 'bump_linked_to_max', 'abort_if_exceeds']

interface ConstraintsEditorProps {
  /** Parameter/Linked Parameter dropdown options (section-scoped tags).
   * Falls back to free-text inputs when omitted. */
  tagOptions?: string[]
  /** Called after a successful save — lets the parent tab strip advance to
   * the next section (User Inputs) automatically. */
  onSaved?: () => void
}

// Editor for the Constraints sheet — the generic rule engine that replaced
// the old hardcoded "bump turbine speed to max" / "abort if pressure
// exceeds" logic (see src/whatif/engine.py's apply_linked_constraints_for_inputs
// and check_abort_constraints). Every rule here is expressed as data, not code.
export function ConstraintsEditor({ tagOptions, onSaved }: ConstraintsEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-constraints'], queryFn: getConstraints })
  const [rows, setRows] = useState<ConstraintsRow[]>([])

  useEffect(() => {
    if (query.data) setRows(query.data)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitConstraints,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-constraints'], result)
      onSaved?.()
    },
  })

  if (query.isLoading) return <p className="caption">Loading constraints…</p>

  const paramChoices = tagOptions
    ? Array.from(new Set([...rows.map((r) => r.Parameter).filter(Boolean), ...tagOptions])).sort()
    : null

  function updateField(index: number, field: keyof ConstraintsRow, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [field]: value }
    setRows(next)
  }

  function addRow() {
    setRows([...rows, { Parameter: '', 'user input value': '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
  }

  function ParamField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
    if (paramChoices) {
      return (
        <select value={value} onChange={(e) => onChange(e.target.value)} style={{ width: 180 }}>
          <option value="">—</option>
          {paramChoices.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      )
    }
    return <input type="text" value={value ?? ''} onChange={(e) => onChange(e.target.value)} style={{ width: 180 }} />
  }

  return (
    <div>
      <Callout variant="info">
        Two rule types: <strong>bump_linked_to_max</strong> — if this row's Parameter is below its own limit AND the
        Linked Parameter is below its own limit, the Linked Parameter is bumped to its Max value.{' '}
        <strong>abort_if_exceeds</strong> — if this Parameter's computed value exceeds its limit, the whole what-if
        run stops and shows the Remark as the reason.
      </Callout>
      <div style={{ overflowX: 'auto', marginTop: '1rem' }}>
        <table className="table-compact">
          <thead>
            <tr>
              <th>Parameter</th>
              {VALUE_FIELDS.map((f) => (
                <th key={f}>{f}</th>
              ))}
              <th>Linked Parameter</th>
              <th>Action</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td>
                  <ParamField value={row.Parameter} onChange={(v) => updateField(i, 'Parameter', v)} />
                </td>
                {VALUE_FIELDS.map((f) => (
                  <td key={f}>
                    <input
                      type="text"
                      value={row[f] ?? ''}
                      onChange={(e) => updateField(i, f, e.target.value)}
                      style={{ width: f === 'Remark' ? 220 : 110 }}
                    />
                  </td>
                ))}
                <td>
                  <ParamField
                    value={row['Linked Parameter'] ?? ''}
                    onChange={(v) => updateField(i, 'Linked Parameter', v)}
                  />
                </td>
                <td>
                  <select
                    value={row.Action ?? ''}
                    onChange={(e) => updateField(i, 'Action', e.target.value)}
                    style={{ width: 170 }}
                  >
                    {ACTIONS.map((a) => (
                      <option key={a} value={a}>
                        {a || '—'}
                      </option>
                    ))}
                  </select>
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
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Constraint
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save Constraints</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">Constraints updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
