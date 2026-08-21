import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

// Read directly by api/client.ts's request interceptor too (interceptors run
// outside React, so they can't use useActiveCase() -- this key is the single
// source of truth for "which case is active" app-wide).
export const ACTIVE_CASE_STORAGE_KEY = 'softsense.activeCaseId'
export const DEFAULT_CASE_ID = 'default'

interface ActiveCaseContextValue {
  activeCaseId: string
  setActiveCaseId: (caseId: string) => void
}

const ActiveCaseContext = createContext<ActiveCaseContextValue | null>(null)

export function ActiveCaseProvider({ children }: { children: ReactNode }) {
  const [activeCaseId, setActiveCaseIdState] = useState(
    () => localStorage.getItem(ACTIVE_CASE_STORAGE_KEY) ?? DEFAULT_CASE_ID,
  )

  function setActiveCaseId(caseId: string) {
    setActiveCaseIdState(caseId)
    localStorage.setItem(ACTIVE_CASE_STORAGE_KEY, caseId)
  }

  return (
    <ActiveCaseContext.Provider value={{ activeCaseId, setActiveCaseId }}>{children}</ActiveCaseContext.Provider>
  )
}

// The one "which case is currently open" pointer, app-wide -- scopes
// What-If config/models and the Soft Sensor model registry/saved_models
// (see backend/app/services/whatif_case_service.py's docstring). Provided at
// the app root (main.tsx) rather than nested under What-If Studio only,
// since the Soft Sensor pages (Data Health/Feature Discovery/Build Model/
// Experiment History) are also case-scoped per the case-isolation plan.
export function useActiveCase() {
  const ctx = useContext(ActiveCaseContext)
  if (!ctx) throw new Error('useActiveCase must be used within ActiveCaseProvider')
  return ctx
}
