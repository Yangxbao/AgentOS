import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { governanceApi, type AssignmentResult } from '../api/governance'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

export default function AssignmentPage() {
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null
  const employees = useQuery({
    queryKey: ['employees', activeCompanyId],
    queryFn: () => peopleApi.listEmployees(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const departments = useQuery({
    queryKey: ['departments', activeCompanyId],
    queryFn: () => orgApi.listDepartments(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  const [capabilities, setCapabilities] = useState('coding.python,test.unit')
  const [tools, setTools] = useState('file.write')
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

  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先创建公司。</p>

  return (
    <div className="space-y-6 p-6">
      <h2 className="text-lg font-semibold text-slate-100">派工预览</h2>
      <p className="text-xs text-slate-500">
        M1 只做预览与决策留痕，不会真正派发任务（M2 接入任务引擎）。performance / load 暂无真实数据。
      </p>

      <div className="grid gap-3 rounded border border-slate-800 p-4 md:grid-cols-3">
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="能力标签，逗号分隔" value={capabilities} onChange={(e) => setCapabilities(e.target.value)} />
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="工具授权，逗号分隔" value={tools} onChange={(e) => setTools(e.target.value)} />
        <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={risk} onChange={(e) => setRisk(e.target.value)}>
          {['low', 'medium', 'high', 'critical'].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
               placeholder="预算 USD" value={budget} onChange={(e) => setBudget(e.target.value)} />
        <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={preferDept} onChange={(e) => setPreferDept(e.target.value)}>
          <option value="">偏好部门（可选）</option>
          {departments.data?.items.map((dept) => <option key={dept.id} value={dept.id}>{dept.name}</option>)}
        </select>
        <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">执行人：默认最高分</option>
          {employees.data?.items.map((employee) => (
            <option key={employee.id} value={employee.id}>{employee.name}</option>
          ))}
        </select>
        <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50 md:col-span-3"
                disabled={preview.isPending} onClick={() => preview.mutate()}>
          计算候选人
        </button>
      </div>

      {message && <div className="rounded border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-200">{message}</div>}

      {result && (
        <div className="space-y-4">
          <section>
            <h3 className="text-sm font-medium text-slate-200">候选人</h3>
            <div className="mt-2 space-y-2">
              {result.candidates.map((candidate) => (
                <div key={candidate.employee_id} className="rounded border border-slate-800 p-3 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-100">{candidate.name}</span>
                    <span className="text-sky-300">{candidate.score.toFixed(3)}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{candidate.model}</div>
                  <div className="mt-2 grid grid-cols-5 gap-2 text-xs text-slate-400">
                    {Object.entries(candidate.factors).map(([key, value]) => (
                      <div key={key}>
                        <div>{key}</div>
                        <div className="mt-1 h-1.5 rounded bg-slate-800">
                          <div className="h-1.5 rounded bg-sky-600" style={{ width: `${value * 100}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {result.candidates.length === 0 && <p className="text-sm text-slate-500">没有满足硬过滤的候选人。</p>}
            </div>
          </section>

          <section className="text-sm">
            <h3 className="text-sm font-medium text-slate-200">被排除</h3>
            <ul className="mt-2 space-y-1 text-xs text-slate-500">
              {result.excluded.map((item) => <li key={item.employee_id}>{item.name}：{item.reason}</li>)}
              {result.excluded.length === 0 && <li>无</li>}
            </ul>
          </section>

          <section className="rounded border border-slate-800 p-3 text-sm">
            <h3 className="text-sm font-medium text-slate-200">审查人</h3>
            {result.reviewer ? (
              <div className="mt-1 text-slate-300">
                {result.reviewer.name}（{result.reviewer.independence} / {result.reviewer.pool}）
                <span className="ml-2 text-xs text-slate-500">
                  {result.reviewer.cross_provider ? '跨供应商' : result.reviewer.cross_model ? '同供应商跨模型' : '同模型'}
                  {result.reviewer.degraded_reviewer ? ' · 降级审查人' : ''}
                </span>
              </div>
            ) : (
              <div className="mt-1 text-amber-400 text-xs">
                无合格审查人：{result.reviewer_reason_code} — {result.reviewer_suggestion}
              </div>
            )}
            <div className="mt-2 text-xs text-slate-500">{result.score_note}</div>
          </section>
        </div>
      )}
    </div>
  )
}
