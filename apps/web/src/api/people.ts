import { api } from './client'
import type { Page } from './types'

export interface ModelConnection {
  id: string
  company_id: string
  name: string
  provider: string
  model: string
  api_key_ref: string
  has_credential: boolean
  base_url: string | null
  timeout_s: number
  max_retries: number
  last_health_check_at: string | null
  last_health_status: 'ok' | 'fail' | null
  last_health_latency_ms: number | null
  enabled: boolean
  updated_at: string | null
}

export interface Provider {
  id: string
  label: string
  api_key_env: string
  models: { id: string; label: string; context_window: number; cost_tier: string }[]
}

export interface EmployeePosition {
  position_id: string
  name: string
  is_primary: boolean
  department_id: string | null
  /** 岗位是否具备审查资格（派工审核人过滤用；后端仍硬校验） */
  can_review?: boolean
}

export interface Employee {
  id: string
  company_id: string
  department_id: string | null
  name: string
  avatar: string
  title: string
  bio: string
  personality: string
  status: 'active' | 'disabled' | 'archived'
  reports_to: string | null
  primary_model_id: string
  fallback_model_id: string | null
  adapter_type: string
  tools_allowed: string[]
  permission_profile: Record<string, unknown>
  positions: EmployeePosition[]
  model: {
    primary: ModelConnection | null
    fallback: ModelConnection | null
    health: boolean | null
    health_source: string
  }
  updated_at: string | null
}

export const peopleApi = {
  providers: () => api.get<{ providers: Provider[] }>('/api/v1/model-providers'),
  listConnections: (companyId: string) =>
    api.get<ModelConnection[]>(`/api/v1/companies/${companyId}/model-connections`),
  createConnection: (companyId: string, payload: Record<string, unknown>) =>
    api.post<ModelConnection>(`/api/v1/companies/${companyId}/model-connections`, payload),
  testConnection: (id: string) => api.post<{ ok: boolean; latency_ms: number }>(`/api/v1/model-connections/${id}/test`, {}),
  deleteConnection: (id: string) => api.delete<void>(`/api/v1/model-connections/${id}`),

  listEmployees: (companyId: string) =>
    api.get<Page<Employee>>(`/api/v1/companies/${companyId}/employees?page_size=200`),
  createEmployee: (companyId: string, payload: Record<string, unknown>) =>
    api.post<Employee>(`/api/v1/companies/${companyId}/employees`, payload),
  getEmployee: (id: string) => api.get<Employee>(`/api/v1/employees/${id}`),
  patchEmployee: (id: string, payload: Record<string, unknown>) =>
    api.patch<Employee>(`/api/v1/employees/${id}`, payload),
  setStatus: (id: string, action: 'enable' | 'disable') =>
    api.post<Employee>(`/api/v1/employees/${id}/${action}`, {}),
  bindModels: (id: string, payload: { primary_model_id: string; fallback_model_id?: string | null; reason?: string }) =>
    api.put<{ warnings: string[]; primary_model_id: string }>(`/api/v1/employees/${id}/model-binding`, payload),
  deleteEmployee: (id: string) => api.delete<void>(`/api/v1/employees/${id}`),
}
