import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'
import { tasksApi, type TaskState } from '../api/tasks'

const STATE_LABEL: Record<string, string> = {
  draft: '草稿', pending: '待调度', queued: '排队中', running: '执行中',
  paused: '已暂停', awaiting_approval: '待审批', rework_required: '待返工',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过',
  review_passed: '已通过（遗留）', in_review: '审查中（遗留）',
}

const STATE_STYLE: Record<string, string> = {
  draft: 'bg-slate-800 text-slate-300',
  pending: 'bg-slate-800 text-slate-300',
  queued: 'bg-sky-900 text-sky-300',
  running: 'bg-blue-900 text-blue-300',
  paused: 'bg-amber-900 text-amber-300',
  awaiting_approval: 'bg-purple-900 text-purple-300',
  rework_required: 'bg-orange-900 text-orange-300',
  succeeded: 'bg-emerald-900 text-emerald-300',
  failed: 'bg-red-900 text-red-300',
  cancelled: 'bg-slate-800 text-slate-500',
}

export function StateBadge({ state }: { state: TaskState | string }) {
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${STATE_STYLE[state] ?? 'bg-slate-800 text-slate-300'}`}>
      {STATE_LABEL[state] ?? state}
    </span>
  )
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

const PRIORITIES = ['low', 'normal', 'high', 'urgent']
const RISKS = ['low', 'medium', 'high', 'critical']

export default function TasksPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const [stateFilter, setStateFilter] = useState('')
  const tasks = useQuery({
    queryKey: ['tasks', activeCompanyId, stateFilter],
    queryFn: () => tasksApi.list(activeCompanyId as string, {
      page_size: 100, ...(stateFilter ? { state: stateFilter } : {}),
    }),
    enabled: Boolean(activeCompanyId),
    refetchInterval: 3000,
  })
  const employees = useQuery({
    queryKey: ['employees', activeCompanyId],
    queryFn: () => peopleApi.listEmployees(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [assignee, setAssignee] = useState('')
  const [priority, setPriority] = useState('normal')
  const [risk, setRisk] = useState('low')
  const [dueAt, setDueAt] = useState('')
  const [approval, setApproval] = useState(false)
  const [mode, setMode] = useState('auto')

  const activeEmployees = useMemo(
    () => (employees.data?.items ?? []).filter((item) => item.status === 'active'),
    [employees.data],
  )
  useEffect(() => {
    if (!assignee && activeEmployees.length > 0) setAssignee(activeEmployees[0].id)
  }, [activeEmployees, assignee])

  const createTask = useMutation({
    mutationFn: () => tasksApi.create(activeCompanyId as string, {
      title: title.trim(),
      objective: objective.trim(),
      assignee_employee_id: assignee,
      priority,
      risk_level: risk,
      due_at: dueAt ? new Date(dueAt).toISOString() : null,
      approval_required: approval,
      execution_mode: mode,
    }),
    onSuccess: (task) => {
      setTitle('')
      setObjective('')
      setApproval(false)
      setOpen(false)
      setMessage(`任务「${task.title}」已创建`)
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  return (
    <div className="p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">任务中心</h1>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          value={activeCompanyId ?? ''}
          onChange={(event) => setCompanyId(event.target.value)}
        >
          {(companies.data?.items ?? []).map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          value={stateFilter}
          onChange={(event) => setStateFilter(event.target.value)}
        >
          <option value="">全部状态</option>
          {Object.entries(STATE_LABEL).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <span className="text-xs text-slate-500">共 {tasks.data?.total ?? 0} 个任务</span>
        <button
          className="ml-auto rounded bg-sky-600 px-4 py-1.5 text-sm text-white"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? '收起' : '新建任务'}
        </button>
      </div>

      {message && (
        <div className="mt-3 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>
      )}

      {open && (
        <section className="mt-4 grid gap-3 rounded border border-slate-800 bg-slate-900/40 p-4 md:grid-cols-2">
          <label className="text-sm text-slate-300">
            标题
            <input className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                   value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="text-sm text-slate-300">
            执行员工
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={assignee} onChange={(event) => setAssignee(event.target.value)}>
              {activeEmployees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.name}{employee.title ? `（${employee.title}）` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-300 md:col-span-2">
            目标 / 指令
            <textarea className="mt-1 h-24 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                      value={objective} onChange={(event) => setObjective(event.target.value)} />
          </label>
          <label className="text-sm text-slate-300">
            优先级
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={priority} onChange={(event) => setPriority(event.target.value)}>
              {PRIORITIES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-300">
            风险等级
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={risk} onChange={(event) => setRisk(event.target.value)}>
              {RISKS.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-300">
            截止时间
            <input type="datetime-local" className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                   value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
          </label>
          <label className="text-sm text-slate-300">
            执行模式
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={mode} onChange={(event) => setMode(event.target.value)}>
              <option value="auto">自动（跟随 AGENTOS_MODEL_MODE）</option>
              <option value="mock">Mock（不调用外部模型）</option>
              <option value="real">真实模型</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={approval} onChange={(event) => setApproval(event.target.checked)} />
            执行前需要人工审批
          </label>
          <div className="md:col-span-2">
            <button
              className="rounded bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50"
              disabled={!title.trim() || !assignee || createTask.isPending}
              onClick={() => createTask.mutate()}
            >
              创建
            </button>
          </div>
        </section>
      )}

      <table className="mt-4 w-full text-left text-sm">
        <thead className="text-xs text-slate-500">
          <tr>
            <th className="py-2">任务</th>
            <th>状态</th>
            <th>执行员工</th>
            <th>优先级</th>
            <th>子任务</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          {(tasks.data?.items ?? []).map((task) => (
            <tr key={task.id} className="border-t border-slate-800">
              <td className="py-2">
                <Link className="text-sky-400 hover:underline" to={`/tasks/${task.id}`}>{task.title}</Link>
                <div className="text-xs text-slate-500">{task.objective.slice(0, 60)}</div>
              </td>
              <td><StateBadge state={task.state} /></td>
              <td className="text-slate-300">{task.assignee_name || '—'}</td>
              <td className="text-slate-400">{task.priority}</td>
              <td className="text-slate-400">{task.children_count}</td>
              <td className="text-xs text-slate-500">{task.updated_at?.replace('T', ' ').slice(0, 19)}</td>
            </tr>
          ))}
          {(tasks.data?.items ?? []).length === 0 && (
            <tr><td className="py-6 text-slate-500" colSpan={6}>还没有任务，点右上角新建。</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
