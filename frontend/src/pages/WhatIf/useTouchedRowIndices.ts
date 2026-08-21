import { useState } from 'react'

// Tracks which table row indices the user has actively edited in this
// session, so they can be exempted from section-scope visibility filtering
// (see caseSetupHelpers.inSectionScope). Without this, the instant a row's
// Section is set/typed to a value outside the currently active scope, the
// row disappears from the visible table mid-edit — indistinguishable from
// the edit "not working" (this affected PiTagMappingEditor, ModelMappingEditor,
// and MvDvCvTagListEditor, which all share the same allowed-scope filter).
export function useTouchedRowIndices() {
  const [touched, setTouched] = useState<Set<number>>(new Set())

  function markTouched(index: number) {
    setTouched((prev) => (prev.has(index) ? prev : new Set(prev).add(index)))
  }

  // Call when the row at `index` is removed, so tracked indices stay
  // aligned with every later row shifting down by one.
  function onRowRemoved(index: number) {
    setTouched((prev) => {
      const next = new Set<number>()
      for (const i of prev) {
        if (i === index) continue
        next.add(i > index ? i - 1 : i)
      }
      return next
    })
  }

  return { touched, markTouched, onRowRemoved }
}
