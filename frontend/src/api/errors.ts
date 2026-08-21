/**
 * Extracts a human-readable message from an axios error. FastAPI's
 * `detail` field is a plain string for HTTPException, but an ARRAY of
 * {loc, msg, type} objects for its own request-validation errors (422s
 * raised before a route handler even runs — e.g. a malformed multipart
 * body) — both shapes need handling, or a validation-array error silently
 * falls through to whatever generic fallback the caller supplies, hiding
 * the actual problem. Also handles the no-`.response` case (network
 * failure, CORS block, timeout), which axios reports very differently
 * from an HTTP error response.
 */
export function extractErrorMessage(error: unknown, fallback: string): string {
  const err = error as {
    message?: string
    response?: { data?: { detail?: unknown }; status?: number }
    request?: unknown
  }

  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    const messages = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
      .filter(Boolean)
    if (messages.length) return messages.join('; ')
  }

  if (err?.response?.status) {
    return `Request failed (HTTP ${err.response.status}). ${fallback}`
  }
  if (err?.request) {
    return 'No response from the server — check that the backend is running and reachable.'
  }
  return err?.message || fallback
}
