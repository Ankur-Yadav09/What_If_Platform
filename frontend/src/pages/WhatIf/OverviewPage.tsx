import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createCase, listCases, openCase } from '../../api/cases'
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
  getTargetSection,
  getUserInputs,
} from '../../api/whatIf'
import { Callout } from '../../components/Callout'
import { StatusCard } from '../../components/StatusCard'
import { useActiveCase } from '../../state/ActiveCaseContext'
import { useActiveWhatIf } from '../../state/ActiveWhatIfContext'

// Query keys that vary by active case -- invalidated on every case switch
// (create or open) so the page's status tiles and every What-If Setup /
// Experimentation & Model Selection tab refetch against the newly active
// case rather than showing stale data carried over from the previous one.
const CASE_SCOPED_QUERY_KEYS = [
  'whatif-config-status',
  'whatif-models-status',
  'whatif-pi-mapping',
  'whatif-model-mapping',
  'whatif-section-order',
  'whatif-mvdvcv',
  'whatif-constraints',
  'whatif-user-inputs',
  'whatif-column-order',
  'whatif-target-section',
  'whatif-detected-counts',
  'overview',
  // Datasets/projects are now fully case-isolated too (Connect Data/Data
  // Health/Model Definition/Build Model) -- these two are the unparameterized
  // list-level queries, so they need explicit invalidation on switch. Queries
  // parameterized by dataset/project name (e.g. ['preprocess-stats', name])
  // don't need it here: once ActiveDatasetContext/ActiveProjectContext
  // re-derive their value for the new case (see those files), the query key
  // itself changes and/or its `enabled: !!name` guard turns off.
  'datasets',
  'projects',
]

const GUIDE_SECTIONS = [
  {
    title: '🔧 System Config',
    items: [
      'Process Flow Order — plant sections in actual sequence, plus which one this case targets.',
      'PI Tag Mapping — raw PI tag → readable name → section. Fill it in according to the Process Flow Order, and upload your training/historian data in that same tag order too.',
      'Input Tag Configuration (MV/DV/CV) (optional) — prioritized inputs for Model Mapping.',
    ],
  },
  {
    title: '🧠 Model Config',
    items: [
      'Model Development — Connect Data, Data Health, Model Definition, AI Feature Discovery, Build Model. Freely revisit any step, rebuild, and run as many experiments as you need.',
      'Experimentation & Model Selection — compare every experiment for a Predicted Parameter and mark one "Selected for What-If Analysis". What-If Analysis then uses it automatically; parameters with no selection fall back to the dedicated Kalman model (trained from the "Advanced" section there).',
    ],
  },
  {
    title: '⚙️ What-If Config',
    items: [
      'Constraints (optional) — operating limits and bump/abort rules.',
      'User Inputs (optional) — overridable parameters with allowed ranges.',
      'Results Layout (optional) — display order for the results table.',
    ],
  },
]

const FAQ_ITEMS = [
  {
    q: 'What-If Analysis is locked?',
    a: 'Go to What-If Setup — it unlocks once PI Tag Mapping, Model Mapping, and every predicted parameter has a model (either a trained Kalman model, or an experiment marked "Selected for What-If Analysis" in Experimentation & Model Selection).',
  },
  {
    q: 'Which model does What-If Analysis actually use for a parameter?',
    a: 'Whichever experiment you marked "Selected for What-If Analysis" for that parameter, in Model Config → Experimentation & Model Selection. If none is selected, it falls back to that parameter\'s dedicated Kalman model.',
  },
  {
    q: 'Scenario failed to compute?',
    a: 'Confirm the historical timestamp you picked has complete data, and that any overrides are within the displayed boundary range.',
  },
  {
    q: 'Validation table is empty?',
    a: 'Widen the min/max filters — they default to the full historical range but can be narrowed by hand.',
  },
]

