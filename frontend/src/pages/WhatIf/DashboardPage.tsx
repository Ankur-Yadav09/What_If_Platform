import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { getConfigStatus, getModelsStatus, getTagOptions, runScenario } from '../../api/whatIf'
import { extractErrorMessage } from '../../api/errors'
import { Callout } from '../../components/Callout'
import { SectionBanner } from '../../components/SectionBanner'
import { useActiveWhatIf } from '../../state/ActiveWhatIfContext'
import { ActualVsEstimatedTable } from './ActualVsEstimatedTable'
import { BaselineValuesPanel } from './BaselineValuesPanel'
import { KpiCardsRow } from './KpiCardsRow'
import { SimulationOverridesPanel } from './SimulationOverridesPanel'
import { TagSourcePanel } from './TagSourcePanel'
import { TargetSectionSelector } from './TargetSectionSelector'
import { TimestampSelector } from './TimestampSelector'
import { ValidationFiltersPanel } from './ValidationFiltersPanel'
import type { WhatIfScenarioResult } from '../../api/types'

// What-If Analysis — a single flowing page (Target Section → Tag Source →
// Timestamp/Baseline → Simulation Overrides → Compute → KPI cards → Actual
// vs Estimated → Historical Validation), matching the reference Streamlit
// tab's order. The three scenario-identity pickers render as one compact
// horizontal row of cards (a "filter bar") rather than one tall stacked
// card, specifically to cut down the page's overall scroll length.
export function DashboardPage() {
  const { generatedTags, targetSection, setTargetSection } = useActiveWhatIf()

  const configStatusQuery = useQuery({ queryKey: ['whatif-config-status'], queryFn: getConfigStatus })
  const modelStatusQuery = useQuery({ queryKey: ['whatif-models-status'], queryFn: getModelsStatus })

  const gateReady =
    !!configStatusQuery.data?.pi_mapping_present &&
    !!configStatusQuery.data?.model_details_present &&
    !!modelStatusQuery.data?.all_present

  const tagOptionsQuery = useQuery({
    queryKey: ['whatif-tag-options', generatedTags, targetSection],
    queryFn: () => getTagOptions(generatedTags, targetSection),
    enabled: gateReady,
  })

  const [manualTags, setManualTags] = useState<Set<string>>(new Set())
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedTimestamp, setSelectedTimestamp] = useState('')
  const [overrides, setOverrides] = useState<Record<string, string>>({})

  const activeTags = useMemo(() => {
    if (!tagOptionsQuery.data) return []
    return tagOptionsQuery.data.source === 'config' ? tagOptionsQuery.data.tags : Array.from(manualTags)
  }, [tagOptionsQuery.data, manualTags])

  // Mirrors the Streamlit original: an override that fails numeric or
  // boundary validation is silently dropped (kept at baseline) rather than
  // sent, exactly like whatif_runner.py's val_float = np.nan path.
  const validOverrides = useMemo(() => {
    const limits = tagOptionsQuery.data?.limits ?? {}
    return Object.entries(overrides)
      .filter(([, raw]) => raw.trim() !== '')
      .map(([parameter, raw]) => ({ parameter, value: Number(raw) }))
      .filter((o) => !Number.isNaN(o.value))
      .filter((o) => {
        const lim = limits[o.parameter]
        return !lim || (o.value >= lim.lower && o.value <= lim.upper)
      })
  }, [overrides, tagOptionsQuery.data])

  const scenarioMutation = useMutation({ mutationFn: runScenario })
  const resultsRef = useRef<HTMLDivElement>(null)

  // useMutation resets `data` to undefined the instant a new mutate() call
  // starts (confirmed live: the whole results block was unmounting and
  // reappearing on every recompute, not just going stale as originally
  // assumed) -- track the last successful result separately so a recompute
  // dims/labels the existing results in place instead of blanking the page.
  const [lastResult, setLastResult] = useState<WhatIfScenarioResult | null>(null)
  useEffect(() => {
    if (scenarioMutation.data) setLastResult(scenarioMutation.data)
  }, [scenarioMutation.data])

  // Results land well below the Compute button — jump to them automatically
  // instead of leaving the user to notice and scroll down themselves (same
  // reasoning as the Welcome page's User Guide/FAQ auto-scroll).
  useEffect(() => {
    if (scenarioMutation.data) resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [scenarioMutation.data])

  if (configStatusQuery.isLoading || modelStatusQuery.isLoading) {
    return <p className="caption">Checking What-If setup status…</p>
  }

  if (!gateReady) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <SectionBanner
          title="What-If Analysis"
          subtitle="Simulate hypothetical process scenarios against your configured predictive models."
        />
        <Callout variant="warning">
          🔒 Simulation overrides are locked. Complete{' '}
          <Link to="/what-if/case-setup">What-If Setup</Link> — PI Tag Mapping, Model Mapping, and all trained Kalman
          models must be present — before this page unlocks.
        </Callout>
      </div>
    )
  }

  function runCompute() {
    scenarioMutation.mutate({ timestamp: selectedTimestamp, overrides: validOverrides, target_section: targetSection })
  }

  const nOverrides = validOverrides.length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <SectionBanner
        title="What-If Analysis"
        subtitle="Simulate hypothetical process scenarios against your configured predictive models."
      />

      {/* Filter bar: 3 compact cards side by side instead of one tall
          stacked card -- these are short, identity-picking controls
          (a dropdown, a short description, a date/time picker), not
          content that needs a full card's worth of vertical space each. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '1.25rem',
        }}
      >
        <div className="card" style={{ padding: '1.25rem 1.5rem' }}>
          <h3 style={{ marginTop: 0 }}>Target Section</h3>
          <TargetSectionSelector value={targetSection} onChange={setTargetSection} />
        </div>

        {/* When the tag source is the config "user inputs" sheet, there's
            nothing to pick — TagSourcePanel just prints a static "using N
            tags" line, so the card added a whole box with no actual
            content. Only the wizard/historian sources have a real picker
            (the MultiSelectDropdown that drives manualTags/activeTags
            below), so the card is worth showing only then. */}
        {tagOptionsQuery.data && tagOptionsQuery.data.source !== 'config' && (
          <div className="card" style={{ padding: '1.25rem 1.5rem' }}>
            <h3 style={{ marginTop: 0 }}>Tag Source</h3>
            <TagSourcePanel tagOptions={tagOptionsQuery.data} selectedTags={manualTags} onChange={setManualTags} />
          </div>
        )}

        <div className="card" style={{ padding: '1.25rem 1.5rem' }}>
          <h3 style={{ marginTop: 0 }}>Baseline Process Snapshot</h3>
          <TimestampSelector
            selectedDate={selectedDate}
            onDateChange={setSelectedDate}
            selectedTimestamp={selectedTimestamp}
            onTimestampChange={setSelectedTimestamp}
          />
        </div>
      </div>

      <div className="card" style={{ padding: '1.25rem 1.5rem' }}>
        <BaselineValuesPanel timestamp={selectedTimestamp} tags={activeTags} />
      </div>

      <SimulationOverridesPanel
        tags={activeTags}
        limits={tagOptionsQuery.data?.limits ?? {}}
        overrides={overrides}
        onChange={(tag, raw) => setOverrides({ ...overrides, [tag]: raw })}
        onReset={() => setOverrides({})}
      />

      <div className="card" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <button disabled={!selectedTimestamp || scenarioMutation.isPending} onClick={runCompute}>
            {scenarioMutation.isPending
              ? 'Processing…'
              : `Compute What-If Scenario (${nOverrides} override${nOverrides === 1 ? '' : 's'} active)`}
          </button>
          {!selectedTimestamp && <span className="caption">Pick an Available Snapshot Time above first.</span>}
        </div>
        {scenarioMutation.isError && (
          <div style={{ marginTop: '0.75rem' }}>
            <Callout variant="error">{extractErrorMessage(scenarioMutation.error, 'What-if analysis failed.')}</Callout>
          </div>
        )}
      </div>

      {lastResult && (
        <div
          ref={resultsRef}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '1.75rem',
            position: 'relative',
            // lastResult (not scenarioMutation.data) is what keeps these
            // results on screen during a recompute instead of the whole
            // block unmounting -- this dim + badge is the cue that what's
            // showing is the previous run, not the new one landing.
            opacity: scenarioMutation.isPending ? 0.5 : 1,
            pointerEvents: scenarioMutation.isPending ? 'none' : undefined,
            transition: 'opacity 0.15s ease',
          }}
        >
          {scenarioMutation.isPending && (
            <div
              style={{
                position: 'sticky',
                top: '0.75rem',
                alignSelf: 'center',
                zIndex: 5,
                background: 'var(--text-main)',
                color: 'var(--bg-page)',
                fontWeight: 600,
                fontSize: '0.85rem',
                padding: '0.4rem 0.9rem',
                borderRadius: 999,
              }}
            >
              ⏳ Recalculating…
            </div>
          )}
          {lastResult.constraint_hit && (
            <Callout variant="warning">{lastResult.constraint_message}</Callout>
          )}
          <KpiCardsRow kpis={lastResult.kpis} />
          <div className="card" style={{ padding: '1.5rem' }}>
            <ActualVsEstimatedTable timestamp={selectedTimestamp} rows={lastResult.rows} />
          </div>
          <ValidationFiltersPanel
            timestamp={selectedTimestamp}
            scenarioRows={lastResult.rows}
            targetSection={targetSection}
          />
        </div>
      )}
    </div>
  )
}
