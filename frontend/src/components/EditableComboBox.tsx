import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface EditableComboBoxProps {
  value: string
  onChange: (next: string) => void
  options: string[]
  placeholder?: string
  style?: React.CSSProperties
}

// A free-text input with a real, click-to-open dropdown of suggestions --
// unlike a plain <input list="..."> (HTML <datalist>), which most browsers
// only reveal once the user starts typing rather than on focus/click like an
// actual dropdown. Typing still filters the list live, and any value not in
// `options` is accepted as-is (this is a suggestion list, not a restricted
// choice) -- matches MultiSelectDropdown.tsx's click-to-expand/click-outside
// pattern, just single-value and free-text instead of multi-select checkboxes.
//
// The option panel renders through a portal, positioned via the input's own
// bounding rect (position: fixed), rather than as a plain absolutely
// positioned child -- this component is used inside ModelMappingEditor's
// scrollable table wrapper, and a plain-child panel would get clipped by
// that ancestor's overflow for any row not near the very top.
export function EditableComboBox({ value, onChange, options, placeholder, style }: EditableComboBoxProps) {
  const [open, setOpen] = useState(false)
  // Whether the user has typed since this dropdown was last opened -- on a
  // row that already has a value (the common case for an uploaded config
  // file with every row filled in), filtering by `value` from the moment
  // the panel opens would narrow the list down to just that one row's own
  // current text, which looks exactly like "no suggestions" even though the
  // full option list is available. Opening (focus/click) always shows every
  // option first; only actually typing something new narrows it.
  const [searching, setSearching] = useState(false)
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  function updateRect() {
    const el = inputRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setRect({ top: r.bottom, left: r.left, width: r.width })
  }

  useEffect(() => {
    if (!open) return
    updateRect()
    function onScrollOrResize() {
      updateRect()
    }
    function onDocMouseDown(e: MouseEvent) {
      const target = e.target as Node
      if (inputRef.current?.contains(target) || panelRef.current?.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('scroll', onScrollOrResize, true)
    window.addEventListener('resize', onScrollOrResize)
    document.addEventListener('mousedown', onDocMouseDown)
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true)
      window.removeEventListener('resize', onScrollOrResize)
      document.removeEventListener('mousedown', onDocMouseDown)
    }
  }, [open])

  const filtered = searching && value.trim()
    ? options.filter((o) => o.toLowerCase().includes(value.trim().toLowerCase()))
    : options

  return (
    <div style={{ width: '100%', ...style }}>
      <input
        ref={inputRef}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value)
          setSearching(true)
          setOpen(true)
        }}
        onFocus={() => {
          setSearching(false)
          setOpen(true)
        }}
        style={{ width: '100%', fontWeight: 600, boxSizing: 'border-box' }}
      />
      {open &&
        rect &&
        createPortal(
          <div
            ref={panelRef}
            className="card"
            style={{
              position: 'fixed',
              top: rect.top + 4,
              left: rect.left,
              width: rect.width,
              maxHeight: 220,
              overflowY: 'auto',
              zIndex: 1000,
              padding: '0.3rem 0',
            }}
          >
            {filtered.length === 0 && (
              <div className="caption" style={{ padding: '0.4rem 0.8rem' }}>
                {options.length === 0 ? 'No suggestions yet — type a name.' : 'No matches — type a custom name.'}
              </div>
            )}
            {filtered.map((o) => (
              <div
                key={o}
                onMouseDown={(e) => {
                  e.preventDefault()
                  onChange(o)
                  setOpen(false)
                }}
                style={{ padding: '0.4rem 0.8rem', cursor: 'pointer' }}
              >
                {o}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </div>
  )
}
