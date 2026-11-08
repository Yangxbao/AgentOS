import { api } from './client'
import type { Page } from './types'

export type TaskState =
  | 'draft' | 'pending' | 'queued' | 'running' | 'paused' | 'awaiting_approval'
  | 'rework_required' | 'succeeded' | 'failed' | 'cancelled' | 'skipped'
  | 'review_passed' | 'in_review'

export interface PlanStep {
  id: string
  title?: string
  employee_id: string
  employee_name?: string
  instruction: string
  deliverable?: string
  depends_on: string[]
  tools?: string[]
}

export interface Task {
  id: string
  company_id: string
  department_id: string | null
  parent_task_id: string | null
  root_task_id: string | null
  depth: number
  title: string
  objective: string
  instruction: string
  deliverable: string
  priority: string
  risk_level: string
  state: TaskState
  assignee_employee_id: string | null
  reviewer_employee_id: string | null
  approval_required: boolean
  approval_stage: string
  budget_usd: number | null
  execution_mode: string
  due_at: string | null
  plan: { version?: number; steps: PlanStep[]; max_parallel?: number }
  result: Record<string, unknown>
  context: Record<string, unknown>
  rework_count: number
  max_rework: number
  cancel_requested: boolean
  pause_requested: boolean
  children_count: number
  version: number
  started_at: string | null
  ended_at: string | null
  created_at: string | null
  updated_at: string | null
  assignee_name?: string
}

export interface AgentRun {
  id: string
  task_run_id: string
  employee_id: string | null
  employee_name: string
  role: string
  adapter_type: string
  model: string
  step_id: string | null
  prompt_version: number | null
  state: string
  error: string | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  started_at: string | null
  ended_at: string | null
}

export interface TaskRun {
  id: string
  task_id: string
  run_no: number
  trigger: string
  state: string
  mode: string
  error: string | null
  checkpoint: { completed_steps?: string[]; outputs?: Record<string, unknown> }
  started_at: string | null
  ended_at: string | null
  agent_runs: AgentRun[]
}

export interface Approval {
  id: string
  task_id: string
  task_run_id: string | null
  gate: string
  status: string
  requested_by: string
  reviewer_employee_id: string | null
  decided_by: string | null
  comment: string
  rewind_step_id: string | null
  created_at: string | null
  decided_at: string | null
  task_title?: string
}

export interface UsageRecord {
  agent_run_id: string
  employee_id: string | null
  employee_name: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number | null
  latency_ms: number
  billable: boolean
  created_at: string | null
}

export interface UsageSummary {
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  total_cost_usd: number
  unknown_cost_records: number
  calls: number
  by_employee: { employee_id: string; employee_name: string; cost_usd: number; calls: number }[]
  by_model: { model: string; cost_usd: number; calls: number }[]
  records: UsageRecord[]
}

export interface TaskDetail extends Task {
  children: Task[]
  employees: Record<string, { id: string; name: string; title: string }>
  runs: TaskRun[]
  active_run: TaskRun | null
  approvals: Approval[]
  pending_approvals: Approval[]
  usage: UsageSummary
  allowed_transitions: string[]
}

export interface TimelineItem {
  kind: 'event' | 'agent_run' | 'approval' | 'handoff' | 'tool_call'
  type: string
  at: string
  payload?: Record<string, unknown>
  step_id?: string
  employee_name?: string
  model?: string
  state?: string
  summary?: string
  status?: string
  comment?: string
  tool?: string
  tool_call_id?: string
  risk?: string
  error_code?: string | null
  duration_ms?: number
}

export interface DenialTop {
  code: string
  count: number
}

export interface ToolStats {
  total: number
  by_status: Record<string, number>
  denials_top: DenialTop[]
}

export interface BudgetWatchItem {
  task_id: string
  title: string
  state: string
  budget_usd: number
  spent_usd: number
  ratio: number
}

export interface BudgetWatch {
  default_budget_usd: number | null
  watching: BudgetWatchItem[]
}

export interface MonitorSummary {
  company_id: string
  task_total: number
  states: Record<string, number>
  active_runs: number
  pending_approvals: number
  today_cost_usd: number
  today_calls: number
  failed_tasks: number
  recent_agent_runs: AgentRun[]
  tool_execution?: { enabled: boolean }
  tools?: ToolStats
  budgets?: BudgetWatch
}

export const tasksApi = {
  list: (companyId: string, params: Record<string, string | number | boolean> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    ).toString()
    return api.get<Page<Task>>(
      `/api/v1/companies/${companyId}/tasks${query ? `?${query}` : ''}`,
    )
  },
  create: (companyId: string, payload: Record<string, unknown>) =>
    api.post<Task>(`/api/v1/companies/${companyId}/tasks`, payload),
  detail: (taskId: string) => api.get<TaskDetail>(`/api/v1/tasks/${taskId}`),
  update: (taskId: string, payload: Record<string, unknown>) =>
    api.patch<Task>(`/api/v1/tasks/${taskId}`, payload),
  run: (taskId: string) =>
    api.post<{ run_id: string; run_no: number; state: string; mode: string }>(
      `/api/v1/tasks/${taskId}/run`, {},
    ),
  pause: (taskId: string) =>
    api.post<{ state: string; pending: boolean }>(`/api/v1/tasks/${taskId}/pause`, {}),
  resume: (taskId: string) =>
    api.post<{ run_id: string; run_no: number }>(`/api/v1/tasks/${taskId}/resume`, {}),
  retry: (taskId: string) =>
    api.post<{ run_id: string; run_no: number }>(`/api/v1/tasks/${taskId}/retry`, {}),
  cancel: (taskId: string) =>
    api.post<{ state: string; pending: boolean }>(`/api/v1/tasks/${taskId}/cancel`, {}),
  setPlan: (taskId: string, payload: { steps: Partial<PlanStep>[]; max_parallel?: number }) =>
    api.put<TaskDetail>(`/api/v1/tasks/${taskId}/plan`, payload),
  timeline: (taskId: string) =>
    api.get<{ items: TimelineItem[]; total: number }>(`/api/v1/tasks/${taskId}/timeline`),
  approvals: (taskId: string) => api.get<Approval[]>(`/api/v1/tasks/${taskId}/approvals`),
  pendingApprovals: (params: { status_filter?: string } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).map(([key, value]) => [key, String(value)]),
    ).toString()
    return api.get<Page<Approval>>(`/api/v1/approvals${query ? `?${query}` : ''}`)
  },
  decide: (approvalId: string, payload: Record<string, unknown>) =>
    api.post<{ approval: Approval; state: string; run_id: string | null }>(
      `/api/v1/approvals/${approvalId}/decision`, payload,
    ),
  monitor: (companyId: string) =>
    api.get<MonitorSummary>(`/api/v1/monitor/summary?company_id=${companyId}`),
}
