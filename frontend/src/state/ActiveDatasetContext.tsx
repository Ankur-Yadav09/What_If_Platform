import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { DEFAULT_CASE_ID, useActiveCase } from './ActiveCaseContext'

const BASE_STORAGE_KEY = 'softsense.activeDataset'

// The default case keeps the exact original, un-namespaced key -- this is
// what makes "the default case's connected dataset stays exactly as it was"
// true with zero migration, mirroring every other DEFAULT_CASE_ID-resolves-
// to-the-old-flat-thing pattern already used across case isolation. Any
// other case gets its own key, defaulting to blank until that case connects
// something of its own.
function storageKeyFor(caseId: string): string {
  return caseId === DEFAULT_CASE_ID ? BASE_STORAGE_KEY : `${BASE_STORAGE_KEY}.${caseId}`
}

interface ActiveDatasetContextValue {
  activeDataset: string
  setActiveDataset: (name: string) => void
}

const ActiveDatasetContext = createContext<ActiveDatasetContextValue | null>(null)

export function ActiveDatasetProvider({ children }: { children: ReactNode }) {
  const { activeCaseId } = useActiveCase()
  const [activeDataset, setActiveDatasetState] = useState(
    () => localStorage.getItem(storageKeyFor(activeCaseId)) ?? '',
  )

  // Re-derive whenever the active case changes, so switching cases shows
  // that case's own remembered selection (or blank, for a case that's never
  // had one) without needing a page reload.
  useEffect(() => {
    setActiveDatasetState(localStorage.getItem(storageKeyFor(activeCaseId)) ?? '')
  }, [activeCaseId])

  function setActiveDataset(name: string) {
    setActiveDatasetState(name)
    const key = storageKeyFor(activeCaseId)
    if (name) localStorage.setItem(key, name)
    else localStorage.removeItem(key)
  }

  return (
    <ActiveDatasetContext.Provider value={{ activeDataset, setActiveDataset }}>
      {children}
    </ActiveDatasetContext.Provider>
  )
}

// Carries the dataset chosen on Connect Process Data across Preprocessing and
// Feature Selection so those pages don't ask the user to pick it again --
// scoped per What-If case (see storageKeyFor above), since datasets are now
// fully case-isolated on the backend too.
export function useActiveDataset() {
  const ctx = useContext(ActiveDatasetContext)
  if (!ctx) throw new Error('useActiveDataset must be used within ActiveDatasetProvider')
  return ctx
}
