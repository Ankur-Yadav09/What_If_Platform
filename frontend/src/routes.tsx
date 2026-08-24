import { createBrowserRouter } from 'react-router-dom'
import { Layout } from './layout/Layout'
import { AppOverviewPage } from './pages/Overview/AppOverviewPage'
import { DashboardPage } from './pages/WhatIf/DashboardPage'
import { WhatIfOverviewPage } from './pages/WhatIf/OverviewPage'
import { WhatIfSetupPage } from './pages/WhatIf/WhatIfSetupPage'

// The former standalone "Soft Sensor Module" routes (/upload, /preprocess,
// /feature-selection, /train, /predict, /experiment-history,
// /soft-sensor-overview) were removed here -- nothing in the UI linked to
// them (see Sidebar.tsx), so they were dead, direct-URL-only routes. The
// pages themselves aren't gone: UploadPage, PreprocessPage,
// FeatureSelectionPage, TrainPage, and ExperimentHistoryPage are still very
// much in use, reused verbatim as embedded tabs inside What-If Studio's
// Model Config (see ModelConfigTab.tsx) -- only their standalone routes and
// the two pages with zero other callers (SoftSensor/OverviewPage.tsx,
// Predict/PredictPage.tsx) were deleted.
export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <AppOverviewPage /> },
      { path: '/what-if/overview', element: <WhatIfOverviewPage /> },
      { path: '/what-if/case-setup', element: <WhatIfSetupPage /> },
      { path: '/what-if/dashboard', element: <DashboardPage /> },
    ],
  },
])
