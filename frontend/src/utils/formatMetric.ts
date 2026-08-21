// Adaptive-precision number formatting for What-If Analysis's process
// values (temperatures, pressures, flows, RPMs, power in the tens to
// hundred-thousands) -- a flat .toFixed(3) reads like a raw sensor dump on
// a 6-figure value (e.g. "196233.387"); real dashboards drop precision as
// magnitude grows and add thousands separators. Small values (deltas,
// fractional readings) keep their precision since 3 decimals is meaningful
// there.
export function formatMetric(value: number, opts?: { forceSign?: boolean }): string {
  if (!Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  const decimals = abs >= 1000 ? 0 : abs >= 10 ? 1 : 3
  const formatted = value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  const sign = opts?.forceSign && value > 0 ? '+' : ''
  return `${sign}${formatted}`
}
