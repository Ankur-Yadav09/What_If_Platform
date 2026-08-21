import { useQuery } from '@tanstack/react-query'
import { getTargetSection } from '../../api/whatIf'

interface TargetSectionSelectorProps {
  value: string | null
  onChange: (section: string | null) => void
}

// Lets the user scope a what-if run to a section + everything upstream of it
// (see src/whatif/engine.py's filter_model_details_by_section) — used on
// both the Case Setup wizard (to set the default) and the Dashboard (to
// re-pick it per run without redoing the wizard), matching the reference
// Streamlit dashboard's "Target Section" behavior.
export function TargetSectionSelector({ value, onChange }: TargetSectionSelectorProps) {
  const query = useQuery({ queryKey: ['whatif-target-section'], queryFn: getTargetSection })
  const sectionOrder = query.data?.section_order ?? []

  if (query.isLoading) return <p className="caption">Loading process flow order…</p>
  if (sectionOrder.length < 2) {
    return (
      <p className="caption">
        Define at least 2 sections in the Process Execution Order step to enable section-scoped what-if runs.
      </p>
    )
  }

  const active = value ?? query.data?.target_section ?? sectionOrder[sectionOrder.length - 1]
  const idx = sectionOrder.indexOf(active)
  const excluded = idx >= 0 ? sectionOrder.slice(idx + 1) : []

  return (
    <div>
      <label className="caption" style={{ display: 'block', marginBottom: '0.4rem' }}>
        🎯 Target Section (compute this section and everything upstream of it)
      </label>
      <select value={active} onChange={(e) => onChange(e.target.value)} style={{ minWidth: 220 }}>
        {sectionOrder.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {excluded.length > 0 && (
        <p className="caption" style={{ marginTop: '0.4rem' }}>
          {excluded.length} downstream section{excluded.length === 1 ? '' : 's'} hidden: {excluded.join(', ')}
        </p>
      )}
    </div>
  )
}
