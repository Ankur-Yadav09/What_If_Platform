import { createContext, useContext, useState } from 'react'
import type { ReactNode } from 'react'

const STORAGE_KEY = 'softsense.whatIfGeneratedTags'
const SECTION_STORAGE_KEY = 'softsense.whatIfTargetSection'

interface ActiveWhatIfContextValue {
  generatedTags: string[]
  setGeneratedTags: (tags: string[]) => void
  targetSection: string | null
  setTargetSection: (section: string | null) => void
}

const ActiveWhatIfContext = createContext<ActiveWhatIfContextValue | null>(null)

function readStored(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

function readStoredSection(): string | null {
  try {
    return localStorage.getItem(SECTION_STORAGE_KEY)
  } catch {
    return null
  }
}

export function ActiveWhatIfProvider({ children }: { children: ReactNode }) {
  const [generatedTags, setGeneratedTagsState] = useState<string[]>(readStored)
  const [targetSection, setTargetSectionState] = useState<string | null>(readStoredSection)

  function setGeneratedTags(tags: string[]) {
    setGeneratedTagsState(tags)
    if (tags.length) localStorage.setItem(STORAGE_KEY, JSON.stringify(tags))
    else localStorage.removeItem(STORAGE_KEY)
  }

  function setTargetSection(section: string | null) {
    setTargetSectionState(section)
    if (section) localStorage.setItem(SECTION_STORAGE_KEY, section)
    else localStorage.removeItem(SECTION_STORAGE_KEY)
  }

  return (
    <ActiveWhatIfContext.Provider value={{ generatedTags, setGeneratedTags, targetSection, setTargetSection }}>
      {children}
    </ActiveWhatIfContext.Provider>
  )
}

// Carries the Plant Configuration Wizard's generated tag list and the chosen
// Target Section from Case Setup into the Dashboard's tag-source resolution
// and scenario compute (there's no server-side session in this module — see
// backend/app/services/what_if_service.py).
export function useActiveWhatIf() {
  const ctx = useContext(ActiveWhatIfContext)
  if (!ctx) throw new Error('useActiveWhatIf must be used within ActiveWhatIfProvider')
  return ctx
}