function ResourceButton({
  icon,
  label,
  onClick,
  disabled,
  disabledHint,
}: {
  icon: string
  label: string
  onClick?: () => void
  disabled?: boolean
  disabledHint?: string
}) {
  return (
    <button
      className="chip"
      style={{ flex: 1, minWidth: 160, opacity: disabled ? 0.55 : 1 }}
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledHint : undefined}
    >
      {icon} {label}
      {disabled && <span className="caption" style={{ display: 'block' }}>Coming soon</span>}
    </button>
  )
}

// Welcome page for What-If Studio — action-oriented landing screen (Quick
// Actions, workflow at a glance, live configuration readiness, resources)
// replacing the earlier text-heavy Overview page. Detailed step-by-step
// reference content still exists, just tucked behind the "User Guide"/"FAQ"
// resource buttons instead of being the default view.
export function WhatIfOverviewPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeCaseId, setActiveCaseId } = useActiveCase()
  const { targetSection, setTargetSection, setGeneratedTags } = useActiveWhatIf()
  const [guideOpen, setGuideOpen] = useState(false)
  const [faqOpen, setFaqOpen] = useState(false)
  const [newCaseOpen, setNewCaseOpen] = useState(false)
  const [casePickerOpen, setCasePickerOpen] = useState(false)
  const [newCaseName, setNewCaseName] = useState('')
  const guideRef = useRef<HTMLDivElement>(null)
  const faqRef = useRef<HTMLDivElement>(null)

  const casesQuery = useQuery({ queryKey: ['whatif-cases'], queryFn: listCases })
  const activeCase = casesQuery.data?.find((c) => c.case_id === activeCaseId)

  // Opening the User Guide / FAQ reveals a panel below the Resources
  // buttons — on a shorter viewport that panel lands off-screen, so
  // scroll it into view instead of leaving the user to notice and scroll
  // down themselves.
  useEffect(() => {
    if (guideOpen) guideRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [guideOpen])
  useEffect(() => {
    if (faqOpen) faqRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [faqOpen])

  const configStatusQuery = useQuery({ queryKey: ['whatif-config-status'], queryFn: getConfigStatus })
  const modelStatusQuery = useQuery({ queryKey: ['whatif-models-status'], queryFn: getModelsStatus })
  const targetSectionQuery = useQuery({ queryKey: ['whatif-target-section'], queryFn: getTargetSection })

  const piPresent = !!configStatusQuery.data?.pi_mapping_present
  const modelPresent = !!configStatusQuery.data?.model_details_present
  const sectionOrder = targetSectionQuery.data?.section_order ?? []
  const processOrderReady = sectionOrder.length >= 2
  const modelsReady = !!modelStatusQuery.data?.all_present

  const hasAnyConfig = piPresent || modelPresent || processOrderReady
  const fullyReady = processOrderReady && piPresent && modelPresent && modelsReady

  // Switching the active case (creating a new one, or opening a different
  // existing one) invalidates every case-scoped query and clears the
  // client-side wizard state (ActiveWhatIfContext's target section/generated
  // tags), since those are cached under a single global localStorage key,
  // not per case, and would otherwise still show the previous case's
  // picks even though the backend sheet is now a different case entirely.
  function switchToCase(caseId: string) {
    setActiveCaseId(caseId)
    for (const key of CASE_SCOPED_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
    setTargetSection(null)
    setGeneratedTags([])
    navigate('/what-if/case-setup')
  }

  const createCaseMutation = useMutation({
    mutationFn: (name: string) => createCase(name),
    onSuccess: (created) => {
      setNewCaseName('')
      setNewCaseOpen(false)
      queryClient.invalidateQueries({ queryKey: ['whatif-cases'] })
      switchToCase(created.case_id)
    },
  })

  const openCaseMutation = useMutation({
    mutationFn: (caseId: string) => openCase(caseId),
    onSuccess: (opened) => {
      setCasePickerOpen(false)
      queryClient.invalidateQueries({ queryKey: ['whatif-cases'] })
      switchToCase(opened.case_id)
    },
  })

  function submitNewCase() {
    const name = newCaseName.trim()
    if (name) createCaseMutation.mutate(name)
  }

  const downloadSampleMutation = useMutation({
    mutationFn: async () => {
      const [pi, model, sectionOrderRows, mvdvcv, constraints, userInputs, columnOrder, ts] = await Promise.all([
        getPiMapping(),
        getModelMapping(),
        getSectionOrder(),
        getMvDvCvTaglist(),
        getConstraints(),
        getUserInputs(),
        getColumnOrder(),
        getTargetSection(),
      ])
      const blob = await exportFullConfig({
        pi_mapping_rows: pi,
        model_details_rows: model.rows,
        constraints_rows: constraints,
        user_inputs_rows: userInputs,
        display_order_rows: columnOrder,
        section_order_rows: sectionOrderRows,
        mvdvcv_rows: mvdvcv,
        target_section: ts.target_section,
      })
      downloadBlob(blob, 'Sample_Config_file.xlsx')
    },
  })

  const statusTiles = [
    {
      label: 'Process Flow Order',
      ready: processOrderReady,
      value: processOrderReady ? `${sectionOrder.length} sections` : 'Not set',
    },
    {
      label: 'PI Tag Mapping',
      ready: piPresent,
      value: piPresent ? `${configStatusQuery.data?.pi_mapping_row_count ?? 0} tags` : 'Missing',
    },
    {
      label: 'Model Mapping',
      ready: modelPresent,
      value: modelPresent ? `${configStatusQuery.data?.model_details_row_count ?? 0} rows` : 'Missing',
    },
    {
      label: 'Trained Models',
      ready: modelsReady,
      value: modelStatusQuery.data ? `${modelStatusQuery.data.pkl_count}/${modelStatusQuery.data.required_pkl_count} files` : '—',
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      {/* Welcome banner -- kept to just the heading/buttons; the case
          panels below are deliberately siblings, not descendants, of
          .section-banner: that class forces every nested <p> to the pale
          --banner-subtitle color meant for its dark gradient background,
          which is invisible against the white .card panels used here. */}
      <div className="section-banner" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span className="icon">🧭</span>
          <div>
            <h2 style={{ marginBottom: '0.3rem' }}>Welcome to What-If Studio</h2>
            <p style={{ maxWidth: 620, margin: 0 }}>
              Simulate process scenarios against trained plant models and see the projected impact before you act.
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <button
            onClick={() => {
              setCasePickerOpen(false)
              setNewCaseOpen((o) => !o)
            }}
          >
            + New Case
          </button>
          <button
            className="chip"
            onClick={() => {
              setNewCaseOpen(false)
              setCasePickerOpen((o) => !o)
            }}
          >
            ⏩ Switch / Resume Case
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <p className="caption" style={{ margin: 0 }}>
          Current case: <strong>{activeCase?.name ?? activeCaseId}</strong>
        </p>

        {newCaseOpen && (
          <div className="card" style={{ padding: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="Case name (e.g. Furnace Trial 2)"
              value={newCaseName}
              onChange={(e) => setNewCaseName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submitNewCase()}
              style={{ flex: 1, minWidth: 220 }}
              autoFocus
            />
            <button onClick={submitNewCase} disabled={!newCaseName.trim() || createCaseMutation.isPending}>
              {createCaseMutation.isPending ? 'Creating…' : 'Create'}
            </button>
            <p className="caption" style={{ width: '100%', margin: 0 }}>
              No files needed — you'll build the PI mapping, model mapping, constraints, user inputs and column
              order for this case entirely in What-If Setup, then save it from there.
            </p>
            {createCaseMutation.isError && <Callout variant="error">Could not create that case — try a different name.</Callout>}
          </div>
        )}

        {casePickerOpen && (
          <div className="card" style={{ padding: '1rem' }}>
            {casesQuery.isLoading ? (
              <p className="caption">Loading cases…</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {(casesQuery.data ?? []).map((c) => (
                  <div
                    key={c.case_id}
                    style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}
                  >
                    <div>
                      <div style={{ fontWeight: 700 }}>{c.name}</div>
                      <p className="caption" style={{ margin: 0 }}>Last opened {c.last_opened_at}</p>
                    </div>
                    {c.case_id === activeCaseId ? (
                      <span className="pill active">✓ Active</span>
                    ) : (
                      <button
                        className="chip"
                        onClick={() => openCaseMutation.mutate(c.case_id)}
                        disabled={openCaseMutation.isPending}
                      >
                        Open
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Configuration status */}
      <div>
        <h3 style={{ marginBottom: '0.75rem' }}>Configuration Status</h3>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          {statusTiles.map((t) => (
            <StatusCard
              key={t.label}
              label={t.label}
              value={t.value}
              sublabel={t.ready ? '✅ Ready' : '⏳ Pending'}
              tone={t.ready ? 'success' : 'warning'}
            />
          ))}
        </div>
      </div>

      {/* Current case status */}
      <div>
        <h3 style={{ marginBottom: '0.75rem' }}>Current Case</h3>
        {hasAnyConfig ? (
          <div className="card" style={{ padding: '1.25rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
            <div>
              <div style={{ fontWeight: 700 }}>{activeCase?.name ?? activeCaseId}</div>
              <p className="caption" style={{ margin: 0 }}>
                Target section: {targetSection ?? targetSectionQuery.data?.target_section ?? 'not set'} ·{' '}
                {fullyReady ? 'Ready to run scenarios' : 'Setup in progress'}
              </p>
            </div>
            <button
              className="chip"
              onClick={() => navigate(fullyReady ? '/what-if/dashboard' : '/what-if/case-setup')}
            >
              {fullyReady ? 'Go to What-If Analysis →' : 'Continue Setup →'}
            </button>
          </div>
        ) : (
          <p className="caption">This case is empty — build its configuration in What-If Setup.</p>
        )}
      </div>

      {/* Resources */}
      <div>
        <h3 style={{ marginBottom: '0.75rem' }}>Resources</h3>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <ResourceButton icon="📘" label="User Guide" onClick={() => setGuideOpen((o) => !o)} />
          <ResourceButton
            icon="📥"
            label={downloadSampleMutation.isPending ? 'Preparing…' : 'Sample Configuration'}
            onClick={() => downloadSampleMutation.mutate()}
          />
          <ResourceButton icon="❓" label="FAQ" onClick={() => setFaqOpen((o) => !o)} />
        </div>
        {downloadSampleMutation.isError && (
          <div style={{ marginTop: '0.75rem' }}>
            <Callout variant="error">Could not prepare the sample configuration download.</Callout>
          </div>
        )}

        {guideOpen && (
          <div ref={guideRef} className="card" style={{ padding: '1.25rem', marginTop: '1rem' }}>
            <div style={{ fontWeight: 700, marginBottom: '0.75rem' }}>📘 What-If Setup — at a glance</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {GUIDE_SECTIONS.map((section) => (
                <div key={section.title}>
                  <div className="caption" style={{ fontWeight: 700, marginBottom: '0.3rem' }}>{section.title}</div>
                  <ul style={{ margin: 0, paddingLeft: '1.2rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                    {section.items.map((item) => (
                      <li key={item} className="caption">{item}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}

        {faqOpen && (
          <div ref={faqRef} className="card" style={{ padding: '1.25rem', marginTop: '1rem' }}>
            <div style={{ fontWeight: 700, marginBottom: '0.6rem' }}>❓ Frequently Asked Questions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {FAQ_ITEMS.map((item) => (
                <p key={item.q} className="caption" style={{ margin: 0 }}>
                  <strong>{item.q}</strong> {item.a}
                </p>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
