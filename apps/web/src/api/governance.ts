import { api } from './client'
import type { Page } from './types'

export interface EffectivePermissions {
  employee_id: string
  permissions: Record<string, unknown>
  sources: Record<string, { layer: string; value: unknown }[]>
}

export interface AssignmentResult {
  decision_id: string
  candidates: {
    employee_id: string
    name: string
    model: string
    score: number
    factors: Record<string, number>
  }[]
  excluded: { employee_id: string; name: string; reason: string }[]
  reviewer: {
    employee_id: string
    name: string
    model: string
    pool: string
    independence: string
    cross_model: boolean
    cross_provider: boolean
    degraded_reviewer: boolean
    warnings: string[]
  } | null
  reviewer_reason_code: string | null
  reviewer_suggestion: string | null
  data_quality: Record<string, string>
  score_note: string
  algorithm_version: string
}

export interface AuditRow {
  id: number
  actor_type: string
  actor_id: string
  action: string
  target_type: string
  target_id: string
  detail: Record<string, unknown>
  request_id: string
  created_at: string | null
}

export const governanceApi = {
  effectivePermissions: (employeeId: string) =>
    api.get<EffectivePermissions>(`/api/v1/employees/${employeeId}/effective-permissions`),
  capabilities: (employeeId: string) => api.get<Record<string, unknown>>(`/api/v1/employees/${employeeId}/capabilities`),
  preview: (companyId: string, payload: Record<string, unknown>) =>
    api.post<AssignmentResult>(`/api/v1/companies/${companyId}/assignments/preview`, payload),
  audit: (params = '') => api.get<Page<AuditRow>>(`/api/v1/audit?page_size=100${params}`),
}
