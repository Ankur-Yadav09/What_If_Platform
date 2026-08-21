import { useMutation, useQuery } from '@tanstack/react-query'
import type { CSSProperties } from 'react'
import { exportCorrelationMatrix, getCorrelationMatrix } from '../../api/preprocess'
import { Callout } from '../../components/Callout'
import { downloadBlob } from '../../api/whatIf'

function cellStyle(value: number | null): CSSProperties {
  if (value === null) return {}
  if (value > 0.4) return { backgroundColor: 'rgba(34, 197, 94, 0.25)' }
  if (value < -0.4) return { backgroundColor: 'rgba(239, 68, 68, 0.25)' }
  return {}
}

interface CorrelationMatrixViewProps {
  /** The dataset currently active in Connect Data — the same dataset Data
   * Health's other checks (PreprocessPage) already run against. */
  datasetName: string
}

// Pearson correlation matrix over the connected dataset's numeric columns,
// with the same green(> 0.4)/red(< -0.4) conditional coloring as the
// reference Streamlit dashboard's correlation step.
export function CorrelationMatrixView({ datasetName }: CorrelationMatrixViewProps) {
  const query = useQuery({
    queryKey: ['dataset-correlation-matrix', datasetName],
    queryFn: () => getCorrelationMatrix(datasetName),
    enabled: !!datasetName,
  })
  const exportMutation = useMutation({
    mutationFn: () => exportCorrelationMatrix(datasetName),
    onSuccess: (blob) => downloadBlob(blob, `Correlation_Matrix_${datasetName}.xlsx`),
  })

  if (!datasetName) return <p className="caption">Select a dataset in Connect Data to see its correlation matrix.</p>
  if (query.isLoading) return <p className="caption">Computing correlation matrix…</p>
  if (query.isError) {
    return <p className="caption">Correlation matrix unavailable for '{datasetName}'.</p>
  }
  const data = query.data
  if (!data || data.columns.length === 0) return <p className="caption">No numeric columns to correlate.</p>

  return (
    <div>
      <p className="caption">
        {data.n_rows} numeric columns from <code>{datasetName}</code>. Green cells are strongly positively correlated
        (&gt; 0.4), red cells strongly negatively correlated (&lt; -0.4).
      </p>
      <div className="data-table-scroll" style={{ overflow: 'auto', maxHeight: 480 }}>
        <table className="table-compact" style={{ fontSize: '0.75rem' }}>
          <thead>
            <tr>
              <th className="sticky-col">&nbsp;</th>
              {data.columns.map((c) => (
                <th key={c} title={c} style={{ whiteSpace: 'nowrap' }}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.matrix.map((row, i) => (
              <tr key={data.columns[i]}>
                <td className="sticky-col" style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                  {data.columns[i]}
                </td>
                {row.map((value, j) => (
                  <td key={j} style={cellStyle(value)}>
                    {value === null ? '' : value.toFixed(3)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button
        className="chip"
        style={{ marginTop: '1rem' }}
        onClick={() => exportMutation.mutate()}
        disabled={exportMutation.isPending}
      >
        {exportMutation.isPending ? 'Preparing…' : '📥 Download Correlation Matrix (.XLSX)'}
      </button>
      {exportMutation.isError && (
        <div style={{ marginTop: '0.5rem' }}>
          <Callout variant="error">Could not prepare the correlation matrix download.</Callout>
        </div>
      )}
    </div>
  )
}
