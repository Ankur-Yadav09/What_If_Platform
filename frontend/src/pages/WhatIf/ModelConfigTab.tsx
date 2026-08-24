import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getOverview, selectModelForParameter } from '../../api/overview'
import { getFeatureStats } from '../../api/preprocess'
import {
  commitModelMapping,
  getModelMapping,
  getModelsStatus,
  getMvDvCvTaglist,
  getPiMapping,
  getSectionOrder,
} from '../../api/whatIf'
import { Tabs } from '../../components/Tabs'
import { ExperimentHistoryPage } from '../SoftSensor/ExperimentHistoryPage'
import { FeatureSelectionPage } from '../FeatureSelection/FeatureSelectionPage'
import { PreprocessPage } from '../Preprocess/PreprocessPage'
import { TrainPage } from '../Train/TrainPage'
import { UploadPage } from '../Upload/UploadPage'
import { useActiveDataset } from '../../state/ActiveDatasetContext'
import { useActiveWhatIf } from '../../state/ActiveWhatIfContext'
import { allowedSet } from './caseSetupHelpers'
import { CorrelationMatrixView } from './CorrelationMatrixView'
import { FormulaEditor } from './FormulaEditor'
import { ModelDevelopmentStepper } from './ModelDevelopmentStepper'
import { findSelectedModel, INPUT_COLS, isDataModelRow, ModelMappingEditor } from './ModelMappingEditor'
import { ModelStatusPanel } from './ModelStatusPanel'
import { TrainingDataUpload } from './TrainingDataUpload'
import type { ModelDetailsRow } from '../../api/types'
import type { ModelDevPhaseKey } from './ModelDevelopmentStepper'

// Writes a just-accepted model's X features into its Predicted Parameter's
// own Input parameter_1..8 cells (truncated to INPUT_COLS.length -- the
// config file's fixed 8-slot schema, src/whatif/config_io.py's
// MODEL_DETAILS_COLUMNS) so Model Definition reflects them without the user
// re-entering anything. Blanks any slots beyond xCols.length so a re-Accept
// with fewer features doesn't leave stale tags behind from a previous run.
function withSyncedInputs(rows: ModelDetailsRow[], targetY: string, xCols: string[]): ModelDetailsRow[] {
  const trimmed = xCols.slice(0, INPUT_COLS.length)
  return rows.map((r) => {
    if ((r['Predicted parameter'] ?? '').toString().trim() !== targetY) return r
    const next = { ...r }
    INPUT_COLS.forEach((col, i) => {
      next[col] = trimmed[i] ?? ''
    })
    return next
  })
}

