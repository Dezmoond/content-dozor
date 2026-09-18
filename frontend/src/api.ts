const API = '/api/v1'
const TOKEN_KEY = 'platform_token'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setAuthToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearAuthToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {})
  const token = getStoredToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  const r = await fetch(`${API}${path}`, { ...init, headers })
  if (r.status === 401) {
    clearAuthToken()
  }
  if (!r.ok) throw new Error(await r.text())
  const ct = r.headers.get('content-type') || ''
  if (ct.includes('application/json')) return r.json()
  return (await r.text()) as T
}

export async function login(email: string, password: string) {
  const r = await fetch(`${API}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: email, password }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json() as Promise<{ access_token: string; token_type: string }>
}

export async function register(email: string, password: string) {
  return api<{ id: string; email: string; role: string }>('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, role: 'analyst' }),
  })
}

export const getMe = () => api<{ id: string; email: string; role: string }>('/auth/me')
export const getUsers = () => api<Array<{ id: string; email: string; role: string }>>('/auth/users')

export const getCases = () => api<any[]>('/cases')
export const createCase = (title: string) =>
  api('/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) })
export const getCase = (id: string) => api(`/cases/${id}`)
export const getCaseStats = (id: string) => api(`/cases/${id}/stats`)
export const patchCase = (id: string, body: Record<string, unknown>) =>
  api(`/cases/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
export const deleteCase = (id: string) =>
  api<{ ok: boolean; id: string }>(`/cases/${id}`, { method: 'DELETE' })

export const getSettings = () => api<Record<string, unknown>>('/settings')
export const putSetting = (key: string, value: unknown) =>
  api(`/settings/${key}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value }) })

export type DatabaseConfigPayload = {
  engine: string
  host?: string
  port?: number
  user?: string
  password?: string
  dbname?: string
  init_schema?: boolean
}

export const testDatabase = (body: DatabaseConfigPayload) =>
  api<{ ok: boolean; message: string }>('/database/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const createDatabase = (body: DatabaseConfigPayload) =>
  api<{ ok: boolean; message: string; schema?: string | null }>('/database/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const getAudit = () => api<any[]>('/audit')
export const getParsers = () =>
  api<{ parsers: string[]; items?: Array<{ id: string; name: string }> }>('/parsers')
export const runParser = (parser_id: string) =>
  api('/parsers/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parser_id }) })
export const getPlugins = () => api<any[]>('/plugins')

export type JobStatus = {
  id: string
  status: string
  progress: number
  detail?: string | null
  result?: unknown
  celery_task_id?: string | null
  case_id?: string | null
  document_id?: string | null
}

export const getJob = (jobId: string) => api<JobStatus>(`/jobs/${jobId}`)

export async function ingestSource(
  caseId: string,
  body: {
    sourceType: string
    analysisMode?: 'deep' | 'shallow'
    file?: File | null
    text?: string
    url?: string
    includeComments?: boolean
  },
) {
  const fd = new FormData()
  fd.append('source_type', body.sourceType)
  fd.append('analysis_mode', body.analysisMode || 'deep')
  if (body.url?.trim()) fd.append('url', body.url.trim())
  if (body.text?.trim()) fd.append('text', body.text)
  fd.append('include_comments', body.includeComments === false ? 'false' : 'true')
  if (body.file) fd.append('file', body.file)
  const token = getStoredToken()
  const headers: HeadersInit = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const r = await fetch(`${API}/cases/${caseId}/ingest`, { method: 'POST', body: fd, headers })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export type IngestSourceType = {
  id: string
  label: string
  description: string
  input_kind: 'file' | 'text' | 'url' | 'url_or_file'
  accept: string[]
  needs_internet: 'never' | 'optional' | 'required'
  include_comments: boolean
  status: 'ready' | 'expanding'
  placeholder: string
  hint: string
}

export const getIngestSources = () =>
  api<{ items: IngestSourceType[]; online: boolean }>('/ingest/sources')

export async function uploadDocument(
  caseId: string,
  file: File,
  options?: { analysis_mode?: 'deep' | 'shallow' },
) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('analysis_mode', options?.analysis_mode || 'deep')
  const token = getStoredToken()
  const headers: HeadersInit = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const r = await fetch(`${API}/cases/${caseId}/documents`, { method: 'POST', body: fd, headers })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function fetchCaseHtmlReport(caseId: string): Promise<string> {
  const token = getStoredToken()
  const headers: HeadersInit = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const r = await fetch(`${API}/reports/${caseId}/html`, { headers })
  if (!r.ok) throw new Error(await r.text())
  return r.text()
}

export async function analyzeText(text: string) {
  return api('/analyze/text', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}
