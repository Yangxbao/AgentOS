import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'
import { toolsApi } from '../api/tools'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

export default function EmployeesPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const employees = useQuery({
    queryKey: ['employees', activeCompanyId],
    queryFn: () => peopleApi.listEmployees(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const connections = useQuery({
    queryKey: ['connections', activeCompanyId],
    queryFn: () => peopleApi.listConnections(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const departments = useQuery({
    queryKey: ['departments', activeCompanyId],
    queryFn: () => orgApi.listDepartments(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  // 员工卡片概览用：本公司工作区授权关系（grants 含 employee_id）
  const workspaces = useQuery({
    queryKey: ['workspaces', activeCompanyId],
    queryFn: () => toolsApi.listWorkspaces(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const grantCountByEmployee = (() => {
    const counts: Record<string, number> = {}
    for (const workspace of workspaces.data ?? []) {
      for (const row of workspace.grants) {
        counts[row.employee_id] = (counts[row.employee_id] ?? 0) + 1
      }
    }
    return counts
  })()

  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [modelId, setModelId] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const createEmployee = useMutation({
    mutationFn: () =>
      peopleApi.createEmployee(activeCompanyId as string, {
        name: name.trim(),
        title: title.trim(),
        primary_model_id: modelId,
        department_id: departmentId || null,
      }),
    onSuccess: (employee) => {
      setName('')
      setTitle('')
      setMessage(`员工「${employee.name}」已入职`)
      queryClient.invalidateQueries({ queryKey: ['employees'] })
      queryClient.invalidateQueries({ queryKey: ['org-tree'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const toggleStatus = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'enable' | 'disable' }) =>
      peopleApi.setStatus(id, action),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['employees'] }),
    onError: (error) => setMessage(errorText(error)),
  })

  if (!activeCompanyId) {
    return <p className="p-6 text-slate-400">请先在组织设置中创建公司。</p>
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-100">AI 员工</h2>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
          value={activeCompanyId}
          onChange={(event) => setCompanyId(event.target.value)}
        >
          {companies.data?.items.map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
      </div>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">招聘新员工</h3>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                 placeholder="姓名" value={name} onChange={(e) => setName(e.target.value)} />
          <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                 placeholder="职位（如 首席分析官）" value={title} onChange={(e) => setTitle(e.target.value)} />
          <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
            <option value="">（直属公司）</option>
            {departments.data?.items.map((dept) => (
              <option key={dept.id} value={dept.id}>{dept.name}</option>
            ))}
          </select>
          <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">选择主模型连接…</option>
            {connections.data?.map((conn) => (
              <option key={conn.id} value={conn.id}>
                {conn.name}（{conn.model}）
              </option>
            ))}
          </select>
          <button
            className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={!name.trim() || !modelId || createEmployee.isPending}
            onClick={() => createEmployee.mutate()}
          >
            入职
          </button>
          {connections.data?.length === 0 && (
            <span className="text-xs text-amber-400">
              还没有模型连接，请先到「模型连接」页创建
            </span>
          )}
        </div>
      </section>

      <section className="space-y-2">
        {employees.data?.items.map((employee) => (
          <div key={employee.id} className="flex items-center justify-between rounded border border-slate-800 px-4 py-3">
            <div>
              <div className="flex items-center gap-2">
                <Link className="text-slate-100 hover:underline" to={`/employees/${employee.id}`}>
                  {employee.avatar || '🤖'} {employee.name}
                </Link>
                <span className="text-xs text-slate-500">{employee.title || '未设职位'}</span>
                <span className={`rounded px-2 py-0.5 text-xs ${
                  employee.status === 'active' ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-800 text-slate-400'
                }`}>
                  {employee.status === 'active' ? '在职' : '停用'}
                </span>
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {employee.positions.map((p) => p.name).join(' / ') || '无岗位'} ·{' '}
                {employee.model.primary?.model ?? '未绑定模型'}
                {employee.model.health === false && <span className="ml-2 text-red-400">模型异常</span>}
              </div>
              <div className="mt-1 flex items-center gap-3 text-xs">
                <span className={employee.tools_allowed.length > 0 ? 'text-sky-400' : 'text-amber-500'}>
                  已授权工具：{employee.tools_allowed.length} 项
                </span>
                <span className={grantCountByEmployee[employee.id] ? 'text-sky-400' : 'text-amber-500'}>
                  已授权工作区：{grantCountByEmployee[employee.id] ?? 0} 个
                </span>
                <Link className="text-sky-500 hover:underline" to={`/employees/${employee.id}`}>
                  编辑配置 →
                </Link>
              </div>
            </div>
            <button
              className="text-xs text-slate-400 hover:text-slate-200"
              onClick={() =>
                toggleStatus.mutate({ id: employee.id, action: employee.status === 'active' ? 'disable' : 'enable' })
              }
            >
              {employee.status === 'active' ? '停用' : '启用'}
            </button>
          </div>
        ))}
        {employees.data?.items.length === 0 && (
          <p className="text-sm text-slate-500">还没有员工，先在上面招聘一个。</p>
        )}
      </section>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}
    </div>
  )
}
