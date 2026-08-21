import { useQuery } from '@tanstack/react-query'
import { getAccuracySummary } from '../../api/whatIf'

const COLUMNS = [
  'Predicted parameter', 'Status', 'Model type', 'Input parameters',
  'Train rows', 'Test rows', 'RMSE', 'MAE', 'MAPE_%', 'R2',
]

// Per-parameter training results (Model_accuracy_summary.csv), produced by
// the training script's generic Kalman-training loop. Shown after a
// successful "Train models" run.
export function AccuracySummaryPanel() {
  const query = useQuery({ queryKey: ['whatif-accuracy-summary'], queryFn: getAccuracySummary })

  if (query.isLoading) return null
  if (!query.data?.available) {
    return <p className="caption">Run training to generate a per-parameter accuracy summary.</p>
  }

  return (
    <div>
      <h4>📈 Model Accuracy Summary</h4>
      <div style={{ overflowX: 'auto' }}>
        <table className="table-compact">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {query.data.rows.map((row, i) => (
              <tr key={i}>
                {COLUMNS.map((c) => (
                  <td key={c}>{row[c] === null || row[c] === undefined ? '—' : String(row[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
