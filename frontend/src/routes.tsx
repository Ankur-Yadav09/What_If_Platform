import { createBrowserRouter } from 'react-router-dom'
import { Layout } from './layout/Layout'
import { AppOverviewPage } from './pages/Overview/AppOverviewPage'
import { FeatureSelectionPage } from './pages/FeatureSelection/FeatureSelectionPage'
import { ExperimentHistoryPage } from './pages/SoftSensor/ExperimentHistoryPage'
import { SoftSensorOverviewPage } from './pages/SoftSensor/OverviewPage'
import { PredictPage } from './pages/Predict/PredictPage'
import { PreprocessPage } from './pages/Preprocess/PreprocessPage'
import { TrainPage } from './pages/Train/TrainPage'
import { UploadPage } from './pages/Upload/UploadPage'
import { DashboardPage } from './pages/WhatIf/DashboardPage'
import { WhatIfOverviewPage } from './pages/WhatIf/OverviewPage'
import { WhatIfSetupPage } from './pages/WhatIf/WhatIfSetupPage'

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <AppOverviewPage /> },
      { path: '/soft-sensor-overview', element: <SoftSensorOverviewPage /> },
      { path: '/upload', element: <UploadPage /> },
      { path: '/preprocess', element: <PreprocessPage /> },
      { path: '/feature-selection', element: <FeatureSelectionPage /> },
      { path: '/train', element: <TrainPage /> },
      { path: '/predict', element: <PredictPage /> },
      { path: '/experiment-history', element: <ExperimentHistoryPage /> },
      { path: '/what-if/overview', element: <WhatIfOverviewPage /> },
      { path: '/what-if/case-setup', element: <WhatIfSetupPage /> },
      { path: '/what-if/dashboard', element: <DashboardPage /> },
    ],
  },
])