// "Model Config" section of What-If Setup, split into the two logical parts
// of building a model: an iterative "Model Development" workflow (Connect
// Data / Data Health / Model Definition / AI Feature Discovery / Build
// Model — freely revisit any step, rebuild, run more experiments) and
// "Experimentation & Model Selection" (compare every experiment Model
// Development has produced, mark one per Predicted Parameter as the model
// What-If Analysis actually uses — see ExperimentHistoryPage.tsx and
// src/whatif/engine.py::predict_and_update_with_soft_sensor_model). All
// Soft Sensor pages are reused verbatim, no duplicated implementations.
// Correlation Matrix isn't a standalone tab — it's appended inside Data
// Health, computed over whichever dataset is active in Connect Data (the
// same dataset PreprocessPage's own checks run against) — not the separate,
// case-scoped What-If training workbook (that one still has its own
// endpoint, api/whatIf.ts::getCorrelationMatrix, just unused by this view
// now). The dedicated Kalman-filter training step lives folded into
// Experimentation & Model Selection as a secondary/fallback action for
// parameters with no Experiment-History-selected model.
export function ModelConfigTab() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeDataset: datasetName } = useActiveDataset()
  const { targetSection } = useActiveWhatIf()
  const [outerTab, setOuterTab] = useState(0)
  const [devPhase, setDevPhase] = useState<ModelDevPhaseKey>('connect')
  // Which Predicted Parameter Model Definition's "Configure Model" sent the
  // user off to configure — carries through the discovery/build phases so
  // Feature Discovery/Build Model don't ask for Y again, and so Accept knows
  // which row to mark Ready. Cleared on Accept; left as-is on Improve.
  const [activeTargetY, setActiveTargetY] = useState<string | null>(null)
  // Which First-Principle Predicted Parameter "Define Formula" opened --
  // when set, the modeldef phase swaps its content to FormulaEditor instead
  // of ModelMappingEditor (same phase, no new stepper step), returning here
  // on "Back". Independent of activeTargetY/devPhase since it never leaves
  // the modeldef phase at all.
  const [activeFormulaParam, setActiveFormulaParam] = useState<string | null>(null)

  const sectionOrderQuery = useQuery({ queryKey: ['whatif-section-order'], queryFn: getSectionOrder })
  const piMappingQuery = useQuery({ queryKey: ['whatif-pi-mapping'], queryFn: getPiMapping })
  const mvdvcvQuery = useQuery({ queryKey: ['whatif-mvdvcv'], queryFn: getMvDvCvTaglist })
  const modelMappingQuery = useQuery({ queryKey: ['whatif-model-mapping'], queryFn: getModelMapping })
  const modelStatusQuery = useQuery({ queryKey: ['whatif-models-status'], queryFn: getModelsStatus })
  const overviewQuery = useQuery({ queryKey: ['overview'], queryFn: getOverview })
  const featureStatsQuery = useQuery({
    queryKey: ['preprocess-stats', datasetName],
    queryFn: () => getFeatureStats(datasetName),
    enabled: !!datasetName,
  })

  const selectMutation = useMutation({
    mutationFn: ({ parameter, modelName }: { parameter: string; modelName: string }) =>
      selectModelForParameter(parameter, modelName),
    onSuccess: (data) => queryClient.setQueryData(['overview'], data),
  })

  // Writes the accepted model's X features into the row's own Input
  // parameter_1..8 cells (see withSyncedInputs) -- same commit endpoint
  // ModelMappingEditor's own "Save Model Mapping" button uses, so it's the
  // one source of truth either way.
  const commitMappingMutation = useMutation({
    mutationFn: commitModelMapping,
    onSuccess: (result) =>
      queryClient.setQueryData(['whatif-model-mapping'], {
        rows: result,
        historian_tags: modelMappingQuery.data?.historian_tags ?? [],
      }),
  })

  const sectionOrderList = (sectionOrderQuery.data ?? []).map((r) => r.Section?.trim() ?? '').filter(Boolean)
  const allowed = allowedSet(sectionOrderList, targetSection)
  const piRows = piMappingQuery.data ?? []
  const mvdvcvRows = mvdvcvQuery.data ?? []
  const savedModels = overviewQuery.data?.saved_models ?? []
  const mappingRows = modelMappingQuery.data?.rows ?? []
  const modelMappingComplete = mappingRows.some((r) => (r['Predicted parameter'] ?? '').trim() !== '')

  // Suggested "Predicted parameter" values: the active dataset's numeric
  // columns (what AI Feature Discovery treats as valid Y candidates) plus
  // any name already used by a saved experiment or existing row -- covers
  // First-Principle labels and config-file-uploaded names too, without
  // restricting the field to only real dataset columns.
  const predictedParameterOptions = Array.from(
    new Set([
      ...(featureStatsQuery.data ?? []).filter((s) => s.Mean !== null).map((s) => s.Feature),
      ...savedModels.flatMap((m) => m.y_cols),
      ...mappingRows.map((r) => (r['Predicted parameter'] ?? '').trim()).filter(Boolean),
    ]),
  ).sort((a, b) => a.localeCompare(b))

  // Only Data-model rows go through this guided loop -- First-Principle rows
  // have no trained model to be "Ready", so they're excluded from both the
  // progress count and the proceed-to-What-If gate below. "Ready" is simply
  // "has a Selected-for-What-If-Analysis experiment" (findSelectedModel) --
  // Accept always selects (see handleAccept), so there's no separate
  // client-side acceptance state to track.
  const dataModelRows = mappingRows.filter(
    (r) => (r['Predicted parameter'] ?? '').trim() !== '' && isDataModelRow(r),
  )
  const readyCount = dataModelRows.filter((r) =>
    findSelectedModel((r['Predicted parameter'] ?? '').trim(), savedModels),
  ).length
  const allParametersReady = dataModelRows.length === 0 || readyCount === dataModelRows.length

  // Accept always both (a) selects this experiment for What-If Analysis and
  // (b) writes its X features back into Model Definition — one action, per
  // spec: no separate "add to Experimentation" prompt, since training
  // already unconditionally saves every run as an experiment regardless.
  function handleAccept(modelName: string) {
    if (!activeTargetY) return
    const targetY = activeTargetY
    selectMutation.mutate(
      { parameter: targetY, modelName },
      {
        onSuccess: (data) => {
          const model = data.saved_models.find((m) => m.name === modelName)
          if (model) commitMappingMutation.mutate(withSyncedInputs(mappingRows, targetY, model.x_cols))
        },
      },
    )
    setActiveTargetY(null)
    setDevPhase('modeldef')
  }

  const guided = activeTargetY
    ? { targetY: activeTargetY, onAccept: handleAccept, onImprove: () => setDevPhase('discovery') }
    : undefined

  const readyForAnalysis =
    !!piRows.length &&
    !!(modelMappingQuery.data?.rows.length) &&
    !!modelStatusQuery.data?.all_present &&
    allParametersReady

  let devContent
  if (devPhase === 'connect') {
    devContent = <UploadPage hideStepper onContinue={() => setDevPhase('health')} />
  } else if (devPhase === 'health') {
    devContent = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <PreprocessPage hideStepper onContinue={() => setDevPhase('modeldef')} />
        <div style={{ marginTop: '0.5rem', paddingTop: '1.5rem', borderTop: '1px solid var(--border)' }}>
          <h3 style={{ marginTop: 0 }}>Correlation Matrix</h3>
          <p className="caption">
            Pearson correlation of the connected dataset — spot strongly related tags before mapping model inputs
            below.
          </p>
          <CorrelationMatrixView datasetName={datasetName} />
        </div>
      </div>
    )
  } else if (devPhase === 'modeldef') {
    devContent = activeFormulaParam ? (
      <FormulaEditor predictedParameter={activeFormulaParam} onBack={() => setActiveFormulaParam(null)} />
    ) : (
      <div>
        <p className="caption">
          Active scope: {[...allowed].length ? sectionOrderList.filter((s) => allowed.has(s.toLowerCase())).join(', ') : 'all sections'}.
          {' '}"Configure Model →" pre-fills Feature Discovery/Build Model for that parameter; "Define Formula →" (First-Principle rows) is for typing a math expression instead.
          {modelMappingComplete && (
            <span className="pill active" style={{ marginLeft: '0.6rem' }}>
              ✓ Configured
            </span>
          )}
          {dataModelRows.length > 0 && (
            <span className={`pill${allParametersReady ? ' active' : ''}`} style={{ marginLeft: '0.6rem' }}>
              {readyCount} of {dataModelRows.length} parameter(s) Model Ready
            </span>
          )}
        </p>
        <ModelMappingEditor
          allowed={allowed}
          piRows={piRows}
          mvdvcvRows={mvdvcvRows}
          sectionOptions={['', ...sectionOrderList]}
          sectionOrder={sectionOrderList}
          savedModels={savedModels}
          predictedParameterOptions={predictedParameterOptions}
          onConfigureModel={(parameter) => {
            setActiveTargetY(parameter)
            setDevPhase('discovery')
          }}
          onDefineFormula={(parameter) => setActiveFormulaParam(parameter)}
        />
        <button style={{ marginTop: '1.25rem' }} onClick={() => setDevPhase('discovery')}>
          Continue to AI Feature Discovery →
        </button>
      </div>
    )
  } else if (devPhase === 'discovery') {
    devContent = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <FeatureSelectionPage hideStepper onContinue={() => setDevPhase('build')} lockedTargetY={activeTargetY ?? undefined} />
      </div>
    )
  } else {
    devContent = <TrainPage hideStepper onContinue={() => setOuterTab(1)} guided={guided} />
  }

  return (
    <Tabs
      activeIndex={outerTab}
      onChange={setOuterTab}
      tabs={[
        {
          label: 'Model Development',
          complete: modelMappingComplete,
          content: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <ModelDevelopmentStepper current={devPhase} onSelect={setDevPhase} />
              {devContent}
            </div>
          ),
        },
        {
          label: 'Experimentation & Model Selection',
          complete: !!modelStatusQuery.data?.all_present,
          content: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <ExperimentHistoryPage />
              <details className="card" style={{ padding: '1.5rem' }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>
                  Advanced: train dedicated Kalman filter models
                </summary>
                <p className="caption" style={{ marginTop: '0.75rem' }}>
                  Fallback for any parameter with no experiment "Selected for What-If Analysis" above — What-If
                  Analysis uses this dedicated Kalman model for those parameters automatically.
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', marginTop: '1rem' }}>
                  <div className="card" style={{ padding: '1.5rem' }}>
                    <h3 style={{ marginTop: 0 }}>Training Dataset</h3>
                    <TrainingDataUpload />
                  </div>
                  <ModelStatusPanel
                    status={modelStatusQuery.data}
                    isLoading={modelStatusQuery.isLoading}
                    canProceed={readyForAnalysis}
                    onProceed={() => navigate('/what-if/dashboard')}
                  />
                </div>
              </details>
            </div>
          ),
        },
      ]}
    />
  )
}
