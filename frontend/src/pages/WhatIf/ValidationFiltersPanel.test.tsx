import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ValidationFiltersPanel } from './ValidationFiltersPanel'

vi.mock('../../api/whatIf', () => ({
  runValidationFilter: vi.fn().mockResolvedValue({
    rows: [{ Timestamp: '2025-01-22T10:00:00.000', tag_1: 1, tag_2: 2, tag_3: 3, tag_4: 4, tag_5: 5, tag_6: 6, tag_7: 7 }],
    match_count: 1,
  }),
  downloadBlob: vi.fn(),
  exportScenarioCsv: vi.fn(),
}))

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('ValidationFiltersPanel', () => {
  it('drops the 🔍 emoji from the summary label and the results heading/placeholder/export button', async () => {
    renderWithClient(<ValidationFiltersPanel timestamp="2025-01-22 10:00:00" scenarioRows={[]} targetSection={null} />)

    const summary = screen.getByText(/Validation Filters — compare this scenario/)
    expect(summary.textContent).not.toContain('🔍')
    expect(summary.textContent).toBe(
      'Validation Filters — compare this scenario against similar historical snapshots (optional)',
    )

    const heading = await screen.findByRole('heading', { name: 'Correlated Historical Validation Sets', level: 4 })
    expect(heading.textContent).not.toContain('🔍')

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Find a parameter…')).toBeInTheDocument()
    })
    expect(screen.queryByPlaceholderText(/🔍/)).not.toBeInTheDocument()

    // The mocked runValidationFilter result has a non-empty rows array, so
    // the export goes through the combined-workbook (.xlsx) path -- see
    // exportScenarioCsv's docstring in api/whatIf.ts.
    const exportButton = screen.getByRole('button', {
      name: 'Export Unified Comparison & Historical Validation Data (.XLSX)',
    })
    expect(exportButton.textContent).not.toContain('📥')
  })
})
