import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SimulationOverridesPanel } from './SimulationOverridesPanel'

// Plain presentational component (no data-fetching) -- tested directly with
// realistic minimal props per the empty-state and populated-state branches.
describe('SimulationOverridesPanel', () => {
  it('empty-tags early return: heading has no emoji prefix', () => {
    render(
      <SimulationOverridesPanel tags={[]} limits={{}} overrides={{}} onChange={vi.fn()} onReset={vi.fn()} />,
    )
    const heading = screen.getByRole('heading', { name: 'Simulation Overrides' })
    expect(heading).toBeInTheDocument()
    expect(heading.textContent).toBe('Simulation Overrides')
  })

  it('main render: heading and filter placeholder drop 🔧/🔍, Reset All keeps its ↺ affordance', () => {
    const tags = ['tag_a', 'tag_b', 'tag_c', 'tag_d', 'tag_e', 'tag_f', 'tag_g']
    render(
      <SimulationOverridesPanel
        tags={tags}
        limits={{}}
        overrides={{ tag_a: '5' }}
        onChange={vi.fn()}
        onReset={vi.fn()}
      />,
    )

    const heading = screen.getByRole('heading', { name: /Simulation Overrides/ })
    expect(heading.textContent).not.toContain('🔧')
    expect(heading.textContent).toContain('Simulation Overrides')

    const filterInput = screen.getByPlaceholderText('Filter tags by name…')
    expect(filterInput).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/🔍/)).not.toBeInTheDocument()

    // Reset All's ↺ is a scope-boundary status/affordance icon, not a
    // decorative title icon -- it must remain untouched.
    const resetButton = screen.getByRole('button', { name: /Reset All/ })
    expect(resetButton.textContent).toContain('↺')
  })
})
