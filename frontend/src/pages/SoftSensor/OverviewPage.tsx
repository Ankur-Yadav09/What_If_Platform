import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getOverview } from '../../api/overview'
import { Callout } from '../../components/Callout'
import { DataTable } from '../../components/DataTable'
import { StatusCard } from '../../components/StatusCard'
import { WorkflowGuide } from '../../components/WorkflowGuide'
import type { SavedModelSummary } from '../../api/types'

// Relocated from pages/Overview/OverviewPage.tsx (unchanged) to become the
// Soft Sensor module's own overview, now that '/' is the whole-app overview
// (see pages/Overview/AppOverviewPage.tsx).
export function SoftSensorOverviewPage() {
  const navigate = useNavigate()
  const overviewQuery = useQuery({ queryKey: ['overview'], queryFn: getOverview })

  const mostRecentModel = useMemo(() => {
    const models = overviewQuery.data?.saved_models ?? []
    if (models.length === 0) return null
    return [...models].sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1))[0].name
  }, [overviewQuery.data])

  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const activeModel = selectedModel ?? mostRecentModel

  if (overviewQuery.isLoading) return <p className="caption">Loading overview…</p>
  if (overviewQuery.isError) return <p className="caption">Failed to load overview.</p>

  const { datasets, saved_models: savedModels } = overviewQuery.data!
  const activeSummary = savedModels.find((m) => m.name === activeModel)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <div>
        <h1>🏭 Soft Sensor Module</h1>
        <p className="caption">Industrial AI Platform for Soft Sensor Development and Process Optimization</p>
      </div>

      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <StatusCard
          label="Datasets Stored"
          value={String(datasets.length)}
          tone={datasets.length > 0 ? 'info' : 'warning'}
          sublabel={datasets.length === 0 ? 'Upload data to begin' : undefined}
        />
        <StatusCard
          label="Models Trained"
          value={String(savedModels.length)}
          tone={savedModels.length > 0 ? 'info' : 'warning'}
          sublabel={savedModels.length === 0 ? 'Train a model first' : undefined}
        />
        <StatusCard
          label="Best Test R² (all models)"
          tone={savedModels.some((m) => m.avg_r2 != null) ? 'success' : 'warning'}
          value={
            savedModels.some((m) => m.avg_r2 != null)
              ? Math.max(...savedModels.map((m) => m.avg_r2 ?? -Infinity)).toFixed(3)
              : '—'
          }
        />
      </div>

      <section>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '1.15rem' }}>📊 Model Performance</h2>
          {savedModels.length > 0 && (
            <select value={activeModel ?? ''} onChange={(e) => setSelectedModel(e.target.value)}>
              {[...savedModels]
                .sort((a, b) => (a.saved_at < b.saved_at ? 1 : -1))
                .map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
            </select>
          )}
        </div>

        {savedModels.length === 0 && (
          <Callout variant="info">Upload data, preprocess, and train a model to see performance metrics here.</Callout>
        )}

        {activeSummary && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
              <StatusCard
                label="Train R² / RMSE / MAE"
                tone={activeSummary.train_r2 != null ? 'info' : 'warning'}
                value={activeSummary.train_r2 != null ? activeSummary.train_r2.toFixed(3) : '—'}
                sublabel={
                  activeSummary.train_rmse != null && activeSummary.train_mae != null
                    ? `RMSE ${activeSummary.train_rmse.toFixed(3)} · MAE ${activeSummary.train_mae.toFixed(3)}`
                    : 'Not available for this model'
                }
              />
              <StatusCard
                label="Test R² / RMSE / MAE"
                tone={activeSummary.avg_r2 != null ? 'success' : 'warning'}
                value={activeSummary.avg_r2 != null ? activeSummary.avg_r2.toFixed(3) : '—'}
                sublabel={
                  activeSummary.avg_rmse != null && activeSummary.avg_mae != null
                    ? `RMSE ${activeSummary.avg_rmse.toFixed(3)} · MAE ${activeSummary.avg_mae.toFixed(3)}`
                    : 'Not available for this model'
                }
              />
            </div>
            {activeSummary.train_r2 != null && activeSummary.avg_r2 != null && (
              <p className="caption">
                Gap (Train − Test) = <code>{(activeSummary.train_r2 - activeSummary.avg_r2).toFixed(3)}</code> — a
                large gap means the model fits its training data much better than unseen data (overfitting). For a
                detailed per-target breakdown, run this model on the Predict page's Project Test Split.
              </p>
            )}
            <div style={{ display: 'flex', gap: '3rem', flexWrap: 'wrap' }}>
              <div>
                <strong>Input Features (X)</strong>
                <ul>
                  {activeSummary.x_cols.map((c) => (
                    <li key={c}>
                      <code>{c}</code>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <strong>Target Features (Y)</strong>
                <ul>
                  {activeSummary.y_cols.map((c) => (
                    <li key={c}>
                      <code>{c}</code>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}
      </section>

      <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: 1, minWidth: 340 }}>
          <h2 style={{ fontSize: '1.15rem', marginBottom: '0.75rem' }}>📦 Datasets in Database</h2>
          <DataTable
            keyFn={(d) => d.name}
            maxVisibleRows={5}
            emptyMessage="No datasets stored yet."
            rows={datasets}
            columns={[
              { header: 'Name', render: (d) => d.name },
              { header: 'Uploaded', render: (d) => d.uploaded_at },
              { header: 'Rows', render: (d) => d.rows },
              { header: 'Cols', render: (d) => d.cols },
            ]}
          />
        </div>
        <div style={{ flex: 1, minWidth: 340 }}>
          <h2 style={{ fontSize: '1.15rem', marginBottom: '0.75rem' }}>💾 Saved Models</h2>
          <DataTable<SavedModelSummary>
            keyFn={(m) => m.name}
            emptyMessage="No models saved yet."
            rows={savedModels}
            columns={[
              { header: 'Name', render: (m) => m.name },
              { header: 'Algorithm', render: (m) => m.algorithm ?? '—' },
              { header: 'Saved At', render: (m) => m.saved_at },
              { header: 'Train R²', render: (m) => (m.train_r2 != null ? m.train_r2.toFixed(3) : '—') },
              { header: 'Test R²', render: (m) => (m.avg_r2 != null ? m.avg_r2.toFixed(3) : '—') },
            ]}
          />
        </div>
      </div>

      <WorkflowGuide />

      <div>
        <button onClick={() => navigate('/upload')}>Continue to Connect Data →</button>
      </div>
    </div>
  )
}
