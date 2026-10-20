export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}
let token = (() => { try { return sessionStorage.getItem('nx_token') || '' } catch { return '' } })()
export const hasToken = () => !!token
export function setToken(t: string) {
  token = t
  try { t ? sessionStorage.setItem('nx_token', t) : sessionStorage.removeItem('nx_token') } catch { /* stockage indisponible */ }
}
export const newKey = () => crypto.randomUUID()

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown; key?: string } = {}): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (opts.key) headers['Idempotency-Key'] = opts.key
  const res = await fetch(`/api${path}`, { method: opts.method || 'GET', headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) })
  let data: any = null
  try { data = await res.json() } catch { /* corps vide */ }
  if (res.status === 401 && token) { setToken(''); window.dispatchEvent(new Event('nx-logout')) }
  if (!res.ok) throw new ApiError(res.status, data?.error || 'http_error', data?.message || (typeof data?.detail === 'string' ? data.detail : JSON.stringify(data?.detail ?? res.statusText)))
  return data as T
}

export type Role = 'fondateur' | 'operateur' | 'lecture'
export const rank: Record<Role, number> = { lecture: 0, operateur: 1, fondateur: 2 }
export interface Me { username: string; role: Role }
