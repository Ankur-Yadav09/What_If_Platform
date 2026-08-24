import { useQuery } from '@tanstack/react-query'
import { memo, useEffect, useState } from 'react'
import { getBaseline } from '../../api/whatIf'
import { DataTable } from '../../components/DataTable'
import { formatMetric } from '../../utils/formatMetric'

interface BaselineValuesPanelProps {
  timestamp: string
  tags: string[]
}

// Memoized alongside ActualVsEstimatedTable/ValidationFiltersPanel — see
// ValidationFiltersPanel.tsx's docstring for why this matters.
export const BaselineValuesPanel = memo(function BaselineValuesPanel({ timestamp, tags }: BaselineValuesPanelProps) {
  const [open, setOpen] = useState(false)
  const query = useQuery({
    queryKey: ['whatif-baseline', timestamp, tags],
    queryFn: () => getBaseline(timestamp, tags),
    enabled: !!timestamp,
  })

  // Auto-expand every time a new snapshot is confirmed, so the values load
  // and display immediately instead of waiting on a manual toggle click —
  // still collapsible afterward if the user wants the space back.
  useEffect(() => {
    if (timestamp) setOpen(true)
  }, [timestamp])

  const rows = query.data ? Object.entries(query.data).map(([parameter, value]) => ({ parameter, value })) : []

  return (
    <div>
      <button className="chip" onClick={() => setOpen((o) => !o)}>
        {open ? '▲' : '▼'} Baseline Process Values at Selected Timestamp
      </button>
      {open && (
        <div style={{ marginTop: '0.75rem' }}>
          <DataTable
            columns={[
              { header: 'Parameter', render: (r) => r.parameter },
              {
                header: 'Current Value',
                render: (r) => (typeof r.value === 'number' ? formatMetric(r.value) : String(r.value ?? '')),
              },
            ]}
            rows={rows}
            keyFn={(r) => r.parameter}
            maxVisibleRows={8}
          />
        </div>
      )}
    </div>
  )
})
