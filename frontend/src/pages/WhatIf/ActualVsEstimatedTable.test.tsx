import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ActualVsEstimatedTable } from './ActualVsEstimatedTable'
import type { WhatIfScenarioRow } from '../../api/types'

vi.mock('../../api/whatIf', () => ({
  downloadBlob: vi.fn(),
}))

// >8 rows so the filter input (with its own emoji placeholder) actually renders.
const rows: WhatIfScenarioRow[] = Array.from({ length: 9 }, (_, i) => ({
  parameter: `param_${i}`,
  actual: i,
  estimated: i + 0.5,
  change: 0.5,
}))

describe('ActualVsEstimatedTable', () => {
  it('drops the 📈 heading emoji and the 🔍 filter placeholder emoji, keeping the plain text', () => {
    render(<ActualVsEstimatedTable timestamp="2025-01-22 10:00:00" rows={rows} />)

    const heading = screen.getByRole('heading', { name: 'Actual vs Estimated Scenario Output' })
    expect(heading).toBeInTheDocument()
    expect(heading.textContent).not.toContain('📈')

    const filterInput = screen.getByPlaceholderText('Filter parameters…')
    expect(filterInput).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/🔍/)).not.toBeInTheDocument()
  })

  it('drops the 📥 emoji from the export button label', () => {
    render(<ActualVsEstimatedTable timestamp="2025-01-22 10:00:00" rows={rows} />)
    const exportButton = screen.getByRole('button', { name: 'Export Baseline vs Simulation Matrix (.CSV)' })
    expect(exportButton).toBeInTheDocument()
    expect(exportButton.textContent).not.toContain('📥')
  })
})
