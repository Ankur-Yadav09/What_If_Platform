import { useMemo, useState } from 'react'

interface Column<T> {
  header: string
  render: (row: T) => React.ReactNode
  /** When provided, the column header becomes clickable to sort by this raw
   * value (string/number/null) rather than the rendered node -- columns
   * without it stay exactly as before (no indicator, not clickable), so
   * every existing DataTable usage is unaffected unless it opts in. */
  sortValue?: (row: T) => string | number | null
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  keyFn: (row: T) => string
  emptyMessage?: string
  /** When set, caps the visible height to roughly this many body rows and scrolls the rest vertically instead of growing the page. */
  maxVisibleRows?: number
}

const HEADER_ROW_HEIGHT = 42
const BODY_ROW_HEIGHT = 42

export function DataTable<T>({ columns, rows, keyFn, emptyMessage, maxVisibleRows }: DataTableProps<T>) {
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const sortedRows = useMemo(() => {
    if (sortCol === null) return rows
    const col = columns[sortCol]
    if (!col?.sortValue) return rows
    const dir = sortDir === 'desc' ? -1 : 1
    // Nulls (missing/non-numeric values) always sort to the end, regardless
    // of direction -- "no data" isn't meaningfully "smallest" or "largest".
    return [...rows].sort((a, b) => {
      const va = col.sortValue!(a)
      const vb = col.sortValue!(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb)) * dir
    })
  }, [rows, columns, sortCol, sortDir])

  function handleSort(i: number) {
    if (sortCol !== i) {
      setSortCol(i)
      setSortDir('asc')
    } else {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    }
  }

  if (rows.length === 0) {
    return <p className="caption">{emptyMessage ?? 'Nothing here yet.'}</p>
  }
  return (
    <div
      className={maxVisibleRows ? 'data-table-scroll' : undefined}
      style={{
        overflowX: 'auto',
        ...(maxVisibleRows
          ? { maxHeight: HEADER_ROW_HEIGHT + maxVisibleRows * BODY_ROW_HEIGHT, overflowY: 'auto' }
          : {}),
      }}
    >
      <table>
        <thead>
          <tr>
            {columns.map((col, i) => (
              <th
                key={col.header}
                onClick={col.sortValue ? () => handleSort(i) : undefined}
                style={col.sortValue ? { cursor: 'pointer', userSelect: 'none' } : undefined}
                title={col.sortValue ? `Sort by ${col.header}` : undefined}
              >
                {col.header}
                {col.sortValue && (
                  <span style={{ marginLeft: '0.35rem', opacity: sortCol === i ? 1 : 0.35 }}>
                    {sortCol === i ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr key={keyFn(row)}>
              {columns.map((col) => (
                <td key={col.header}>{col.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
