import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TimestampSelector } from './TimestampSelector'

vi.mock('../../api/whatIf', () => ({
  getDates: vi.fn().mockResolvedValue(['2025-01-22']),
  getTimestamps: vi.fn().mockResolvedValue(['2025-01-22 10:00:00']),
}))

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('TimestampSelector', () => {
  it('renders the confirmed snapshot label with no 🗓️ emoji prefix', () => {
    renderWithClient(
      <TimestampSelector
        selectedDate="2025-01-22"
        onDateChange={vi.fn()}
        selectedTimestamp="2025-01-22 10:00:00"
        onTimestampChange={vi.fn()}
      />,
    )

    const label = screen.getByText('22 Jan 2025, 10:00:00')
    expect(label).toBeInTheDocument()
    expect(label.textContent).not.toContain('🗓️')
  })
})
