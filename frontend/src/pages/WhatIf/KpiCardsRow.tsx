import { memo, useState } from 'react'
import { formatMetric } from '../../utils/formatMetric'
import type { WhatIfKpi } from '../../api/types'

// Status color is reserved for the direction of change and always paired
// with an explicit ▲/▼ glyph + text, never color alone (a red/green-blind
// reader must still be able to tell increase from decrease at a glance).
function statusFor(change: number): { text: string; bg: string; glyph: string } {
  if (change > 0) return { text: 'var(--success-text)', bg: 'var(--success-bg)', glyph: '▲' }
  if (change < 0) return { text: 'var(--error-text)', bg: 'var(--error-bg)', glyph: '▼' }
  return { text: 'var(--text-caption)', bg: 'var(--bg-subtle)', glyph: '–' }
}

function WhatIfKpiCard({ kpi }: { kpi: WhatIfKpi }) {
  const status = statusFor(kpi.change)
  return (
    <div
      className="status-card"
      style={{
        borderTop: `3px solid ${status.text}`,
        display: 'flex',
        flexDirection: 'column',
        gap: '0.35rem',
        padding: '0.75rem 0.9rem',
      }}
    >
      <div
        className="caption"
        title={kpi.tag}
        style={{
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
          fontWeight: 600,
          lineHeight: 1.25,
          fontSize: '0.78rem',
          minHeight: '2em',
        }}
      >
        {kpi.tag.replace(/_/g, ' ')}
      </div>
      <div className="metric-value" style={{ fontSize: '1.15rem' }}>
        {formatMetric(kpi.estimated)}
      </div>
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.25rem',
          alignSelf: 'flex-start',
          background: status.bg,
          color: status.text,
          fontWeight: 700,
          fontSize: '0.72rem',
          padding: '0.1rem 0.45rem',
          borderRadius: 999,
        }}
      >
        <span aria-hidden>{status.glyph}</span>
        {formatMetric(kpi.change, { forceSign: true })}
      </div>
      <div className="caption" style={{ fontSize: '0.72rem' }}>
        vs. baseline {formatMetric(kpi.actual)}
      </div>
    </div>
  )
}

// Memoized alongside ActualVsEstimatedTable/ValidationFiltersPanel — see
// ValidationFiltersPanel.tsx's docstring for why this matters.
export const KpiCardsRow = memo(function KpiCardsRow({ kpis }: { kpis: WhatIfKpi[] }) {
  // Starts collapsed — the grid can run to two dozen+ tiles, and the more
  // immediately useful view after a compute is the Actual vs Estimated
  // table right below it, not a wall of cards. Purely manual after that —
  // it does not re-open itself on a later compute.
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')

  // The backend derives this set from the live config (predicted parameters
  // + constrained parameters + the plant plug-in's KPI_PARAMETERS) — see
  // src/whatif/kpi.py::derive_kpi_tags. No client-side tag whitelist here;
  // whatever the backend returns, in the order it returns it, is shown.
  if (kpis.length === 0) return null

  const visibleKpis = filter.trim()
    ? kpis.filter((k) => k.tag.toLowerCase().includes(filter.trim().toLowerCase()))
    : kpis

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <button className="chip" onClick={() => setOpen((o) => !o)}>
          {open ? '▲' : '▼'} Key Performance Indicators ({kpis.length})
        </button>
        {open && kpis.length > 8 && (
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter KPIs…"
            style={{ maxWidth: 240 }}
          />
        )}
      </div>
      {open && (
        <>
          {filter.trim() && (
            <p className="caption" style={{ marginTop: '0.4rem' }}>
              {visibleKpis.length} of {kpis.length} match.
            </p>
          )}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))',
              gap: '0.6rem',
              marginTop: '0.75rem',
            }}
          >
            {visibleKpis.map((kpi) => (
              <WhatIfKpiCard key={kpi.tag} kpi={kpi} />
            ))}
            {visibleKpis.length === 0 && <p className="caption">No KPIs match "{filter}".</p>}
          </div>
        </>
      )}
    </div>
  )
})
