import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  downloadBlob,
  exportFullConfig,
  getColumnOrder,
  getConfigStatus,
  getConstraints,
  getModelMapping,
  getModelsStatus,
  getMvDvCvTaglist,
  getPiMapping,
  getSectionOrder,
  getUserInputs,
  saveConfig,
} from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { Tabs } from '../../components/Tabs'
import { useActiveWhatIf } from '../../state/ActiveWhatIfContext'
import { ConfigSourceStatus } from './ConfigSourceStatus'
import { ModelConfigTab } from './ModelConfigTab'
import { SystemConfigTab } from './SystemConfigTab'
import { WhatIfConfigTab } from './WhatIfConfigTab'

// What-If Setup — replaces the old 11-step vertical wizard with 3 logical,
// horizontally-tabbed configuration sections (System Config / Model Config
// / What-If Config), matching the module's guided-but-non-linear redesign.
// All underlying editors/logic are reused as-is; only the surrounding shell
// changed (no more Back/Save & Continue step gating).
export function WhatIfSetupPage() {
  const queryClient = useQueryClient()
  const { targetSection } = useActiveWhatIf()
  const [primaryTab, setPrimaryTab] = useState(0)

  const configStatusQuery = useQuery({ queryKey: ['whatif-config-status'], queryFn: getConfigStatus })
  const modelStatusQuery = useQuery({ queryKey: ['whatif-models-status'], queryFn: getModelsStatus })
  const sectionOrderQuery = useQuery({ queryKey: ['whatif-section-order'], queryFn: getSectionOrder })
  const modelMappingQuery = useQuery({ queryKey: ['whatif-model-mapping'], queryFn: getModelMapping })
  const constraintsQuery = useQuery({ queryKey: ['whatif-constraints'], queryFn: getConstraints })
  const userInputsQuery = useQuery({ queryKey: ['whatif-user-inputs'], queryFn: getUserInputs })
  const columnOrderQuery = useQuery({ queryKey: ['whatif-column-order'], queryFn: getColumnOrder })

  const sectionOrderList = (sectionOrderQuery.data ?? []).map((r) => r.Section?.trim() ?? '').filter(Boolean)
  const distinctSectionCount = new Set(sectionOrderList.map((s) => s.toLowerCase())).size
  const processOrderComplete = sectionOrderList.length >= 2 && distinctSectionCount === sectionOrderList.length
  const systemConfigComplete = processOrderComplete && !!configStatusQuery.data?.pi_mapping_present

  const modelMappingComplete = (modelMappingQuery.data?.rows ?? []).some(
    (r) => (r['Predicted parameter'] ?? '').trim() !== '',
  )
  const modelConfigComplete = modelMappingComplete && !!modelStatusQuery.data?.all_present

  // What-If Config's 3 sub-sections are all optional (unlike System/Model
  // Config, which gate on required fields) — so "complete" here means "at
  // least one of them has been configured," not "all three."
  const whatIfConfigComplete =
    (constraintsQuery.data ?? []).length > 0 ||
    (userInputsQuery.data ?? []).length > 0 ||
    (columnOrderQuery.data ?? []).length > 0

  async function buildFullConfigPayload() {
    const [pi, model, secOrder, mvdvcv, constraints, userInputs, colOrder] = await Promise.all([
      queryClient.ensureQueryData({ queryKey: ['whatif-pi-mapping'], queryFn: getPiMapping }),
      queryClient.ensureQueryData({ queryKey: ['whatif-model-mapping'], queryFn: getModelMapping }),
      queryClient.ensureQueryData({ queryKey: ['whatif-section-order'], queryFn: getSectionOrder }),
      queryClient.ensureQueryData({ queryKey: ['whatif-mvdvcv'], queryFn: getMvDvCvTaglist }),
      queryClient.ensureQueryData({ queryKey: ['whatif-constraints'], queryFn: getConstraints }),
      queryClient.ensureQueryData({ queryKey: ['whatif-user-inputs'], queryFn: getUserInputs }),
      queryClient.ensureQueryData({ queryKey: ['whatif-column-order'], queryFn: getColumnOrder }),
    ])
    return {
      pi_mapping_rows: pi,
      model_details_rows: model.rows,
      constraints_rows: constraints,
      user_inputs_rows: userInputs,
      display_order_rows: colOrder,
      section_order_rows: secOrder,
      mvdvcv_rows: mvdvcv,
      target_section: targetSection,
    }
  }

  const saveConfigMutation = useMutation({
    mutationFn: async () => saveConfig(await buildFullConfigPayload()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['whatif-config-status'] }),
  })

  const downloadConfigMutation = useMutation({
    mutationFn: async () => {
      const blob = await exportFullConfig(await buildFullConfigPayload())
      downloadBlob(blob, 'Config_file.xlsx')
    },
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div>
        <h1>What-If Setup</h1>
        <p className="caption">
          Configure the plant structure, models, and optional scenario rules — organized into three sections below.
        </p>
      </div>

      <ConfigSourceStatus status={configStatusQuery.data} onUploaded={() => {}} />

      <div className="card" style={{ padding: '1.5rem' }}>
        <Tabs
          activeIndex={primaryTab}
          onChange={setPrimaryTab}
          tabs={[
            {
              label: 'System Config',
              complete: systemConfigComplete,
              content: <SystemConfigTab onSaved={() => setPrimaryTab(1)} />,
            },
            { label: 'Model Config', complete: modelConfigComplete, content: <ModelConfigTab /> },
            { label: 'What-If Config', complete: whatIfConfigComplete, content: <WhatIfConfigTab /> },
          ]}
        />
      </div>

      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <button onClick={() => saveConfigMutation.mutate()} disabled={saveConfigMutation.isPending}>
          {saveConfigMutation.isPending ? 'Saving…' : '💾 Save Configuration to Server'}
        </button>
        <button
          className="chip"
          onClick={() => downloadConfigMutation.mutate()}
          disabled={downloadConfigMutation.isPending}
        >
          {downloadConfigMutation.isPending ? 'Preparing…' : '📥 Download Current Configuration'}
        </button>
        {saveConfigMutation.isSuccess && <span className="caption">Saved to Config_file.xlsx.</span>}
        {saveConfigMutation.isError && <span className="caption">Failed to save configuration.</span>}
        {downloadConfigMutation.isError && <span className="caption">Failed to prepare the download.</span>}
      </div>

      {!systemConfigComplete && (
        <Callout variant="info">
          Complete System Config (Process Flow Order + PI Tag Mapping) to unlock scoped dropdowns across the rest of
          setup.
        </Callout>
      )}
    </div>
  )
}
