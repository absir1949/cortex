const BASE = '/api'

export class ApiError extends Error {
  status: number
  body: any
  constructor(status: number, message: string, body: any) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function request<T>(method: string, path: string, body?: any): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return undefined as any
  const json = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(res.status, json?.detail || res.statusText, json)
  }
  return json
}

export const api = {
  get:    <T>(p: string) => request<T>('GET', p),
  post:   <T>(p: string, b?: any) => request<T>('POST', p, b),
  patch:  <T>(p: string, b?: any) => request<T>('PATCH', p, b),
  delete: (p: string) => request<void>('DELETE', p),
}
