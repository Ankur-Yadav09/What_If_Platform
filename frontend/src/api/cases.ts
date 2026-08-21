import { apiClient } from './client'
import type { WhatIfCase } from './types'

// Note: these 3 endpoints don't scope by the *current* active case (there's
// nothing to scope -- listing/creating/opening cases is how the active case
// itself gets chosen), so the case-scoping request interceptor in client.ts
// attaching case_id here is harmless but unused server-side.

export async function listCases(): Promise<WhatIfCase[]> {
  const { data } = await apiClient.get<{ cases: WhatIfCase[] }>('/what-if/cases')
  return data.cases
}

export async function createCase(name: string): Promise<WhatIfCase> {
  const { data } = await apiClient.post<WhatIfCase>('/what-if/cases', { name })
  return data
}

export async function openCase(caseId: string): Promise<WhatIfCase> {
  const { data } = await apiClient.post<WhatIfCase>(`/what-if/cases/${encodeURIComponent(caseId)}/open`)
  return data
}
