import { api } from './client'
import type { Page } from './types'

export interface Company {
  id: string
  name: string
  description: string
  policy: Record<string, unknown>
  status: 'active' | 'archived'
  created_at: string | null
  updated_at: string | null
}

export interface Department {
  id: string
  company_id: string
  parent_id: string | null
  name: string
  code: string
  description: string
  sort_order: number
  depth: number
  created_at: string | null
  updated_at: string | null
}

export interface Position {
  id: string
  company_id: string
  department_id: string | null
  name: string
  level: string
  is_managerial: boolean
  can_review: boolean
  review_capability_tags: string[]
  responsibilities: string
  default_permissions: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface OrgNode extends Department {
  positions: Position[]
  children: OrgNode[]
  employee_count: number
}

export interface OrgTree {
  company: Pick<Company, 'id' | 'name' | 'status' | 'policy'>
  departments: OrgNode[]
  unassigned_positions: Position[]
}

export const orgApi = {
  listCompanies: () => api.get<Page<Company>>('/api/v1/companies?page_size=200'),
  createCompany: (payload: { name: string; description?: string }) =>
    api.post<Company>('/api/v1/companies', payload),
  archiveCompany: (id: string) => api.post<Company>(`/api/v1/companies/${id}/archive`, {}),

  listDepartments: (companyId: string) =>
    api.get<Page<Department>>(`/api/v1/companies/${companyId}/departments?page_size=200`),
  orgTree: (companyId: string) => api.get<OrgTree>(`/api/v1/companies/${companyId}/org-tree`),
  createDepartment: (companyId: string, payload: { name: string; parent_id?: string | null }) =>
    api.post<Department>(`/api/v1/companies/${companyId}/departments`, payload),
  deleteDepartment: (id: string) => api.delete<void>(`/api/v1/departments/${id}`),

  listPositions: (companyId: string) =>
    api.get<Page<Position>>(`/api/v1/companies/${companyId}/positions?page_size=200`),
  createPosition: (
    companyId: string,
    payload: { name: string; department_id?: string | null; can_review?: boolean },
  ) => api.post<Position>(`/api/v1/companies/${companyId}/positions`, payload),
  deletePosition: (id: string) => api.delete<void>(`/api/v1/positions/${id}`),
}
