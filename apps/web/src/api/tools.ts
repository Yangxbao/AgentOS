import { api } from './client'
import type { Page } from './types'

export type WorkspaceGrant = {
  employee_id: string
  employee_name: string
  access: 'read' | 'write'
  granted_by: string
  granted_at: string | null
}

export type Workspace = {
  id: string
  company_id: string
  name: string
  slug: string
  root_path: string
  mode: 'read_only' | 'read_write'
  status: 'active' | 'archived'
  description: string
  created_by: string
  created_at: string | null
  updated_at: string | null
  grants: WorkspaceGrant[]
}

export type ToolSpec = {
  name: string
  category: 'file_read' | 'file_write' | 'network' | 'shell'
  description: string
  risk: 'low' | 'medium' | 'high' | 'critical'
  side_effects: string
  idempotent: boolean
  timeout_s: number
  max_output_bytes: number
  requires_approval: boolean
  enabled_by_default: boolean
  enabled: boolean
  params: Record<string, unknown>
}

export type ToolCatalogue = {
  items: ToolSpec[]
  global_enabled: boolean
  shell_enabled: boolean
}

export type ToolPolicy = {
  enabled: boolean
  categories: Record<string, boolean>
  allowed_tools: string[]
  network_domains: string[]
  allow_http_write: boolean
  auto_execute_max_risk: string
  max_risk_level: string
  max_tool_calls_per_step: number
  approval_required_tools: string[]
}

export type ToolPolicyResponse = {
  global_enabled: boolean
  policy: ToolPolicy
  shell_enabled: boolean
}

export type ToolPermissionReport = {
  employee_id: string
  global_enabled: boolean
  company_enabled: boolean
  shell_enabled: boolean
  workspaces: string[]
  tools: Array<{
    tool: string
    category: string
    risk: string
    enabled: boolean
    requires_approval: boolean
    available: boolean
    reason: string
  }>
}

export type ToolCall = {
  id: string
  task_id: string | null
  task_run_id: string | null
  employee_id: string | null
  employee_name: string | null
  step_id: string
  call_index: number
  tool_name: string
  category: string
  risk_level: string
  status: string
  args_summary: Record<string, unknown>
  resolved_path: string
  output_summary: Record<string, unknown>
  output_bytes: number
  truncated: boolean
  error_code: string | null
  error_message: string | null
  duration_ms: number
  approval_id: string | null
  approval_status: string | null
  created_at: string | null
  ended_at: string | null
}

export const toolsApi = {
  listWorkspaces: (companyId: string) =>
    api.get<Workspace[]>(`/api/v1/companies/${companyId}/workspaces`),
  createWorkspace: (
    companyId: string,
    payload: { name: string; root_path?: string | null; mode?: string; description?: string },
  ) => api.post<Workspace>(`/api/v1/companies/${companyId}/workspaces`, payload),
  updateWorkspace: (id: string, payload: { name?: string; description?: string; mode?: string }) =>
    api.patch<Workspace>(`/api/v1/workspaces/${id}`, payload),
  archiveWorkspace: (id: string) => api.delete<Workspace>(`/api/v1/workspaces/${id}`),
  grant: (workspaceId: string, employeeId: string, access: 'read' | 'write') =>
    api.post<WorkspaceGrant>(`/api/v1/workspaces/${workspaceId}/grants`, {
      employee_id: employeeId,
      access,
    }),
  revoke: (workspaceId: string, employeeId: string) =>
    api.delete<void>(`/api/v1/workspaces/${workspaceId}/grants/${employeeId}`),

  catalogue: () => api.get<ToolCatalogue>('/api/v1/tools'),
  getPolicy: (companyId: string) =>
    api.get<ToolPolicyResponse>(`/api/v1/companies/${companyId}/tool-policy`),
  updatePolicy: (companyId: string, patch: Partial<ToolPolicy>) =>
    api.patch<ToolPolicyResponse>(`/api/v1/companies/${companyId}/tool-policy`, patch),
  employeePermissions: (employeeId: string) =>
    api.get<ToolPermissionReport>(`/api/v1/employees/${employeeId}/tool-permissions`),

  taskToolCalls: (taskId: string, page = 1, pageSize = 100) =>
    api.get<Page<ToolCall>>(`/api/v1/tasks/${taskId}/tool-calls?page=${page}&page_size=${pageSize}`),
  toolCall: (id: string) => api.get<ToolCall>(`/api/v1/tool-calls/${id}`),
}
