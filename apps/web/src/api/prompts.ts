import { api } from './client'

export interface PromptRevision {
  id: string
  employee_id: string
  version: number
  file_path: string
  content_hash: string
  note: string
  is_active: boolean
  created_at: string | null
}

export const promptsApi = {
  list: (employeeId: string) => api.get<PromptRevision[]>(`/api/v1/employees/${employeeId}/prompts`),
  create: (employeeId: string, content: string, note = '') =>
    api.post<PromptRevision>(`/api/v1/employees/${employeeId}/prompts`, { content, note }),
  get: (revisionId: string) =>
    api.get<PromptRevision & { content: string }>(`/api/v1/prompts/${revisionId}`),
  activate: (revisionId: string) => api.post<PromptRevision>(`/api/v1/prompts/${revisionId}/activate`, {}),
  diff: (revisionId: string) => api.get<{ diff: string }>(`/api/v1/prompts/${revisionId}/diff`),
}
