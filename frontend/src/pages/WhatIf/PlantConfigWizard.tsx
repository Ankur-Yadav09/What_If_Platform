import { useState } from 'react'
import type { DetectedCounts } from '../../api/types'

interface PlantConfigWizardProps {
  detectedCounts: DetectedCounts | undefined
  onGenerate: (counts: { cgc_stages: number; prc_stages: number; erc_stages: number; furnaces: number }) => void
  generating: boolean
  onReset: () => void
}

function CountField({
  icon, label, max, value, onChange,
}: { icon: string; label: string; max: number; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="caption" style={{ fontWeight: 600, marginBottom: '0.35rem' }}>
        {icon} {label}
      </div>
      {max === 0 ? (
        <p className="caption" style={{ margin: 0 }}>⚠️ No numbered tags detected for this question.</p>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <input
            type="number"
            min={0}
            max={max}
            value={value}
            onChange={(e) => onChange(Math.max(0, Math.min(max, Number(e.target.value))))}
            style={{ width: 72 }}
          />
          <span className="caption">of up to {max} detected</span>
        </div>
      )}
    </div>
  )
}

export function PlantConfigWizard({ detectedCounts, onGenerate, generating, onReset }: PlantConfigWizardProps) {
  const [cgc, setCgc] = useState(detectedCounts?.cgc_max ?? 0)
  const [prc, setPrc] = useState(detectedCounts?.prc_max ?? 0)
  const [erc, setErc] = useState(detectedCounts?.erc_max ?? 0)
  const [furnaces, setFurnaces] = useState(detectedCounts?.furnace_max ?? 0)

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: '0.4rem' }}>🧙 Plant Configuration Wizard</div>
      <p className="caption" style={{ marginTop: 0 }}>
        Answer the plant line-up questions — matching tags are automatically clubbed per section (CGC / PRC / ERC /
        Furnace).
      </p>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '1.25rem',
          marginTop: '1rem',
        }}
      >
        <CountField icon="🌀" label="CGC compressor stages" max={detectedCounts?.cgc_max ?? 0} value={cgc} onChange={setCgc} />
        <CountField icon="❄️" label="PRC compressor stages" max={detectedCounts?.prc_max ?? 0} value={prc} onChange={setPrc} />
        <CountField icon="🧊" label="ERC compressor stages" max={detectedCounts?.erc_max ?? 0} value={erc} onChange={setErc} />
        <CountField icon="🔥" label="Furnaces" max={detectedCounts?.furnace_max ?? 0} value={furnaces} onChange={setFurnaces} />
      </div>

      <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1.5rem' }}>
        <button
          disabled={generating}
          onClick={() => onGenerate({ cgc_stages: cgc, prc_stages: prc, erc_stages: erc, furnaces })}
        >
          {generating ? 'Generating…' : '⚡ Generate PI Mapping for this line-up'}
        </button>
        <button className="chip" onClick={onReset}>♻️ Reset mapping</button>
      </div>
    </div>
  )
}
