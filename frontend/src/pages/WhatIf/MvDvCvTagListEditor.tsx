import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { commitMvDvCvTaglist, getMvDvCvTaglist } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { inSectionScope } from './caseSetupHelpers'
import { useTouchedRowIndices } from './useTouchedRowIndices'
import { SECTION_OPTIONS } from './whatIfConstants'
import type { MvDvCvTagRow } from '../../api/types'

const TYPE_OPTIONS = ['', 'Independent', 'Dependent']

interface MvDvCvTagListEditorProps {
  /** Restricts which rows are shown/editable to those in-scope. Omit for
   * the unscoped, full-list view used outside the wizard. */
  allowed?: Set<string>
  /** Section dropdown options — normally the Process Flow Order list (so
   * this tab's Section picks stay in sync with the Target Section the user
   * chose there). Falls back to the generic section list when omitted. */
  sectionOptions?: string[]
  /** Called after a successful save — this is System Config's last sub-tab,
   * so the parent uses this to advance to the next top-level section
   * (Model Config) instead of leaving the user to click over themselves. */
  onSaved?: () => void
}

// Editor for the optional MV/DV/CV Tag List — a prioritized, plant-engineer
// curated input-tag source. When present, Model Mapping's input dropdowns
// list these tags before the remaining PI tags.
export function MvDvCvTagListEditor({ allowed, sectionOptions, onSaved }: MvDvCvTagListEditorProps) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['whatif-mvdvcv'], queryFn: getMvDvCvTaglist })
  const [rows, setRows] = useState<MvDvCvTagRow[]>([])
  const { touched, markTouched, onRowRemoved } = useTouchedRowIndices()

  useEffect(() => {
    if (query.data) setRows(query.data)
  }, [query.data])

  const commitMutation = useMutation({
    mutationFn: commitMvDvCvTaglist,
    onSuccess: (result) => {
      setRows(result)
      queryClient.setQueryData(['whatif-mvdvcv'], result)
      onSaved?.()
    },
  })

  if (query.isLoading) return <p className="caption">Loading MV/DV/CV tag list…</p>

  const sectionChoices = sectionOptions ?? SECTION_OPTIONS
  // Include any value already saved in the sheet that isn't one of the known
  // options (e.g. a stray legacy entry) so it stays visible/selected instead
  // of silently reverting to blank the moment this dropdown renders.
  const typeChoices = Array.from(
    new Set([...TYPE_OPTIONS, ...rows.map((r) => r.Type).filter((t): t is string => !!t)]),
  )

  const visibleIndices = rows
    .map((_, i) => i)
    .filter(
      (i) => !allowed || touched.has(i) || inSectionScope(rows[i].Section, allowed, rows[i].GeneralizedDescription),
    )
  const hiddenCount = rows.length - visibleIndices.length

  function updateCell(index: number, field: keyof MvDvCvTagRow, value: string) {
    const next = [...rows]
    next[index] = { ...next[index], [field]: value }
    setRows(next)
    markTouched(index)
  }

  function addRow() {
    setRows([...rows, { Name: '', GeneralizedDescription: '', Section: '', Type: '' }])
  }

  function removeRow(index: number) {
    setRows(rows.filter((_, i) => i !== index))
    onRowRemoved(index)
  }

  return (
    <div>
      <p className="caption">
        Optional: Manipulated/Disturbance/Controlled variable tags, prioritized as an input-tag source for Model
        Mapping ahead of the general PI Tag Mapping list.
      </p>
      <div style={{ overflowX: 'auto' }}>
        <table className="table-compact">
          <thead>
            <tr>
              <th>Name</th>
              <th>GeneralizedDescription</th>
              <th>Section</th>
              <th>Type</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visibleIndices.map((i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    value={rows[i].Name ?? ''}
                    onChange={(e) => updateCell(i, 'Name', e.target.value)}
                    style={{ width: 180 }}
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={rows[i].GeneralizedDescription ?? ''}
                    onChange={(e) => updateCell(i, 'GeneralizedDescription', e.target.value)}
                    style={{ width: 220 }}
                  />
                </td>
                <td>
                  <select
                    value={rows[i].Section ?? ''}
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
                  <select
                    value={rows[i].Type ?? ''}
                    onChange={(e) => updateCell(i, 'Type', e.target.value)}
                    style={{ width: 130 }}
                  >
                    {typeChoices.map((t) => (
                      <option key={t} value={t}>
                        {t || '—'}
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
          {hiddenCount} row(s) belonging to other sections are hidden here (left untouched).
        </p>
      )}
      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem' }}>
        <button className="chip" onClick={addRow}>
          + Add Tag
        </button>
        <button onClick={() => commitMutation.mutate(rows)}>💾 Save MV/DV/CV Tag List</button>
      </div>
      {commitMutation.isSuccess && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">MV/DV/CV tag list updated for this session.</Callout>
        </div>
      )}
    </div>
  )
}
