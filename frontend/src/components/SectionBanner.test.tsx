import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SectionBanner } from './SectionBanner'

// SectionBanner.icon went from required to optional (icon?: string). The
// icon <span> must render only when a truthy icon is passed (Feature
// Selection / Preprocess pages still pass one) and must be omitted entirely
// when it isn't (What-If Analysis's banner) -- per the DoD, those other 6
// call sites must keep rendering their icon unchanged.
describe('SectionBanner', () => {
  it('renders the icon span when an icon prop is provided', () => {
    render(
      <SectionBanner icon="🎯" title="Target Variable Selection" subtitle="Pick the variables to predict." />,
    )
    const icon = screen.getByText('🎯')
    expect(icon).toBeInTheDocument()
    expect(icon.tagName).toBe('SPAN')
    expect(icon).toHaveClass('icon')
    expect(screen.getByRole('heading', { name: 'Target Variable Selection' })).toBeInTheDocument()
    expect(screen.getByText('Pick the variables to predict.')).toBeInTheDocument()
  })

  it('renders no icon span at all when icon is omitted', () => {
    const { container } = render(
      <SectionBanner
        title="What-If Analysis"
        subtitle="Simulate hypothetical process scenarios against your configured predictive models."
      />,
    )
    expect(container.querySelector('span.icon')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What-If Analysis' })).toBeInTheDocument()
    expect(
      screen.getByText('Simulate hypothetical process scenarios against your configured predictive models.'),
    ).toBeInTheDocument()
  })
})
