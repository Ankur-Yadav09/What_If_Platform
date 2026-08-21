import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitMapping, getPiMapping } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { inSectionScope } from './caseSetupHelpers'
import { useTouchedRowIndices } from './useTouchedRowIndices'
import { SECTION_OPTIONS } from './whatIfConstants'
import type { PiMappingRow } from '../../api/types'

interface PiTagMappingEditorProps {
  /** Restricts which rows are shown/editable to those in-scope (Section
   * blank/unclassified rows are always shown). Omit for the unscoped,
   * full-dictionary view used outside the wizard. */
  allowed?: Set<string>
  sectionOptions?: string[]
  /** Called after a successful save — lets the parent tab strip advance to
   * the next section (Input Tag Configuration) automatically. */
  onSaved?: () => void
}

// Editable master PI dictionary (Pi_tags -> Generalized Description ->
// Section) — Case Setup wizard Step 3. Rows outside the active scope stay
// in the dataset untouched, just hidden from view (see `allowed`).
export function PiTagMappingEditor({ allowed, sectionOptions, onSaved }: PiTagMappingEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-pi-mapping'], queryFn: getPiMapping })
  const [rows, setRows] = useState<PiMappingRow[]>([])
  const { touched, markTouched, onRowRemoved } = useTouchedRowIndices()

  useEffect(() => {
    if (query.data) setRows(query.data)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitMapping,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-pi-mapping'], result)
      onSaved?.()
    },
  })

  if (query.isLoading) return <p className="caption">Loading PI tag dictionary…</p>

  const sectionChoices = sectionOptions ?? SECTION_OPTIONS
  const visibleIndices = rows
    .map((_, i) => i)
    .filter(
      (i) =>
        !allowed || touched.has(i) || inSectionScope(rows[i].Section, allowed, rows[i]['Generalized Description']),
    )
  const hiddenCount = rows.length - visibleIndices.length

  function updateCell(index: number, field: keyof PiMappingRow, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [field]: value }
    setRows(next)
    markTouched(index)
  }

  function addRow() {
    setRows([...rows, { Pi_tags: '', 'Generalized Description': '', Section: '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
    onRowRemoved(index)
  }

  return (
    <div>
      <p className="caption">
        Master PI dictionary (Pi_tags → Generalized Description → Section). Map at least one tag before continuing.
      </p>
      <div style={{ overflowX: 'auto', maxHeight: 420, overflowY: 'auto' }}>
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
            {visibleIndices.map((i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    value={rows[i].Pi_tags}
                    onChange={(e) => updateCell(i, 'Pi_tags', e.target.value)}
                    style={{ width: 160 }}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={rows[i]['Generalized Description']}
                    onChange={(e) => updateCell(i, 'Generalized Description', e.target.value)}
                    style={{ width: 220 }}
                  />
                </td>
                <td>
                  <select
                    value={rows[i].Section}
                    onChange={(e) => updateCell(i, 'Section', e.target.value)}
                    style={{ width: 130 }}
                  >
                    {sectionChoices.map((s) => (
                      <option key={s} value={s}>
                        {s || '—'}
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
      {hiddenCount > 0 && (
        <p className="caption" style={{ marginTop: '0.5rem' }}>
          ℹ️ {hiddenCount} row(s) belonging to other sections are hidden here (left untouched) — change the Target
          Section to edit them.
        </p>
      )}
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Tag
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save PI Tag Mapping</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">PI tag mapping updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
