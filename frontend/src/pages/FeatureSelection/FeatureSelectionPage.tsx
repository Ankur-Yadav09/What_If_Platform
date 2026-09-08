import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { listDatasets } from '../../api/datasets'
import { submitFeatureSelection } from '../../api/featureSelection'
import { getFeatureStats } from '../../api/preprocess'
import { Callout } from '../../components/Callout'
import { MultiSelectDropdown } from '../../components/MultiSelectDropdown'
import { SectionBanner } from '../../components/SectionBanner'
import { StepHeading } from '../../components/StepHeading'
import { Tabs } from '../../components/Tabs'
import { useJobPolling } from '../../hooks/useJobPolling'
import { DEFAULT_CASE_ID, useActiveCase } from '../../state/ActiveCaseContext'
import { useActiveDataset } from '../../state/ActiveDatasetContext'
import { FeatureSelectionResults } from './FeatureSelectionResults'
import { FinalApply } from './FinalApply'
import { ManualVariableSelection } from './ManualVariableSelection'
import { METHOD_CATEGORIES, METHOD_IDS, METHOD_LABELS } from './methodMeta'
import type { FeatureSelectionResult } from '../../api/types'

type Pathway = 'configure' | 'automated'

// Persists in-progress Feature Discovery choices (target/candidate columns,
// pathway, job in flight, ...) across unmount/remount -- ModelConfigTab's
// Model Development phases fully unmount their content on switch (see its
// devContent if/else), so without this, navigating to Build Model and back
// silently reset the whole page to "select Y feature" even though nothing
// had actually gone wrong. Scoped per case + dataset, same convention as
// ActiveDatasetContext's storageKeyFor (default case keeps the bare-ish key).
interface PersistedFeatureDiscoveryState {
  yCols: string[]
  xCols: string[]
  pathway: Pathway
  topK: number
  corrThreshold: number
  vifThreshold: number
  enabledMethods: string[]
  perTarget: boolean
  processAware: boolean
  jobId: string | null
}

function storageKeyFor(caseId: string, datasetName: string, targetY?: string): string {
  const base = `softsense.featureDiscovery.${datasetName}`
  const withCase = caseId === DEFAULT_CASE_ID ? base : `${base}.${caseId}`
  // Only appended for the guided (lockedTargetY) flow -- omitted, this is
  // byte-identical to the pre-existing key, so today's manual multi-Y usage
  // (including the standalone /feature-selection route) is unaffected. With
  // it, sequential per-Y guided sessions on the same dataset+case no longer
  // clobber each other's in-progress xCols/job state.
  return targetY ? `${withCase}.y=${encodeURIComponent(targetY)}` : withCase
}

function loadPersisted(key: string): PersistedFeatureDiscoveryState | null {
  const raw = localStorage.getItem(key)
  if (!raw) return null
  try {
    return JSON.parse(raw) as PersistedFeatureDiscoveryState
  } catch {
    return null
  }
}

interface FeatureSelectionPageProps {
  /** Forwarded to FinalApply, which requires it — see its own onContinue
   * doc for why this matters when embedded inside What-If Studio's Model
   * Development flow. */
  onContinue: () => void
  /** Set by Model Definition's "Configure Model" action: locks Target
   * Variable selection to this single column (dataset is already carried
   * via ActiveDatasetContext) so the user isn't asked to pick Y again. */
  lockedTargetY?: string
}

