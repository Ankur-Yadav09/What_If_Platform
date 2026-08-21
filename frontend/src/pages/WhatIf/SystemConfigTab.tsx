import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  commitMapping,
  generateMapping,
  getDetectedCounts,
  getMvDvCvTaglist,
  getPiMapping,
  getSectionOrder,
} from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { Tabs } from '../../components/Tabs'
import { useActiveWhatIf } from '../../state/ActiveWhatIfContext'
import { allowedSet } from './caseSetupHelpers'
import { MappingPreviewGrid } from './MappingPreviewGrid'
import { MvDvCvTagListEditor } from './MvDvCvTagListEditor'
import { PiTagMappingEditor } from './PiTagMappingEditor'
import { PlantConfigWizard } from './PlantConfigWizard'
import { SectionOrderEditor } from './SectionOrderEditor'
import { TargetSectionSelector } from './TargetSectionSelector'
import type { ModelDetailsRow, PiMappingRow } from '../../api/types'

interface SystemConfigTabProps {
  /** Called after the last sub-tab (Input Tag Configuration) saves — lets
   * the parent's primary tab strip (WhatIfSetupPage) advance to Model
   * Config automatically. Completion badges are still computed independently
   * in WhatIfSetupPage from the same shared react-query cache; this callback
   * only drives the one-time "which sub-tab was just saved" navigation. */
  onSaved?: () => void
}

// "System Config" section of What-If Setup — the plant's process structure
// and input tags, as 3 horizontal sub-tabs instead of separate vertical
// wizard steps: Process Flow Order, PI Tag Mapping, Input Tag Configuration
// (MV/DV/CV). Completion badges for the parent's primary tabs are computed
// independently in WhatIfSetupPage.tsx from the same shared react-query
// cache — this component doesn't report status up via a callback (that would
// mean calling a parent state setter during render, which React disallows).
export function SystemConfigTab({ onSaved }: SystemConfigTabProps = {}) {
  const queryClient = useQueryClient()
  const { targetSection, setTargetSection } = useActiveWhatIf()
  const [tab, setTab] = useState(0)
  const [generatorOpen, setGeneratorOpen] = useState(false)
  const [mappingRows, setMappingRows] = useState<PiMappingRow[]>([])
  const [sectionCounts, setSectionCounts] = useState<Record<string, number>>({})

  const sectionOrderQuery = useQuery({ queryKey: ['whatif-section-order'], queryFn: getSectionOrder })
  const piMappingQuery = useQuery({ queryKey: ['whatif-pi-mapping'], queryFn: getPiMapping })
  const mvdvcvQuery = useQuery({ queryKey: ['whatif-mvdvcv'], queryFn: getMvDvCvTaglist })
  const detectedCountsQuery = useQuery({ queryKey: ['whatif-detected-counts'], queryFn: getDetectedCounts })
  const modelMappingRows: ModelDetailsRow[] = [] // export-only context, not needed for this tab's own grid

  const sectionOrderList = (sectionOrderQuery.data ?? []).map((r) => r.Section?.trim() ?? '').filter(Boolean)
  const allowed = allowedSet(sectionOrderList, targetSection)

  const distinctSectionCount = new Set(sectionOrderList.map((s) => s.toLowerCase())).size
  const processOrderComplete = sectionOrderList.length >= 2 && distinctSectionCount === sectionOrderList.length
  const piMappingComplete = (piMappingQuery.data ?? []).length > 0

  const generateMutation = useMutation({
    mutationFn: generateMapping,
    onSuccess: (res) => {
      setMappingRows(res.rows)
      setSectionCounts(res.section_counts)
    },
  })

  const commitMutation = useMutation({
    mutationFn: commitMapping,
    onSuccess: (rows) => {
      setMappingRows(rows)
      queryClient.setQueryData(['whatif-pi-mapping'], rows)
    },
  })

  return (
    <Tabs
      activeIndex={tab}
      onChange={setTab}
      tabs={[
        {
          label: 'Process Flow Order',
          complete: processOrderComplete,
          content: (
            <div>
              <p className="caption">
                Enter plant sections in actual process order (e.g. Furnace → Quench → CGC → PRC → ERC → Cold), then
                pick which section this case currently targets.
              </p>
              <SectionOrderEditor onSaved={() => setTab(1)} />
              <div style={{ marginTop: '1.5rem', paddingTop: '1.25rem', borderTop: '1px solid var(--border)' }}>
                <TargetSectionSelector value={targetSection} onChange={setTargetSection} />
              </div>
            </div>
          ),
        },
        {
          label: 'PI Tag Mapping',
          complete: piMappingComplete,
          content: (
            <div>
              <details open={generatorOpen} onToggle={(e) => setGeneratorOpen(e.currentTarget.open)}>
                <summary style={{ cursor: 'pointer', fontWeight: 600, marginBottom: '0.75rem' }}>
                  🧙 Generate from plant line-up (optional)
                </summary>
                <div className="card" style={{ padding: '1.25rem', marginBottom: '1.25rem' }}>
                  <PlantConfigWizard
                    detectedCounts={detectedCountsQuery.data}
                    generating={generateMutation.isPending}
                    onReset={() => {
                      setMappingRows([])
                      setSectionCounts({})
                    }}
                    onGenerate={(counts) => generateMutation.mutate(counts)}
                  />
                  {generateMutation.isError && (
                    <div style={{ marginTop: '1rem' }}>
                      <Callout variant="error">Failed to generate the PI mapping for this line-up.</Callout>
                    </div>
                  )}
                  <div style={{ marginTop: '1.25rem' }}>
                    <MappingPreviewGrid
                      rows={mappingRows}
                      onChange={setMappingRows}
                      onCommit={() => commitMutation.mutate(mappingRows)}
                      modelDetailsRows={modelMappingRows}
                      sectionCounts={sectionCounts}
                    />
                  </div>
                </div>
              </details>
              <PiTagMappingEditor
                allowed={allowed}
                sectionOptions={['', ...sectionOrderList]}
                onSaved={() => setTab(2)}
              />
            </div>
          ),
        },
        {
          label: 'Input Tag Configuration (MV/DV/CV)',
          complete: (mvdvcvQuery.data ?? []).length > 0,
          content: (
            <div>
              <p className="caption">
                Optional: Manipulated/Disturbance/Controlled variable tags — prioritized as an input-tag source ahead
                of the general PI Tag Mapping list when configuring model inputs.
              </p>
              <MvDvCvTagListEditor
                allowed={allowed}
                sectionOptions={['', ...sectionOrderList]}
                onSaved={onSaved}
              />
              <p className="caption" style={{ marginTop: '0.5rem' }}>
                {(mvdvcvQuery.data ?? []).length} tag(s) configured.
              </p>
            </div>
          ),
        },
      ]}
    />
  )
}
