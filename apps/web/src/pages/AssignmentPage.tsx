import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { governanceApi, type AssignmentResult } from '../api/governance'
import { orgApi } from '../api/org'
import { tasksApi } from '../api/tasks'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

const FACTOR_LABEL: Record<string, string> = {
  position_match: '岗位匹配',
  review_chain_distance: '协作距离',
  performance: '历史表现',
  cost_efficiency: '成本效率',
  load: '当前负载',
}

const EXCLUDE_REASON: Record<string, string> = {
  no_model: '未绑定可用模型',
  capability_missing: '技能不满足要求',
  subordinate_not_allowed: '汇报链越级，不允许直接派工',
  excluded_by_request: '按你的要求手动排除',
}

const RISK_LABEL: Record<string, string> = {
  low: '低', medium: '中', high: '高', critical: '严重',
}

export default function AssignmentPage() {
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null
  const departments = useQuery({
    queryKey: ['departments', activeCompanyId],
    queryFn: () => orgApi.listDepartments(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  // 派单需求
  const [taskTitle, setTaskTitle] = useState('')
  const [objective, setObjective] = useState('')
  const [instruction, setInstruction] = useState('')
  const [capabilities, setCapabilities] = useState('')
  const [tools, setTools] = useState('fs.write_file')
  const [risk, setRisk] = useState('medium')
  const [budget, setBudget] = useState('1')
  const [preferDept, setPreferDept] = useState('')
  const [selected, setSelected] = useState('')
  const [result, setResult] = useState<AssignmentResult | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const preview = useMutation({
    mutationFn: () =>
      governanceApi.preview(activeCompanyId as string, {
        required_capabilities: capabilities.split(',').map((s) => s.trim()).filter(Boolean),
        required_tools: tools.split(',').map((s) => s.trim()).filter(Boolean),
        risk_level: risk,
        budget_usd: budget ? Number(budget) : null,
        prefer_department_id: preferDept || null,
        selected_employee_id: selected || null,
      }),
    onSuccess: (data) => {
      setResult(data)
      setMessage(null)
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const bestId = result?.candidates[0]?.employee_id
  const assigneeId = selected || bestId || ''
  const createTask = useMutation({
    mutationFn: () =>
      tasksApi.create(activeCompanyId as string, {
        title: taskTitle.trim(),
        objective: objective.trim(),
        instruction: (instruction.trim() || objective.trim()),
        assignee_employee_id: assigneeId,
        risk_level: risk,
        execution_mode: 'auto',
        budget_usd: budget ? Number(budget) : null,
      }),
    onSuccess: (task) => {
      setMessage(`已创建任务「${task.title}」并派工给 ${result?.candidates.find((c) => c.employee_id === assigneeId)?.name ?? '候选人'}。`)
      setResult(null)
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const canCreate = Boolean(
    taskTitle.trim() && objective.trim() && assigneeId && !createTask.isPending,
  )
  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先创建公司。</p>

  return (
    <div className="space-y-6 p-6">
      <h2 className="text-lg font-semibold text-slate-100">智能派单</h2>
      <p className="text-xs text-slate-500">
        填写任务需求 → 系统按岗位、技能、工具授权、成本与负载计算候选员工 → 选人并一键创建任务。
        推荐结果仅供参考，最终由你确认。
      </p>

      <div className="grid gap-3 rounded border border-slate-800 p-4 md:grid-cols-2">
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="任务标题（必填）" value={taskTitle}
               onChange={(e) => setTaskTitle(e.target.value)} />
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="任务目标一句话（会写入任务目标）" value={objective}
               onChange={(e) => setObjective(e.target.value)} />
        <textarea className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 md:col-span-2"
                  rows={3}
                  placeholder="详细执行指令（可选，留空则使用任务目标）" value={instruction}
                  onChange={(e) => setInstruction(e.target.value)} />
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="技能要求，逗号分隔（如 coding.python，可留空）" value={capabilities}
               onChange={(e) => setCapabilities(e.target.value)} />
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="所需工具，逗号分隔（如 fs.write_file,fs.read_file）" value={tools}
               onChange={(e) => setTools(e.target.value)} />
        <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={risk} onChange={(e) => setRisk(e.target.value)}>
          {Object.entries(RISK_LABEL).map(([value, label]) => (
            <option key={value} value={value}>风险等级：{label}</option>
          ))}
        </select>
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="预算 USD（可选）" value={budget}
               onChange={(e) => setBudget(e.target.value.replace(/[^0-9.]/g, ''))} />
        <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={preferDept} onChange={(e) => setPreferDept(e.target.value)}>
          <option value="">偏好部门（可选）</option>
          {departments.data?.items.map((dept) => <option key={dept.id} value={dept.id}>{dept.name}</option>)}
        </select>
        <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50 md:col-span-2"
                disabled={preview.isPending || !objective.trim()} onClick={() => preview.mutate()}>
          {preview.isPending ? '计算中…' : '计算候选员工'}
        </button>
      </div>

      {message && (
        <div className="rounded border border-sky-900 bg-sky-950 px-3 py-2 text-sm text-sky-200">
          {message}
          {createTask.isSuccess && (
            <Link className="ml-2 text-sky-400 underline" to="/tasks">去任务中心查看 →</Link>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-4">
          <section>
            <h3 className="text-sm font-medium text-slate-200">候选员工（按综合得分排序，点击选择执行人）</h3>
            <div className="mt-2 space-y-2">
              {result.candidates.map((candidate, index) => (
                <button key={candidate.employee_id}
                        className={`w-full rounded border p-3 text-left text-sm transition ${
                          assigneeId === candidate.employee_id
                            ? 'border-sky-500 bg-sky-950/40'
                            : 'border-slate-800 hover:border-slate-600'
                        }`}
                        onClick={() => setSelected(candidate.employee_id)}>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-100">
                      {index === 0 && <span className="mr-2 rounded bg-emerald-900 px-1.5 py-0.5 text-xs text-emerald-300">推荐</span>}
                      {candidate.name}
                    </span>
                    <span className="text-sky-300">得分 {candidate.score.toFixed(3)}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{candidate.model}</div>
                  <div className="mt-2 grid grid-cols-5 gap-2 text-xs text-slate-400">
                    {Object.entries(candidate.factors).map(([key, value]) => (
                      <div key={key}>
                        <div>{FACTOR_LABEL[key] ?? key}</div>
                        <div className="mt-1 h-1.5 rounded bg-slate-800">
                          <div className="h-1.5 rounded bg-sky-600" style={{ width: `${value * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </button>
              ))}
              {result.candidates.length === 0 && (
                <p className="text-sm text-slate-500">没有满足硬性条件的候选人——可降低技能/工具要求，或先去「AI 员工」页配置相应授权。</p>
              )}
            </div>
          </section>

          <section className="text-sm">
            <h3 className="text-sm font-medium text-slate-200">未入选（含原因）</h3>
            <ul className="mt-2 space-y-1 text-xs text-slate-500">
              {result.excluded.map((item) => (
                <li key={item.employee_id}>{item.name}：{EXCLUDE_REASON[item.reason] ?? item.reason}</li>
              ))}
              {result.excluded.length === 0 && <li>无</li>}
            </ul>
          </section>

          <section className="rounded border border-slate-800 p-3 text-sm">
            <h3 className="text-sm font-medium text-slate-200">审查人（自动推导，可留空交本地用户审批）</h3>
            {result.reviewer ? (
              <div className="mt-1 text-slate-300">
                {result.reviewer.name}
                <span className="ml-2 text-xs text-slate-500">
                  {result.reviewer.cross_provider ? '跨供应商隔离' : result.reviewer.cross_model ? '同供应商跨模型' : '同模型'}
                  {result.reviewer.degraded_reviewer ? ' · 降级审查人' : ''}
                </span>
              </div>
            ) : (
              <div className="mt-1 text-xs text-amber-400">
                无合格员工审查人（{result.reviewer_reason_code}）——创建任务时可交本地用户审批。
              </div>
            )}
          </section>

          <section className="rounded border border-emerald-800 bg-emerald-950/20 p-4">
            <h3 className="text-sm font-medium text-emerald-200">确认派工</h3>
            <p className="mt-1 text-xs text-slate-400">
              执行人：{result.candidates.find((c) => c.employee_id === assigneeId)?.name ?? '未选择'}
              · 风险：{RISK_LABEL[risk] ?? risk}
              {budget ? ` · 预算 $${budget}` : ''}
            </p>
            <button
              className="mt-3 rounded bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50"
              disabled={!canCreate}
              onClick={() => createTask.mutate()}
            >
              {createTask.isPending ? '创建中…' : '创建任务并派工'}
            </button>
            {!taskTitle.trim() && <p className="mt-2 text-xs text-amber-400">填写任务标题后即可创建。</p>}
          </section>
        </div>
      )}
    </div>
  )
}
