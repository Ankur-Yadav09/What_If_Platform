import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { router } from './routes'
import { ActiveCaseProvider } from './state/ActiveCaseContext'
import { ActiveDatasetProvider } from './state/ActiveDatasetContext'
import { ActiveProjectProvider } from './state/ActiveProjectContext'
import { ActiveWhatIfProvider } from './state/ActiveWhatIfContext'
import './theme/theme.css'

const queryClient = new QueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ActiveCaseProvider>
        <ActiveDatasetProvider>
          <ActiveProjectProvider>
            <ActiveWhatIfProvider>
              <RouterProvider router={router} />
            </ActiveWhatIfProvider>
          </ActiveProjectProvider>
        </ActiveDatasetProvider>
      </ActiveCaseProvider>
    </QueryClientProvider>
  </StrictMode>,
)
