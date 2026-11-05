import { api } from './client'

export interface MemoryItem {
  id: string
  company_id: string | null
  scope: 'employee' | 'project' | 'company'
  employee_id: string | null
  project_task_id: string | null
  kind: string
  title: string
  content: string
  tags: string[]
  status: string
  created_by: string
  created_by_type: string
  created_at: string
  updated_at: string
  duplicate?: boolean
}

export const memoryApi = {
  list: (companyId: string, params: Record<string, string | number> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    ).toString()
    return api.get<{ items: MemoryItem[]; total: number }>(
      `/api/v1/companies/${companyId}/memories${query ? `?${query}` : ''}`,
    )
  },
  create: (companyId: string, payload: Record<string, unknown>) =>
    api.post<MemoryItem>(`/api/v1/companies/${companyId}/memories`, payload),
  update: (id: string, payload: Record<string, unknown>) =>
    api.patch<MemoryItem>(`/api/v1/memories/${id}`, payload),
  remove: (id: string) => api.delete<{ id: string; status: string }>(`/api/v1/memories/${id}`),
  promote: (id: string, toScope: 'project' | 'company') =>
    api.post<MemoryItem>(`/api/v1/memories/${id}/promote`, { to_scope: toScope }),
  search: (params: { q: string; company_id?: string; top_k?: number }) => {
    const query = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    ).toString()
    return api.get<{ items: MemoryItem[]; total: number }>(`/api/v1/memories/search?${query}`)
  },
}