export function FeatureSelectionPage({ onContinue, lockedTargetY }: FeatureSelectionPageProps) {
  const { activeCaseId } = useActiveCase()
  const { activeDataset: datasetName, setActiveDataset: setDatasetName } = useActiveDataset()

  // storageKey tracks which case+dataset the rest of this state currently
  // reflects. Restoring on a key change happens synchronously HERE, during
  // render, rather than in a useEffect -- doing it in an effect (as an
  // earlier version of this did) raced against the save effect below: React
  // Strict Mode's dev-only double-invocation of effects on mount ran the
  // save effect (with its stale, pre-restore closure) BETWEEN the two
  // invocations of the load effect, clobbering the just-restored data with
  // blanks before the second invocation ever got a chance to read it back.
  // Adjusting state during render is React's documented answer to exactly
  // this: React discards the stale render immediately, without committing
  // it or running effects for it, so save never observes an inconsistent
  // (new key, old values) snapshot. See PersistedFeatureDiscoveryState above.
  const [storageKey, setStorageKey] = useState(() => storageKeyFor(activeCaseId, datasetName, lockedTargetY))
  const [yCols, setYCols] = useState<Set<string>>(() => new Set(loadPersisted(storageKey)?.yCols ?? []))
  const [pathway, setPathway] = useState<Pathway>(() => loadPersisted(storageKey)?.pathway ?? 'automated')

  // Configure-pathway settings
  const [topK, setTopK] = useState(() => loadPersisted(storageKey)?.topK ?? 10)
  const [corrThreshold, setCorrThreshold] = useState(() => loadPersisted(storageKey)?.corrThreshold ?? 0.85)
  const [vifThreshold, setVifThreshold] = useState(() => loadPersisted(storageKey)?.vifThreshold ?? 10.0)
  const [enabledMethods, setEnabledMethods] = useState<Set<string>>(
    () => new Set(loadPersisted(storageKey)?.enabledMethods ?? METHOD_IDS),
  )
  const [perTarget, setPerTarget] = useState(() => loadPersisted(storageKey)?.perTarget ?? false)
  // Generic Feature Selection (default): every candidate X is eligible for
  // every Y. Process-Aware: only X columns appearing BEFORE a given Y in
  // the dataset's original column order are eligible for that Y — modeled
  // server-side (backend/app/services/feature_selection_service.py), this
  // flag just opts in.
  const [processAware, setProcessAware] = useState(() => loadPersisted(storageKey)?.processAware ?? true)

  const [jobId, setJobId] = useState<string | null>(() => loadPersisted(storageKey)?.jobId ?? null)
  const [xCols, setXCols] = useState<Set<string>>(() => new Set(loadPersisted(storageKey)?.xCols ?? []))

  const currentKey = storageKeyFor(activeCaseId, datasetName, lockedTargetY)
  if (currentKey !== storageKey) {
    const persisted = loadPersisted(currentKey)
    setStorageKey(currentKey)
    setYCols(new Set(persisted?.yCols ?? []))
    setXCols(new Set(persisted?.xCols ?? []))
    setPathway(persisted?.pathway ?? 'automated')
    setTopK(persisted?.topK ?? 10)
    setCorrThreshold(persisted?.corrThreshold ?? 0.85)
    setVifThreshold(persisted?.vifThreshold ?? 10.0)
    setEnabledMethods(new Set(persisted?.enabledMethods ?? METHOD_IDS))
    setPerTarget(persisted?.perTarget ?? false)
    setProcessAware(persisted?.processAware ?? true)
    setJobId(persisted?.jobId ?? null)
  }

  // Save on every change so a later remount (e.g. after visiting Build
  // Model) picks this exact state back up instead of starting over. Keyed
  // off the `storageKey` state (not a freshly-computed one) so this only
  // ever fires once storageKey and the rest of the fields agree with each
  // other -- never mid-transition.
  useEffect(() => {
    const payload: PersistedFeatureDiscoveryState = {
      yCols: [...yCols],
      xCols: [...xCols],
      pathway,
      topK,
      corrThreshold,
      vifThreshold,
      enabledMethods: [...enabledMethods],
      perTarget,
      processAware,
      jobId,
    }
    localStorage.setItem(storageKey, JSON.stringify(payload))
  }, [storageKey, yCols, xCols, pathway, topK, corrThreshold, vifThreshold, enabledMethods, perTarget, processAware, jobId])

  const datasetsQuery = useQuery({ queryKey: ['datasets'], queryFn: listDatasets })
  const statsQuery = useQuery({
    queryKey: ['preprocess-stats', datasetName],
    queryFn: () => getFeatureStats(datasetName),
    enabled: !!datasetName,
  })
  const numericCols = useMemo(
    () => (statsQuery.data ?? []).filter((s) => s.Mean !== null).map((s) => s.Feature),
    [statsQuery.data],
  )
  // While locked, effectiveYCols is the single source of truth for every
  // downstream computation below -- internal yCols state is never written
  // to (see toggleY/MultiSelectDropdown, both bypassed while locked), so it
  // can't drift or leak into the non-guided storage bucket.
  const effectiveYCols = lockedTargetY ? new Set([lockedTargetY]) : yCols
  const candidateX = numericCols.filter((c) => !effectiveYCols.has(c))

  const submitMutation = useMutation({
    mutationFn: submitFeatureSelection,
    onSuccess: (id) => setJobId(id),
  })

  const jobQuery = useJobPolling(jobId)
  const result = jobQuery.data?.status === 'done' ? (jobQuery.data.result as FeatureSelectionResult) : null

  // A persisted jobId can outlive the job it points to (e.g. the backend
  // restarted between sessions) — job_manager.py's registry is in-memory
  // only, so that job_id 404s forever otherwise, polling every 1.5s for
  // nothing (see useJobPolling's refetchInterval).
  useEffect(() => {
    if (jobQuery.isError) setJobId(null)
  }, [jobQuery.isError])

  function toggleY(col: string) {
    const next = new Set(yCols)
    if (next.has(col)) next.delete(col)
    else next.add(col)
    setYCols(next)
    setJobId(null)
  }

  function toggleMethod(mid: string) {
    const next = new Set(enabledMethods)
    if (next.has(mid)) next.delete(mid)
    else next.add(mid)
    setEnabledMethods(next)
  }

  function runConfigure() {
    submitMutation.mutate({
      dataset_name: datasetName,
      y_cols: [...effectiveYCols],
      x_cols: candidateX,
      top_k: topK,
      corr_threshold: corrThreshold,
      vif_threshold: vifThreshold,
      per_target: perTarget,
      process_aware: processAware,
      enabled_methods: [...enabledMethods],
    })
  }

  function runAutomated() {
    const autoTopK = Math.min(Math.max(10, Math.floor(candidateX.length / 5)), 30)
    submitMutation.mutate({
      dataset_name: datasetName,
      y_cols: [...effectiveYCols],
      x_cols: candidateX,
      top_k: autoTopK,
      corr_threshold: 0.85,
      vif_threshold: 10.0,
      per_target: perTarget,
      process_aware: processAware,
    })
  }

  function applyQuickPick(features: string[]) {
    setXCols(new Set(features))
  }

  const methodsByCategory = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const mid of METHOD_IDS) {
      const cat = METHOD_CATEGORIES[mid]
      map[cat] = [...(map[cat] ?? []), mid]
    }
    return map
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <h1>Feature Selection</h1>

      <div>
        <StepHeading step={1} title="Select Target (Y) Variable" />
        <SectionBanner
          icon="🎯"
          title="Target Variable Selection"
          subtitle="Choose one or more columns to predict. These become Y; all others are candidate X features."
        />
      </div>

      <div className="card" style={{ padding: '1.5rem' }}>
        <label>
          <div className="caption">Dataset</div>
          <select
            value={datasetName}
            onChange={(e) => setDatasetName(e.target.value)}
            style={{ minWidth: 320 }}
          >
            <option value="">Select…</option>
            {(datasetsQuery.data ?? []).map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          {datasetName && (
            <p className="caption" style={{ marginTop: '0.4rem' }}>
              Carried over from your last step. Pick a different dataset above if needed.
            </p>
          )}
        </label>

        {datasetName && lockedTargetY && (
          <div style={{ marginTop: '1rem' }}>
            <div className="caption" style={{ marginBottom: '0.4rem' }}>
              Target Variable (locked)
            </div>
            <Callout variant="info">
              Configuring <code>{lockedTargetY}</code> — set from Model Definition. Go back to Model Definition to
              choose a different Predicted Parameter.
            </Callout>
          </div>
        )}

        {datasetName && !lockedTargetY && (
          <div style={{ marginTop: '1rem' }}>
            <div className="caption" style={{ marginBottom: '0.4rem' }}>
              Target Variable(s)
            </div>
            <MultiSelectDropdown
              options={numericCols}
              selected={yCols}
              onChange={(next) => {
                setYCols(next)
                setJobId(null)
              }}
            />
          </div>
        )}

        {datasetName && !lockedTargetY && yCols.size === 0 && (
          <div style={{ marginTop: '1rem' }}>
            <Callout variant="info">Select at least one target (Y) variable to proceed.</Callout>
          </div>
        )}
      </div>

      {datasetName && effectiveYCols.size > 0 && (
        <>
          <p className="caption">
            {candidateX.length} candidate X features · {effectiveYCols.size} target(s):{' '}
            <code>{[...effectiveYCols].join(', ')}</code>
          </p>

          <div>
            <h2 style={{ fontSize: '1.05rem', marginBottom: '0.75rem' }}>Choose Feature Selection Mode</h2>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button className={`chip${pathway === 'automated' ? ' active' : ''}`} onClick={() => setPathway('automated')}>
                ⚡ Automated Feature Selection
              </button>
              <button className={`chip${pathway === 'configure' ? ' active' : ''}`} onClick={() => setPathway('configure')}>
                🔧 Configure Feature Selection
              </button>
            </div>
          </div>

          {pathway === 'automated' ? (
            <div className="card" style={{ padding: '1.5rem' }}>
              <StepHeading step={2} title="Automated Feature Selection" />
              <SectionBanner
                icon="⚡"
                title="Automated Feature Selection"
                subtitle="Runs all available methods with best-default parameters in one click."
              />
              <p className="caption" style={{ margin: '1rem 0' }}>
                Will run {METHOD_IDS.length} independent scoring method(s) · Top-K auto-scaled to feature count ·
                Collinearity threshold = 0.85 · VIF threshold = 10.0
              </p>
              <button disabled={submitMutation.isPending} onClick={runAutomated}>
                {submitMutation.isPending ? 'Running…' : '⚡ Run Automated Feature Selection'}
              </button>
            </div>
          ) : (
            <div className="card" style={{ padding: '1.5rem' }}>
              <StepHeading step={3} title="Configure Feature Selection" />
              <Tabs
                tabs={[
                  {
                    label: '⚙️ Configure Analysis',
                    content: (
                      <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                        <label>
                          <div className="caption">Top-K features per method</div>
                          <input
                            type="number"
                            min={2}
                            max={Math.min(25, candidateX.length)}
                            value={topK}
                            onChange={(e) => setTopK(Number(e.target.value))}
                            style={{ width: 80 }}
                          />
                        </label>
                        <label>
                          <div className="caption">X–X collinearity flag threshold</div>
                          <input
                            type="number"
                            min={0.5}
                            max={0.99}
                            step={0.05}
                            value={corrThreshold}
                            onChange={(e) => setCorrThreshold(Number(e.target.value))}
                            style={{ width: 90 }}
                          />
                        </label>
                        <label>
                          <div className="caption">VIF threshold</div>
                          <input
                            type="number"
                            min={2}
                            max={50}
                            step={1}
                            value={vifThreshold}
                            onChange={(e) => setVifThreshold(Number(e.target.value))}
                            style={{ width: 90 }}
                          />
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '1.4rem' }}>
                          <input type="checkbox" checked={perTarget} onChange={(e) => setPerTarget(e.target.checked)} />
                          <span className="caption">Per-target mode (recommended for multi-Y)</span>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '1.4rem' }}>
                          <input
                            type="checkbox"
                            checked={processAware}
                            onChange={(e) => setProcessAware(e.target.checked)}
                          />
                          <span className="caption">
                            🏭 Process-Aware Feature Selection (only allow upstream X variables for each target,
                            based on column order) — default is Generic (all candidates for every target)
                          </span>
                        </label>
                      </div>
                    ),
                  },
                  {
                    label: '📋 Methods Selection',
                    content: (
                      <div style={{ display: 'flex', gap: '2.5rem', flexWrap: 'wrap' }}>
                        {Object.entries(methodsByCategory).map(([cat, mids]) => (
                          <div key={cat}>
                            <strong>{cat}</strong>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', marginTop: '0.4rem' }}>
                              {mids.map((mid) => (
                                <label key={mid} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                  <input type="checkbox" checked={enabledMethods.has(mid)} onChange={() => toggleMethod(mid)} />
                                  {METHOD_LABELS[mid]}
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    ),
                  },
                ]}
              />
              <p className="caption" style={{ marginTop: '1rem' }}>
                {enabledMethods.size} of {METHOD_IDS.length} core scoring method(s) selected.
              </p>
              <button
                style={{ marginTop: '1rem' }}
                disabled={enabledMethods.size === 0 || submitMutation.isPending}
                onClick={runConfigure}
              >
                {submitMutation.isPending ? 'Running…' : '🔍 Run Intelligent Feature Selection'}
              </button>
            </div>
          )}

          {jobId && jobQuery.data && !jobQuery.data.done && (
            <Callout variant="info">
              ⏳ {jobQuery.data.progress.message ?? 'Running…'} — this may take 20-90 seconds.
            </Callout>
          )}
          {jobQuery.data?.status === 'error' && <Callout variant="error">{jobQuery.data.error}</Callout>}

          {result && (
            <>
              <div>
                <StepHeading step={4} title="Analysis Results" />
                <FeatureSelectionResults result={result} />
              </div>

              <div className="card" style={{ padding: '1.5rem' }}>
                <p className="caption">
                  <strong>Highly Recommended + Recommended X ({result.recommended_features.length}):</strong>{' '}
                  <code>{result.recommended_features.join(', ') || 'None'}</code>
                </p>
                <p className="caption">
                  <strong>Consider X ({result.optional_features.length}):</strong>{' '}
                  <code>{result.optional_features.join(', ') || 'None'}</code>
                </p>
                <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.75rem' }}>
                  <button onClick={() => applyQuickPick(result.recommended_features)}>
                    ✅ Use Recommended ({result.recommended_features.length})
                  </button>
                  <button
                    onClick={() => applyQuickPick([...result.recommended_features, ...result.optional_features])}
                  >
                    ⭐ Use Rec + Optional ({result.recommended_features.length + result.optional_features.length})
                  </button>
                  <button onClick={() => setXCols(new Set())}>🗑️ Clear Selection</button>
                </div>
              </div>

              <ManualVariableSelection
                numericCols={numericCols}
                xCols={xCols}
                yCols={effectiveYCols}
                onToggleX={(c) => {
                  const next = new Set(xCols)
                  if (next.has(c)) next.delete(c)
                  else next.add(c)
                  setXCols(next)
                }}
                onToggleY={lockedTargetY ? () => {} : toggleY}
                onSelectAllX={(all) => setXCols(all ? new Set(numericCols) : new Set())}
                onSelectAllY={lockedTargetY ? () => {} : (all) => setYCols(all ? new Set(candidateX) : new Set())}
              />

              <FinalApply
                datasetName={datasetName}
                xCols={[...xCols]}
                yCols={[...effectiveYCols]}
                onContinue={onContinue}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}
