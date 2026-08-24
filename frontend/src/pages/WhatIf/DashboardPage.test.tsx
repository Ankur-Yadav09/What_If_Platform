import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { DashboardPage } from './DashboardPage'
import { ActiveWhatIfProvider } from '../../state/ActiveWhatIfContext'
import {
  getConfigStatus,
  getModelsStatus,
  getTagOptions,
  getTargetSection,
  getDates,
} from '../../api/whatIf'

vi.mock('../../api/whatIf', () => ({
  getConfigStatus: vi.fn(),
  getModelsStatus: vi.fn(),
  getTagOptions: vi.fn(),
  getTargetSection: vi.fn(),
  getDates: vi.fn(),
  getTimestamps: vi.fn().mockResolvedValue([]),
  getBaseline: vi.fn().mockResolvedValue({}),
  runScenario: vi.fn(),
  runValidationFilter: vi.fn().mockResolvedValue({ rows: [], match_count: 0 }),
  exportScenarioCsv: vi.fn(),
  downloadBlob: vi.fn(),
}))

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ActiveWhatIfProvider>
          <DashboardPage />
        </ActiveWhatIfProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DashboardPage', () => {
  it('gate-not-ready state: "What-If Analysis" banner renders with no 📊 icon span, lock callout keeps its 🔒', async () => {
    vi.mocked(getConfigStatus).mockResolvedValue({
      pi_mapping_present: false,
      pi_mapping_row_count: 0,
      model_details_present: false,
      model_details_row_count: 0,
      source_path: null,
    })
    vi.mocked(getModelsStatus).mockResolvedValue({
      all_present: false,
      tags_ok: [],
      tags_missing: [],
      pkl_count: 0,
      required_pkl_count: 0,
      raw_sim_present: false,
      training_data_present: false,
      model_mapping_filled: false,
      can_train: false,
      train_blockers: [],
      training_required: false,
    })

    const { container } = renderPage()

    const heading = await screen.findByRole('heading', { name: 'What-If Analysis' })
    expect(heading).toBeInTheDocument()
    expect(container.querySelector('.section-banner span.icon')).not.toBeInTheDocument()

    // The 🔒 in the lock callout is a semantic/status icon, out of this
    // feature's scope -- it must remain untouched.
    expect(screen.getByText(/Simulation overrides are locked/).closest('div')?.textContent).toContain('🔒')
  })

  it('unlocked state: SectionBanner and card headings render with no decorative emoji, Compute button drops 🚀', async () => {
    vi.mocked(getConfigStatus).mockResolvedValue({
      pi_mapping_present: true,
      pi_mapping_row_count: 5,
      model_details_present: true,
      model_details_row_count: 5,
      source_path: '/some/path.xlsx',
    })
    vi.mocked(getModelsStatus).mockResolvedValue({
      all_present: true,
      tags_ok: ['a'],
      tags_missing: [],
      pkl_count: 1,
      required_pkl_count: 1,
      raw_sim_present: true,
      training_data_present: true,
      model_mapping_filled: true,
      can_train: true,
      train_blockers: [],
      training_required: false,
    })
    vi.mocked(getTagOptions).mockResolvedValue({
      tags: [],
      all_tags: [],
      source: 'wizard',
      limits: {},
    })
    vi.mocked(getTargetSection).mockResolvedValue({
      section_order: ['Section A', 'Section B'],
      target_section: 'Section B',
      active_scope: ['Section A', 'Section B'],
      excluded_sections: [],
    })
    vi.mocked(getDates).mockResolvedValue([])

    renderPage()

    const banner = await screen.findByRole('heading', { name: 'What-If Analysis' })
    expect(within(banner.closest('.section-banner') as HTMLElement).queryByText(/📊/)).not.toBeInTheDocument()

    expect(await screen.findByRole('heading', { name: 'Target Section' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Tag Source' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Baseline Process Snapshot' })).toBeInTheDocument()

    const computeButton = screen.getByRole('button', { name: /Compute What-If Scenario/ })
    expect(computeButton.textContent).not.toContain('🚀')
    expect(computeButton.textContent).toContain('Compute What-If Scenario (0 overrides active)')
  })
})
