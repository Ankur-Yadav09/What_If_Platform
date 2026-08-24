import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BaselineValuesPanel } from './BaselineValuesPanel'

vi.mock('../../api/whatIf', () => ({
  getBaseline: vi.fn().mockResolvedValue({}),
}))

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Toggle button label lost its leading "🔎 " but kept the ▲/▼ caret
// affordance (in-scope decorative emoji removed, out-of-scope status glyph
// left alone).
describe('BaselineValuesPanel', () => {
  it('renders the toggle label without the 🔎 emoji, keeping the caret and plain text', () => {
    renderWithClient(<BaselineValuesPanel timestamp="" tags={[]} />)
    const button = screen.getByRole('button', { name: /Baseline Process Values at Selected Timestamp/ })
    expect(button).toBeInTheDocument()
    expect(button.textContent).not.toContain('🔎')
    expect(button.textContent).toMatch(/^[▲▼] Baseline Process Values at Selected Timestamp$/)
  })
})
