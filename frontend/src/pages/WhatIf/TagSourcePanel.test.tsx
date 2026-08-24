import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TagSourcePanel } from './TagSourcePanel'
import type { TagOptionsResult } from '../../api/types'

// Plain presentational component (tagOptions passed as a prop, no
// data-fetching of its own) -- tested directly with realistic minimal props
// for all three SOURCE_LABEL entries.
describe('TagSourcePanel', () => {
  it('shows "Tag Source: Wizard Mapping" with no ⚡ emoji', () => {
    const tagOptions: TagOptionsResult = { tags: ['a', 'b'], all_tags: ['a', 'b'], source: 'wizard', limits: {} }
    render(<TagSourcePanel tagOptions={tagOptions} selectedTags={new Set()} onChange={vi.fn()} />)
    const label = screen.getByRole('heading', { name: 'Tag Source: Wizard Mapping', level: 4 })
    expect(label.textContent).toBe('Tag Source: Wizard Mapping')
  })

  it('shows "Tag Source: Config Sheet" with no 📋 emoji', () => {
    const tagOptions: TagOptionsResult = { tags: ['a'], all_tags: ['a'], source: 'config', limits: {} }
    render(<TagSourcePanel tagOptions={tagOptions} selectedTags={new Set()} onChange={vi.fn()} />)
    const label = screen.getByRole('heading', { name: 'Tag Source: Config Sheet', level: 4 })
    expect(label.textContent).toBe('Tag Source: Config Sheet')
  })

  it('shows "Dynamic Tag Selection" with no 🏷️ emoji', () => {
    const tagOptions: TagOptionsResult = { tags: [], all_tags: ['a', 'b', 'c'], source: 'historian', limits: {} }
    render(<TagSourcePanel tagOptions={tagOptions} selectedTags={new Set()} onChange={vi.fn()} />)
    const label = screen.getByRole('heading', { name: 'Dynamic Tag Selection', level: 4 })
    expect(label.textContent).toBe('Dynamic Tag Selection')
  })
})
