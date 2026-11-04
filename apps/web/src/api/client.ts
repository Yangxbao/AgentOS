import type { ApiErrorBody } from './types'

/** 后端地址：默认本机 8000，可用 VITE_API_BASE 覆盖（不要指向 0.0.0.0）。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly detail: Record<string, unknown>
  readonly requestId: string

  constructor(status: number, body: ApiErrorBody | null, fallbackMessage: string) {
    super(body?.error?.message ?? fallbackMessage)
    this.name = 'ApiError'
    this.status = status
    this.code = body?.error?.code ?? 'UNKNOWN'
    this.detail = body?.error?.detail ?? {}
    this.requestId = body?.error?.request_id ?? '-'
  }
}

type RequestOptions = {
  body?: unknown
  signal?: AbortSignal
  /** 并发控制：写操作带上最后一次读到的 updated_at */
  expectedUpdatedAt?: string
  idempotencyKey?: string
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    // 本地防护要求写请求携带该头（§11.8）；读请求带上也无害
    'X-AgentOS-Client': 'web',
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.expectedUpdatedAt) headers['If-Match'] = options.expectedUpdatedAt
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    throw new ApiError(0, null, `无法连接后端（${API_BASE}）：${(error as Error).message}`)
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload as ApiErrorBody | null, `请求失败（HTTP ${response.status}）`)
  }
  return payload as T
}

export const api = {
  baseUrl: API_BASE,
  get: <T>(path: string, options?: Omit<RequestOptions, 'body'>) => request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>) =>
    request<T>('POST', path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>) =>
    request<T>('PUT', path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>) =>
    request<T>('PATCH', path, { ...options, body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'body'>) => request<T>('DELETE', path, options),
}
