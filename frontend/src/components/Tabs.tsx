import { useState } from 'react'
import type { ReactNode } from 'react'

interface Tab {
  label: string
  content: ReactNode
  /** Shows a small checkmark next to the label when true. Optional — omit
   * for tabs with no natural "done" state (e.g. purely informational ones). */
  complete?: boolean
}

interface TabsProps {
  tabs: Tab[]
  defaultIndex?: number
  /** Controlled mode: pass both to drive the active tab from a parent (e.g.
   * to default to "the first incomplete section"). Omit both for the
   * original uncontrolled behavior (internal state, unchanged for existing
   * callers). */
  activeIndex?: number
  onChange?: (index: number) => void
}

export function Tabs({ tabs, defaultIndex = 0, activeIndex, onChange }: TabsProps) {
  const [internalActive, setInternalActive] = useState(defaultIndex)
  const active = activeIndex ?? internalActive

  function select(i: number) {
    if (onChange) onChange(i)
    else setInternalActive(i)
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          width: '100%',
          borderBottom: '1px solid var(--border)',
          marginBottom: '1.25rem',
        }}
      >
        {tabs.map((tab, i) => (
          <button
            key={tab.label}
            onClick={() => select(i)}
            style={{
              flex: '1 1 0%',
              minWidth: 0,
              background: 'transparent',
              boxShadow: 'none',
              color: active === i ? 'var(--primary)' : 'var(--text-caption)',
              fontWeight: active === i ? 700 : 500,
              borderRadius: 0,
              borderBottom: active === i ? '2px solid var(--primary)' : '2px solid transparent',
              padding: '0.6rem 0.9rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.4rem',
              textAlign: 'center',
            }}
          >
            {tab.label}
            {tab.complete && (
              <span style={{ color: 'var(--success-text)', fontSize: '0.8rem' }} title="Complete">
                ✓
              </span>
            )}
          </button>
        ))}
      </div>
      <div>{tabs[active].content}</div>
    </div>
  )
}
