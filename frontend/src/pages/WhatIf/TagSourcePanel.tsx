import { memo } from 'react'
import { MultiSelectDropdown } from '../../components/MultiSelectDropdown'
import type { TagOptionsResult } from '../../api/types'

interface TagSourcePanelProps {
  tagOptions: TagOptionsResult | undefined
  selectedTags: Set<string>
  onChange: (tags: Set<string>) => void
}

const SOURCE_LABEL: Record<string, string> = {
  wizard: '⚡ Tag Source: Wizard Mapping',
  config: '📋 Tag Source: Config Sheet',
  historian: '🏷️ Dynamic Tag Selection',
}

// Memoized alongside ActualVsEstimatedTable/ValidationFiltersPanel — see
// ValidationFiltersPanel.tsx's docstring for why this matters.
export const TagSourcePanel = memo(function TagSourcePanel({ tagOptions, selectedTags, onChange }: TagSourcePanelProps) {
  if (!tagOptions) return <p className="caption">Loading tag source…</p>

  return (
    <div>
      <h4>{SOURCE_LABEL[tagOptions.source]}</h4>
      {tagOptions.source === 'config' ? (
        <p className="caption">Using the {tagOptions.tags.length} tags defined in the config "user inputs" sheet.</p>
      ) : (
        <>
          <MultiSelectDropdown
            options={tagOptions.source === 'wizard' ? tagOptions.tags : tagOptions.all_tags}
            selected={selectedTags}
            onChange={onChange}
            placeholder={tagOptions.source === 'wizard' ? 'Generated tags (from plant line-up)' : 'User defined inputs'}
          />
          {selectedTags.size === 0 && (
            <p className="caption" style={{ marginTop: '0.5rem' }}>
              {tagOptions.source === 'wizard'
                ? "A wizard-generated mapping is active. Pick tags above — override inputs will appear below."
                : 'No configuration found. Select process tags to simulate scenarios manually.'}
            </p>
          )}
        </>
      )}
    </div>
  )
})
