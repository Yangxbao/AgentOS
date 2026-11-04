export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    detail: Record<string, unknown>
    request_id: string
  }
}

export interface HealthResponse {
  status: string
  mode: string
  version: string
}
