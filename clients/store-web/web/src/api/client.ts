const BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

type ParamValue = string | number | boolean | undefined | null

function query(params?: Record<string, ParamValue>): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function request<T>(
  method: string,
  path: string,
  params?: Record<string, ParamValue>,
  body?: unknown,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}${query(params)}`, {
      method,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json; charset=utf-8' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Không kết nối được máy chủ.')
  }

  if (response.status === 204) {
    return null as T
  }

  if (!response.ok) {
    let code = 'INVALID_RESPONSE'
    let message = `Máy chủ trả lỗi ${response.status}.`
    try {
      const parsed = (await response.json()) as { code?: string; message?: string }
      if (typeof parsed.code === 'string') code = parsed.code
      if (typeof parsed.message === 'string') message = parsed.message
    } catch {
      // Non-JSON body fallback
    }
    throw new ApiError(response.status, code, message)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(response.status, 'INVALID_RESPONSE', 'Máy chủ trả dữ liệu không đọc được.')
  }
}

export function apiGet<T>(path: string, params?: Record<string, ParamValue>): Promise<T> {
  return request<T>('GET', path, params)
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('POST', path, undefined, body)
}

export function apiDelete<T = void>(path: string): Promise<T> {
  return request<T>('DELETE', path)
}
