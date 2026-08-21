// Progress stepper for What-If Studio's "Model Development" section — a
// distinct phase set from the generic frontend/src/components/WorkflowStepper
// (which is the Soft Sensor module's own standalone Connect Data -> ... ->
// Live Prediction story). This one inserts "Model Definition" (Model
// Mapping) in the middle and drops Live Prediction, matching Model
// Development's own 5 steps. Model Development is an intentionally
// non-linear, iterative workflow (rebuild models, revisit feature selection,
// re-map parameters, any order) — so unlike a typical wizard stepper this
// one is clickable on every phase, not just completed ones.
const PHASES = [
  { key: 'connect', label: 'Connect Data', subtitle: 'Select dataset' },
  { key: 'health', label: 'Data Health', subtitle: 'Quality check' },
  { key: 'modeldef', label: 'Model Definition', subtitle: 'Map predicted parameters' },
  { key: 'discovery', label: 'AI Feature Discovery', subtitle: 'Variable selection' },
  { key: 'build', label: 'Build Model', subtitle: 'Train & experiment' },
] as const

export type ModelDevPhaseKey = (typeof PHASES)[number]['key']

interface ModelDevelopmentStepperProps {
  current: ModelDevPhaseKey
  onSelect: (key: ModelDevPhaseKey) => void
}

export function ModelDevelopmentStepper({ current, onSelect }: ModelDevelopmentStepperProps) {
  const currentIndex = PHASES.findIndex((p) => p.key === current)

  return (
    <div className="card" style={{ padding: '1.1rem 1.5rem', overflowX: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', minWidth: 640 }}>
        {PHASES.map((phase, i) => {
          const isCurrent = i === currentIndex
          const isPast = i < currentIndex
          return (
            <div key={phase.key} style={{ display: 'flex', alignItems: 'center', flex: i === PHASES.length - 1 ? 'none' : 1 }}>
              <button
                onClick={() => onSelect(phase.key)}
                title={`Go to ${phase.label}`}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '0.4rem',
                  minWidth: 110,
                  background: 'transparent',
                  boxShadow: 'none',
                  border: 'none',
                  padding: 0,
                  cursor: 'pointer',
                }}
              >
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '0.95rem',
                    fontWeight: 700,
                    background: isCurrent
                      ? 'var(--accent)'
                      : isPast
                        ? 'var(--success-bg)'
                        : 'var(--control-bg)',
                    color: isCurrent ? 'var(--accent-ink)' : isPast ? 'var(--success-text)' : 'var(--text-caption)',
                    border: isCurrent ? 'none' : '1px solid var(--border)',
                  }}
                >
                  {isPast ? '✓' : i + 1}
                </div>
                <span
                  style={{
                    fontSize: '0.78rem',
                    textAlign: 'center',
                    fontWeight: isCurrent ? 700 : 500,
                    color: isCurrent ? 'var(--text-main)' : 'var(--text-caption)',
                  }}
                >
                  {phase.label}
                </span>
                <span style={{ fontSize: '0.7rem', textAlign: 'center', color: 'var(--text-caption)' }}>
                  {phase.subtitle}
                </span>
              </button>
              {i < PHASES.length - 1 && (
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    background: isPast ? 'var(--success-text)' : 'var(--border)',
                    marginBottom: '1.4rem',
                  }}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
