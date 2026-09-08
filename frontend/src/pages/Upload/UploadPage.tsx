import { useState } from 'react'
import { useActiveDataset } from '../../state/ActiveDatasetContext'
import { AIRecommendationCard } from './AIRecommendationCard'
import { DataPreviewSection } from './DataPreviewSection'
import { UploadNewDatasetWizard } from './UploadNewDatasetWizard'
import { UseExistingDatasetTab } from './UseExistingDatasetTab'

type SourceTab = 'existing' | 'new'

interface UploadPageProps {
  // UploadPage is only ever rendered embedded inside What-If Studio's Model
  // Config tab now — "Continue" always moves to the next in-page phase
  // (Data Health), so this is required, not a fallback path.
  onContinue: () => void
}

export function UploadPage({ onContinue }: UploadPageProps) {
  const [tab, setTab] = useState<SourceTab>('existing')
  const { activeDataset: selectedName, setActiveDataset: setSelectedName } = useActiveDataset()

  function handleUploadAnother() {
    setSelectedName('')
    setTab('new')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.75rem' }}>
      <div>
        <h1>Connect Process Data</h1>
        <p className="caption">Connect historical process data to begin building an AI-powered Virtual Sensor.</p>
      </div>

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          className={tab === 'existing' ? 'chip active' : 'chip'}
          onClick={() => setTab('existing')}
        >
          1. Use Existing Dataset
        </button>
        <button
          className={tab === 'new' ? 'chip active' : 'chip'}
          onClick={() => setTab('new')}
        >
          2. Upload New Dataset
        </button>
      </div>

      {tab === 'existing' ? (
        <UseExistingDatasetTab selectedName={selectedName} onSelect={setSelectedName} />
      ) : (
        <UploadNewDatasetWizard onUploaded={(summary) => setSelectedName(summary.name)} />
      )}

      {selectedName && (
        <>
          <DataPreviewSection datasetName={selectedName} />
          <AIRecommendationCard datasetName={selectedName} />

          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button onClick={onContinue}>Continue to Data Health Assessment →</button>
            <button className="chip" onClick={handleUploadAnother}>Upload Another Dataset</button>
          </div>
        </>
      )}
    </div>
  )
}
