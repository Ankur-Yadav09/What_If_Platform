import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { getDates, getTimestamps } from '../../api/whatIf'

interface TimestampSelectorProps {
  selectedDate: string
  onDateChange: (date: string) => void
  selectedTimestamp: string
  onTimestampChange: (ts: string) => void
}

const WEEKDAY_LABELS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTH_LABELS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function parseYMD(date: string): { year: number; month: number; day: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!m) return null
  return { year: Number(m[1]), month: Number(m[2]) - 1, day: Number(m[3]) }
}

function ymd(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// "22 Jan 2025, 10:00:00" from a "YYYY-MM-DD" date + a "YYYY-MM-DD HH:MM:SS" timestamp.
function formatDisplay(date: string, timestamp: string): string {
  const parsed = parseYMD(date)
  if (!parsed) return ''
  const timePart = timestamp.includes(' ') ? timestamp.split(' ')[1] : timestamp
  return `${parsed.day} ${MONTH_LABELS[parsed.month].slice(0, 3)} ${parsed.year}, ${timePart}`
}

// A single combined Date-Time Picker for choosing a historical process
// snapshot: a calendar (only days the historian actually has data for are
// selectable) on the left, and that day's available snapshot times on the
// right — replaces two separate date/timestamp <select>s with one cohesive
// control, matching the "select a date, then its time" two-step flow.
// Nothing is confirmed (onDateChange/onTimestampChange fire together) until
// an available time is actually clicked, so browsing a different day never
// silently changes what's currently loaded below.
export function TimestampSelector({
  selectedDate, onDateChange, selectedTimestamp, onTimestampChange,
}: TimestampSelectorProps) {
  const [open, setOpen] = useState(false)
  const [pendingDate, setPendingDate] = useState(selectedDate)
  const [viewYear, setViewYear] = useState<number | null>(null)
  const [viewMonth, setViewMonth] = useState<number | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const datesQuery = useQuery({ queryKey: ['whatif-dates'], queryFn: getDates })
  const timestampsQuery = useQuery({
    queryKey: ['whatif-timestamps', pendingDate],
    queryFn: () => getTimestamps(pendingDate),
    enabled: !!pendingDate,
  })

  const availableDates = useMemo(() => new Set(datesQuery.data ?? []), [datesQuery.data])

  // Years actually present in the historian — lets a user jump straight to
  // e.g. 2 years back without clicking the ‹ arrow a dozen times. shiftMonth
  // below clamps to this same [min, max] range, so ‹/› and the dropdowns
  // never disagree about how far back/forward there is to go.
  const availableYears = useMemo(() => {
    const years = new Set((datesQuery.data ?? []).map((d) => parseYMD(d)?.year).filter((y): y is number => !!y))
    return [...years].sort((a, b) => a - b)
  }, [datesQuery.data])
  const minYear = availableYears[0]
  const maxYear = availableYears[availableYears.length - 1]

  // First-ever default (nothing confirmed yet): pick the most recent
  // available date, matching this control's previous default behavior.
  useEffect(() => {
    if (!selectedDate && datesQuery.data && datesQuery.data.length > 0) {
      const latest = datesQuery.data[datesQuery.data.length - 1]
      setPendingDate(latest)
      onDateChange(latest)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datesQuery.data])

  // Same first-ever default, for the timestamp: only fires when nothing is
  // confirmed yet (guarded on !selectedTimestamp) — once a real snapshot has
  // been confirmed once, browsing a different day in the calendar must wait
  // for an explicit time click, never auto-jump to one on the user's behalf.
  useEffect(() => {
    if (!selectedTimestamp && timestampsQuery.data && timestampsQuery.data.length > 0) {
      onDateChange(pendingDate)
      onTimestampChange(timestampsQuery.data[timestampsQuery.data.length - 1])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timestampsQuery.data])

  // Every time the picker opens, resume browsing from whatever snapshot is
  // currently confirmed (so reopening shows its month/day, not wherever a
  // previous, abandoned browse session left off).
  useEffect(() => {
    if (!open) return
    setPendingDate(selectedDate)
    const base = parseYMD(selectedDate) ?? (datesQuery.data?.length ? parseYMD(datesQuery.data[datesQuery.data.length - 1]) : null)
    if (base) {
      setViewYear(base.year)
      setViewMonth(base.month)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function shiftMonth(delta: number) {
    if (viewYear === null || viewMonth === null) return
    let y = viewYear
    let m = viewMonth + delta
    if (m < 0) { m = 11; y -= 1 }
    if (m > 11) { m = 0; y += 1 }
    if (minYear !== undefined && y < minYear) return
    if (maxYear !== undefined && y > maxYear) return
    setViewYear(y)
    setViewMonth(m)
  }

  function pickTime(ts: string) {
    onDateChange(pendingDate)
    onTimestampChange(ts)
    setOpen(false)
  }

  const grid = useMemo(() => {
    if (viewYear === null || viewMonth === null) return []
    const firstWeekday = new Date(viewYear, viewMonth, 1).getDay()
    const numDays = new Date(viewYear, viewMonth + 1, 0).getDate()
    const cells: (string | null)[] = []
    for (let i = 0; i < firstWeekday; i++) cells.push(null)
    for (let d = 1; d <= numDays; d++) cells.push(ymd(viewYear, viewMonth, d))
    while (cells.length % 7 !== 0) cells.push(null)
    return cells
  }, [viewYear, viewMonth])

  const displayLabel = selectedDate && selectedTimestamp
    ? formatDisplay(selectedDate, selectedTimestamp)
    : 'Select a historical snapshot…'

  return (
    <div>
      <div className="caption">Historical Process Snapshot</div>
      <div ref={rootRef} style={{ position: 'relative', maxWidth: 360, marginTop: '0.3rem' }}>
        <div
          onClick={() => setOpen((o) => !o)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.5rem',
            background: 'var(--control-bg)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: '0.5rem 0.8rem',
            minHeight: 38,
            cursor: 'pointer',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
            🗓️ {displayLabel}
          </span>
          <span style={{ color: 'var(--text-caption)' }}>{open ? '▲' : '▼'}</span>
        </div>

        {open && (
          <div
            className="card"
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: 4,
              zIndex: 30,
              padding: '0.9rem',
              width: 360,
            }}
          >
            {/* ‹, Month, Year, Time, › all together — quick-jump controls
                grouped in one place instead of a separate side panel. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', marginBottom: '0.5rem' }}>
              <button
                className="chip"
                onClick={() => shiftMonth(-1)}
                disabled={viewYear !== null && viewMonth !== null && minYear !== undefined && viewYear === minYear && viewMonth === 0}
                style={{ padding: '0.15rem 0.45rem' }}
              >
                ‹
              </button>
              <select
                value={viewMonth ?? ''}
                onChange={(e) => setViewMonth(Number(e.target.value))}
                style={{ fontSize: '0.72rem', padding: '0.2rem 0.15rem', flex: '1 1 0' }}
              >
                {MONTH_LABELS.map((label, i) => (
                  <option key={label} value={i}>{label.slice(0, 3)}</option>
                ))}
              </select>
              <select
                value={viewYear ?? ''}
                onChange={(e) => setViewYear(Number(e.target.value))}
                style={{ fontSize: '0.72rem', padding: '0.2rem 0.15rem', flex: '1 1 0' }}
              >
                {availableYears.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
              <button
                className="chip"
                onClick={() => shiftMonth(1)}
                disabled={viewYear !== null && viewMonth !== null && maxYear !== undefined && viewYear === maxYear && viewMonth === 11}
                style={{ padding: '0.15rem 0.45rem' }}
              >
                ›
              </button>
              {timestampsQuery.isLoading ? (
                <span className="caption" style={{ fontSize: '0.68rem' }}>…</span>
              ) : (
                <select
                  disabled={(timestampsQuery.data ?? []).length === 0}
                  value={selectedTimestamp && timestampsQuery.data?.includes(selectedTimestamp) ? selectedTimestamp : ''}
                  onChange={(e) => e.target.value && pickTime(e.target.value)}
                  style={{ fontSize: '0.72rem', padding: '0.2rem 0.15rem', flex: '1 1 0' }}
                >
                  <option value="" disabled>
                    {(timestampsQuery.data ?? []).length === 0 ? 'No times' : 'Time…'}
                  </option>
                  {(timestampsQuery.data ?? []).map((ts) => (
                    <option key={ts} value={ts}>
                      {ts.split(' ')[1] ?? ts}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2, textAlign: 'center' }}>
              {WEEKDAY_LABELS.map((w) => (
                <div key={w} className="caption" style={{ fontSize: '0.68rem', fontWeight: 700 }}>
                  {w}
                </div>
              ))}
              {grid.map((day, i) => {
                if (!day) return <div key={i} />
                const isAvailable = availableDates.has(day)
                const isPending = day === pendingDate
                return (
                  <button
                    key={day}
                    disabled={!isAvailable}
                    onClick={() => setPendingDate(day)}
                    title={isAvailable ? undefined : 'No data for this date'}
                    style={{
                      padding: '0.32rem 0',
                      fontSize: '0.78rem',
                      borderRadius: 6,
                      fontWeight: isPending ? 700 : 500,
                      background: isPending ? 'var(--primary)' : isAvailable ? 'var(--info-bg)' : 'transparent',
                      color: isPending ? 'white' : isAvailable ? 'var(--text-main)' : 'var(--text-faint)',
                      border: 'none',
                      cursor: isAvailable ? 'pointer' : 'not-allowed',
                    }}
                  >
                    {day.slice(-2).replace(/^0/, '')}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
