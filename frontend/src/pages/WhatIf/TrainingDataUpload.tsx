import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import { extractErrorMessage } from '../../api/errors'
import { uploadTrainingData } from '../../api/whatIf'
import { Callout } from '../../components/Callout'

// Case Setup wizard Step 5: upload the training workbook ('PI data' /
// 'Furnace data' sheets). Used only for (future) model retraining, not for
// running scenarios.
export function TrainingDataUpload() {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const uploadMutation = useMutation({
    mutationFn: uploadTrainingData,
    onSuccess: (result) => {
      if (result.saved) queryClient.invalidateQueries({ queryKey: ['whatif-models-status'] })
    },
  })

  return (
    <div>
      <p className="caption">
        Upload <code>DMC_Screen_tags_data.xlsx</code> — a single workbook containing both the "PI data" and "Furnace
        data" sheets.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.75rem' }}>
        <input ref={fileRef} type="file" accept=".xlsx,.xls" />
        <button
          disabled={uploadMutation.isPending}
          onClick={() => {
            const file = fileRef.current?.files?.[0]
            if (file) uploadMutation.mutate(file)
          }}
        >
          {uploadMutation.isPending ? 'Uploading…' : '💾 Save training dataset'}
        </button>
      </div>

      {uploadMutation.data && uploadMutation.data.saved && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="success">Training workbook saved — sheets found: {uploadMutation.data.sheets_found.join(', ')}</Callout>
        </div>
      )}
      {uploadMutation.data && !uploadMutation.data.saved && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="error">
            Missing required sheet(s): {uploadMutation.data.missing_sheets.join(', ')}. Found:{' '}
            {uploadMutation.data.sheets_found.join(', ')}
          </Callout>
        </div>
      )}
      {uploadMutation.isError && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="error">
            {extractErrorMessage(uploadMutation.error, 'Failed to read/save the training workbook.')}
          </Callout>
        </div>
      )}
    </div>
  )
}
