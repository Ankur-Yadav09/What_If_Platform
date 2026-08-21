import axios from 'axios'
import { ACTIVE_CASE_STORAGE_KEY, DEFAULT_CASE_ID } from '../state/ActiveCaseContext'

// Proxied to the FastAPI backend by vite.config.ts's dev-server proxy.
export const apiClient = axios.create({ baseURL: '/api' })

// Case-scoped route families: What-If config/models/dashboard, the Soft
// Sensor model registry/saved_models bridge, and (as of full per-case data
// isolation) datasets/preprocessing/Feature Selection projects too (see the
// case-isolation plan's "Full-stack case isolation scope"). Every request
// to one of these gets ?case_id=<active case> attached automatically --
// reading straight from localStorage (not useActiveCase()) since this
// interceptor runs outside React and must stay in sync with whatever the
// active case is at request time, including on the very first render.
const CASE_SCOPED_URL_PREFIX = /^\/(what-if|overview|training|predict|datasets|preprocess|projects|feature-selection)(\/|$)/

apiClient.interceptors.request.use((config) => {
  if (config.url && CASE_SCOPED_URL_PREFIX.test(config.url)) {
    const caseId = localStorage.getItem(ACTIVE_CASE_STORAGE_KEY) ?? DEFAULT_CASE_ID
    config.params = { ...config.params, case_id: caseId }
  }
  return config
})
