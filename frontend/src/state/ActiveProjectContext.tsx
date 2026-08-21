import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { DEFAULT_CASE_ID, useActiveCase } from './ActiveCaseContext'

const BASE_STORAGE_KEY = 'softsense.activeProject'

// Same per-case namespacing as ActiveDatasetContext.tsx -- see its comment
// for why the default case keeps the original bare key unchanged.
function storageKeyFor(caseId: string): string {
  return caseId === DEFAULT_CASE_ID ? BASE_STORAGE_KEY : `${BASE_STORAGE_KEY}.${caseId}`
}

interface ActiveProjectContextValue {
  activeProject: string
  setActiveProject: (id: string) => void
}

const ActiveProjectContext = createContext<ActiveProjectContextValue | null>(null)

export function ActiveProjectProvider({ children }: { children: ReactNode }) {
  const { activeCaseId } = useActiveCase()
  const [activeProject, setActiveProjectState] = useState(
    () => localStorage.getItem(storageKeyFor(activeCaseId)) ?? '',
  )

  // Re-derive whenever the active case changes, so switching cases shows
  // that case's own remembered project (or blank) without a page reload.
  useEffect(() => {
    setActiveProjectState(localStorage.getItem(storageKeyFor(activeCaseId)) ?? '')
  }, [activeCaseId])

  function setActiveProject(id: string) {
    setActiveProjectState(id)
    const key = storageKeyFor(activeCaseId)
    if (id) localStorage.setItem(key, id)
    else localStorage.removeItem(key)
  }

  return (
    <ActiveProjectContext.Provider value={{ activeProject, setActiveProject }}>
      {children}
    </ActiveProjectContext.Provider>
  )
}

// Carries the project created by "Apply Preprocessing & Split Dataset" on
// Feature Selection into Train Model so its "Choose a Project" dropdown
// doesn't ask the user to pick what they just created -- scoped per What-If
// case (see storageKeyFor above), since projects are now fully case-isolated
// on the backend too.
export function useActiveProject() {
  const ctx = useContext(ActiveProjectContext)
  if (!ctx) throw new Error('useActiveProject must be used within ActiveProjectProvider')
  return ctx
}
