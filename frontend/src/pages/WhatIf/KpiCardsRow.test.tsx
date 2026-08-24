import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { KpiCardsRow } from './KpiCardsRow'
import type { WhatIfKpi } from '../../api/types'

// Plain presentational component (kpis passed as a prop, no data-fetching of
// its own) -- >8 kpis so the filter input (with its own emoji placeholder)
// renders once expanded.
const kpis: WhatIfKpi[] = Array.from({ length: 9 }, (_, i) => ({
  tag: `kpi_${i}`,
  actual: i,
  estimated: i + 1,
  change: 1,
}))

describe('KpiCardsRow', () => {
  it('drops the 📊 emoji from the toggle label but keeps the ▲/▼ caret', () => {
    render(<KpiCardsRow kpis={kpis} />)
    const toggle = screen.getByRole('button', { name: /Key Performance Indicators \(9\)/ })
    expect(toggle.textContent).not.toContain('📊')
    expect(toggle.textContent).toMatch(/^[▲▼] Key Performance Indicators \(9\)$/)
  })

  it('drops the 🔍 emoji from the filter placeholder once expanded', () => {
    render(<KpiCardsRow kpis={kpis} />)
    fireEvent.click(screen.getByRole('button', { name: /Key Performance Indicators \(9\)/ }))
    const filterInput = screen.getByPlaceholderText('Filter KPIs…')
    expect(filterInput).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/🔍/)).not.toBeInTheDocument()
  })

  it('drops the per-metric-type icon from each KPI tile', () => {
    // Tags deliberately match iconFor's old temp/pressure/flow keyword rules
    // (now removed) to confirm no icon sneaks back in for any of them.
    const typedKpis: WhatIfKpi[] = [
      { tag: 'reactor_temp_c', actual: 1, estimated: 2, change: 1 },
      { tag: 'line_pressure', actual: 1, estimated: 2, change: 1 },
      { tag: 'coolant_flow', actual: 1, estimated: 2, change: 1 },
    ]
    render(<KpiCardsRow kpis={typedKpis} />)
    fireEvent.click(screen.getByRole('button', { name: /Key Performance Indicators \(3\)/ }))
    expect(screen.getByTitle('reactor_temp_c').textContent).toBe('reactor temp c')
    expect(screen.getByTitle('line_pressure').textContent).toBe('line pressure')
    expect(screen.getByTitle('coolant_flow').textContent).toBe('coolant flow')
  })
})
