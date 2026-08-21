import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getConfigStatus, getModelsStatus } from '../../api/whatIf'
import { StatusCard } from '../../components/StatusCard'

// The whole-application landing page (route '/'). Intentionally thin —
// detailed What-If status lives on /what-if/case-setup. This page just
// orients the user and links into the What-If Studio.
export function AppOverviewPage() {
  const whatIfConfigQuery = useQuery({ queryKey: ['whatif-config-status'], queryFn: getConfigStatus })
  const whatIfModelsQuery = useQuery({ queryKey: ['whatif-models-status'], queryFn: getModelsStatus })

  const whatIfReady =
    !!whatIfConfigQuery.data?.pi_mapping_present &&
    !!whatIfConfigQuery.data?.model_details_present &&
    !!whatIfModelsQuery.data?.all_present

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <div>
        <h1>🧭 SoftSense AI — What-If Studio</h1>
        <p className="caption">
          Simulate process scenarios against trained plant models and see the projected impact before you act.
        </p>
      </div>

      <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
        <div className="card" style={{ flex: 1, minWidth: 320, padding: '1.5rem' }}>
          <h2 style={{ fontSize: '1.15rem', marginTop: 0 }}>🧭 What-If Studio</h2>
          <div style={{ marginBottom: '1rem' }}>
            <StatusCard
              label="Setup Status"
              value={whatIfReady ? 'Ready' : 'Incomplete'}
              tone={whatIfReady ? 'success' : 'warning'}
              sublabel={whatIfReady ? 'Config and trained models detected' : 'Finish case setup to unlock the dashboard'}
            />
          </div>
          <Link to="/what-if/overview">
            <button>Go to What-If Studio →</button>
          </Link>
        </div>
      </div>
    </div>
  )
}
