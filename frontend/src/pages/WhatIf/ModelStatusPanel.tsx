import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { trainModels } from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { StatusCard } from '../../components/StatusCard'
import { StepHeading } from '../../components/StepHeading'
import { useJobPolling } from '../../hooks/useJobPolling'
import { AccuracySummaryPanel } from './AccuracySummaryPanel'
import type { WhatIfModelStatus, WhatIfTrainResult } from '../../api/types'

interface ModelStatusPanelProps {
  status: WhatIfModelStatus | undefined
  isLoading: boolean
  /** Same gate used elsewhere to unlock the What-If Dashboard/Analysis page — unchanged, only relocated here. */
  canProceed: boolean
  onProceed: () => void
}

export function ModelStatusPanel({ status, isLoading, canProceed, onProceed }: ModelStatusPanelProps) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const trainMutation = useMutation({ mutationFn: trainModels, onSuccess: setJobId })
  const jobQuery = useJobPolling(jobId)

  const isTraining = jobId !== null && jobQuery.data?.done !== true
  const trainResult = jobQuery.data?.status === 'done' ? (jobQuery.data.result as WhatIfTrainResult) : null

  useEffect(() => {
    if (jobQuery.data?.done) {
      queryClient.invalidateQueries({ queryKey: ['whatif-models-status'] })
      queryClient.invalidateQueries({ queryKey: ['whatif-accuracy-summary'] })
    }
  }, [jobQuery.data?.done, queryClient])

  function startTraining() {
    trainMutation.mutate()
  }

  const modelsReady = !!status && (status.raw_sim_present || status.all_present)

  return (
    <div className="card" style={{ padding: '1.5rem' }}>
      <StepHeading step={5} title="Step B — Trained Models" />

      {isLoading || !status ? (
        <p className="caption">Checking Results/Model for trained artifacts…</p>
      ) : isTraining ? (
        <p className="caption">
          ⏳ Training models — this can take several minutes; this step doesn't report incremental progress, so
          keep this tab open until it finishes.
        </p>
      ) : modelsReady ? (
        <Callout variant="success">
          <strong>Trained models detected</strong>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', marginTop: '0.35rem' }}>
            <div>{status.pkl_count} model files available</div>
            <div>
              {status.raw_sim_present ? 'Historical simulation dataset found' : 'Historical simulation dataset not found'}
            </div>
            <div>Training is not required</div>
          </div>
        </Callout>
      ) : (
        <>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <StatusCard
              label="Model artifacts found"
              value={`${status.pkl_count} / ${status.required_pkl_count} files`}
              tone="warning"
            />
            <StatusCard
              label="Tags ready"
              value={`${status.tags_ok.length} / ${status.tags_ok.length + status.tags_missing.length}`}
              sublabel={status.tags_missing.length ? `Missing: ${status.tags_missing.join(', ')}` : 'All tags ready'}
              tone="warning"
            />
          </div>
          <div style={{ marginTop: '1rem' }}>
            <Callout variant="warning">Before training, resolve: {status.train_blockers.join(' · ')}</Callout>
          </div>
        </>
      )}

      {!isLoading && status && !isTraining && (
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', flexWrap: 'wrap' }}>
          <button
            className={modelsReady ? 'chip' : undefined}
            disabled={(!modelsReady && !status.can_train) || trainMutation.isPending}
            onClick={startTraining}
          >
            {trainMutation.isPending
              ? 'Starting…'
              : modelsReady
                ? '🔁 Retrain Models'
                : '🧠 Train Models & Save .pkl files'}
          </button>
          {modelsReady && (
            <button disabled={!canProceed} onClick={onProceed}>
              🚀 Continue to Scenario Dashboard
            </button>
          )}
        </div>
      )}

      {modelsReady && !canProceed && !isTraining && (
        <p className="caption" style={{ marginTop: '0.5rem' }}>
          Requires: PI Tag Mapping present and Model Mapping present, in addition to trained models.
        </p>
      )}

      {trainMutation.isError && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="error">
            {(trainMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
              'Failed to start training.'}
          </Callout>
        </div>
      )}

      {jobQuery.data?.status === 'error' && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant="error">{jobQuery.data.error}</Callout>
        </div>
      )}

      {trainResult && (
        <div style={{ marginTop: '0.75rem' }}>
          <Callout variant={trainResult.success ? 'success' : 'error'}>
            {trainResult.success
              ? `Training finished — ${trainResult.pkl_count} .pkl file(s) saved in Results/Model.`
              : `Training failed (exit code ${trainResult.returncode}). See the log below.`}
          </Callout>
          <details style={{ marginTop: '0.5rem' }}>
            <summary className="caption" style={{ cursor: 'pointer' }}>
              🔧 Training log (stdout / stderr)
            </summary>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                maxHeight: 240,
                overflowY: 'auto',
                background: 'var(--bg-subtle)',
                border: '1px solid var(--border)',
                padding: '0.75rem',
                borderRadius: 8,
                fontSize: '0.78rem',
                marginTop: '0.4rem',
              }}
            >
              {trainResult.stdout_tail || '<no stdout>'}
              {'\n\n--- stderr ---\n'}
              {trainResult.stderr_tail || '<no stderr>'}
            </pre>
          </details>
        </div>
      )}

      {!isLoading && modelsReady && (
        <div style={{ marginTop: '1.25rem' }}>
          <AccuracySummaryPanel />
        </div>
      )}
    </div>
  )
}
