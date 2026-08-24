import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TargetSectionSelector } from './TargetSectionSelector'

vi.mock('../../api/whatIf', () => ({
  getTargetSection: vi.fn().mockResolvedValue({
    section_order: ['Section A', 'Section B', 'Section C'],
    target_section: 'Section C',
    active_scope: ['Section A', 'Section B', 'Section C'],
    excluded_sections: [],
  }),
}))

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('TargetSectionSelector', () => {
  it('shows the label with no 🎯 emoji once the section order loads', async () => {
    renderWithClient(<TargetSectionSelector value={null} onChange={vi.fn()} />)

    const label = await screen.findByText('Target Section (compute this section and everything upstream of it)')
    expect(label).toBeInTheDocument()
    expect(label.textContent).not.toContain('🎯')
  })
})
