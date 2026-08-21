import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { extractErrorMessage } from '../../api/errors'
import { uploadConfig } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import type { WhatIfConfigStatus } from '../../api/types'

interface ConfigSourceStatusProps {
  status: WhatIfConfigStatus | undefined
  onUploaded: () => void
}

// Every query key a full Config_file.xlsx upload can affect — all 8 sheets
// are now surfaced as their own live tabs across System/Model/What-If
// Config, so an upload has to refresh all of them, not just PI/Model mapping.
const CONFIG_QUERY_KEYS = [
  'whatif-config-status',
  'whatif-pi-mapping',
  'whatif-model-mapping',
  'whatif-detected-counts',
  'whatif-section-order',
  'whatif-mvdvcv',
  'whatif-constraints',
  'whatif-user-inputs',
  'whatif-column-order',
  'whatif-target-section',
  'whatif-models-status',
]

export function ConfigSourceStatus({ status, onUploaded }: ConfigSourceStatusProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const uploadMutation = useMutation({
    mutationFn: uploadConfig,
    onSuccess: () => {
      for (const key of CONFIG_QUERY_KEYS) queryClient.invalidateQueries({ queryKey: [key] })
      onUploaded()
    },
  })

  const piOk = !!status?.pi_mapping_present
  const modelOk = !!status?.model_details_present

  return (
    <div className="card" style={{ padding: '1.5rem' }}>
      <h3 style={{ marginTop: 0, marginBottom: '1rem' }}>🗂️ Configuration Source</h3>

      {piOk || modelOk ? (
        <Callout variant="success">
          Config auto-loaded from disk — PI Tag Mapping: {piOk ? status!.pi_mapping_row_count : 'missing'} · Model
          Mapping: {modelOk ? status!.model_details_row_count : 'missing'}
        </Callout>
      ) : (
        <Callout variant="warning">
          No Config_file.xlsx found under Data/. Use the optional upload below, or place the file on disk and
          reload.
        </Callout>
      )}

      <div style={{ marginTop: '1rem' }}>
        <button className="chip" onClick={() => setOpen((o) => !o)}>
          {open ? '▲' : '▼'} Optional: upload a config workbook to override
        </button>
        {open && (
          <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <input ref={fileRef} type="file" accept=".xlsx" />
            <button
              disabled={uploadMutation.isPending}
              onClick={() => {
                const file = fileRef.current?.files?.[0]
                if (file) uploadMutation.mutate(file)
              }}
            >
              {uploadMutation.isPending ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        )}
        {uploadMutation.isSuccess && (
          <div style={{ marginTop: '0.5rem' }}>
            <Callout variant="success">Config workbook uploaded and now in effect.</Callout>
          </div>
        )}
        {uploadMutation.isError && (
          <div style={{ marginTop: '0.5rem' }}>
            <Callout variant="error">
              {extractErrorMessage(uploadMutation.error, 'Could not parse the workbook.')}
            </Callout>
          </div>
        )}
      </div>
    </div>
  )
}
