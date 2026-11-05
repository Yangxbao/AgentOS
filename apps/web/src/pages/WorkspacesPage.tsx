import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'
import { toolsApi, type Workspace } from '../api/tools'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

const MODE_LABEL: Record<string, string> = {
  read_only: '只读',
  read_write: '读写',
}

export default function WorkspacesPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const workspaces = useQuery({
    queryKey: ['workspaces', activeCompanyId],
    queryFn: () => toolsApi.listWorkspaces(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const employees = useQuery({
    queryKey: ['employees', activeCompanyId],
    queryFn: () => peopleApi.listEmployees(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const catalogue = useQuery({ queryKey: ['toolCatalogue'], queryFn: toolsApi.catalogue })

  const [name, setName] = useState('')
  const [rootPath, setRootPath] = useState('')
  const [mode, setMode] = useState('read_write')
  const [message, setMessage] = useState<string | null>(null)
  const [grantTarget, setGrantTarget] = useState<Record<string, string>>({})
  const [grantAccess, setGrantAccess] = useState<Record<string, string>>({})

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const create = useMutation({
    mutationFn: () =>
      toolsApi.createWorkspace(activeCompanyId as string, {
        name: name.trim(),
        root_path: rootPath.trim() || null,
        mode,
      }),
    onSuccess: (workspace) => {
      setName('')
      setRootPath('')
      setMessage(`工作区已创建：${workspace.root_path}`)
      refresh()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const rename = useMutation({
    mutationFn: (payload: { id: string; name: string }) =>
      toolsApi.updateWorkspace(payload.id, { name: payload.name }),
    onSuccess: () => { setMessage('已改名'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  const archive = useMutation({
    mutationFn: (id: string) => toolsApi.archiveWorkspace(id),
    onSuccess: () => { setMessage('已归档（磁盘文件保留）'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  const grant = useMutation({
    mutationFn: (payload: { workspaceId: string }) => {
      const employeeId = grantTarget[payload.workspaceId]
      const access = (grantAccess[payload.workspaceId] ?? 'read') as 'read' | 'write'
      if (!employeeId) throw new ApiError(0, null, '请选择员工')
      return toolsApi.grant(payload.workspaceId, employeeId, access)
    },
    onSuccess: () => { setMessage('授权已保存'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  const revoke = useMutation({
    mutationFn: (payload: { workspaceId: string; employeeId: string }) =>
      toolsApi.revoke(payload.workspaceId, payload.employeeId),
    onSuccess: () => { setMessage('授权已撤销（立即生效）'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先在组织设置中创建公司。</p>

  const toolsOff = catalogue.data ? !catalogue.data.global_enabled : false

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-100">工作区</h2>
        <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                value={activeCompanyId} onChange={(event) => setCompanyId(event.target.value)}>
          {companies.data?.items.map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
        <span className="text-xs text-slate-500">
          文件工具只能访问工作区内的路径；归档不会删除磁盘文件
        </span>
      </div>

      {toolsOff && (
        <div className="rounded border border-amber-800 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
          全局工具执行开关当前为关闭（AGENTOS_TOOL_EXECUTION=off），工作区仍可配置，但 Agent 无法调用任何工具。
        </div>
      )}
      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">新建工作区</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-4">
          <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
                 data-testid="ws-name"
                 placeholder="名称（同公司唯一）" value={name}
                 onChange={(event) => setName(event.target.value)} />
          <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm md:col-span-2"
                 placeholder="根目录绝对路径（留空则用 data/workspaces/<slug>）" value={rootPath}
                 onChange={(event) => setRootPath(event.target.value)} />
          <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
                  data-testid="ws-mode"
                  value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="read_write">读写</option>
            <option value="read_only">只读</option>
          </select>
        </div>
        <button className="mt-3 rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                data-testid="ws-create"
                disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
          创建工作区
        </button>
      </section>

      {workspaces.isLoading && <p className="text-sm text-slate-400">加载中…</p>}
      {workspaces.data?.length === 0 && (
        <p className="rounded border border-slate-800 p-4 text-sm text-slate-400">
          还没有工作区。Agent 需要至少一个工作区授权才能读写文件。
        </p>
      )}

      <div className="space-y-4">
        {workspaces.data?.map((workspace: Workspace) => (
          <section key={workspace.id}
                   className={`rounded border p-4 ${workspace.status === 'archived' ? 'border-slate-800 opacity-70' : 'border-slate-800'}`}>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-sm font-medium text-slate-100">{workspace.name}</h3>
              <span className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                {MODE_LABEL[workspace.mode] ?? workspace.mode}
              </span>
              {workspace.status === 'archived' && (
                <span className="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">已归档</span>
              )}
              <span className="text-xs text-slate-500">{workspace.root_path}</span>
              <div className="ml-auto flex gap-2 text-xs">
                <button className="rounded border border-slate-700 px-2 py-1 text-slate-300"
                        onClick={() => {
                          const next = window.prompt('新的工作区名称', workspace.name)
                          if (next && next.trim() && next !== workspace.name) {
                            rename.mutate({ id: workspace.id, name: next.trim() })
                          }
                        }}>改名</button>
                {workspace.status === 'active' && (
                  <button className="rounded border border-amber-800 px-2 py-1 text-amber-300"
                          onClick={() => archive.mutate(workspace.id)}>归档</button>
                )}
              </div>
            </div>

            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div>
                <div className="text-xs text-slate-500">已授权员工</div>
                <ul className="mt-2 space-y-1 text-sm">
                  {workspace.grants.length === 0 && (
                    <li className="text-xs text-slate-500">尚未授权任何员工（无授权 = 禁止访问）</li>
                  )}
                  {workspace.grants.map((item) => (
                    <li key={item.employee_id}
                        className="flex items-center justify-between rounded border border-slate-800 px-2 py-1">
                      <span className="text-slate-300">
                        {item.employee_name}
                        <span className={`ml-2 rounded px-1.5 py-0.5 text-xs ${item.access === 'write' ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-800 text-slate-300'}`}>
                          {item.access === 'write' ? '读写' : '只读'}
                        </span>
                      </span>
                      <button className="text-xs text-red-400 hover:underline"
                              data-testid={`ws-revoke-${workspace.id}-${item.employee_id}`}
                              onClick={() => revoke.mutate({ workspaceId: workspace.id, employeeId: item.employee_id })}>
                        撤销
                      </button>
                    </li>
                  ))}
                </ul>
              </div>

              {workspace.status === 'active' && (
                <div>
                  <div className="text-xs text-slate-500">新增/更新授权</div>
                  <div className="mt-2 flex gap-2">
                    <select className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                            data-testid={`ws-grant-employee-${workspace.id}`}
                            value={grantTarget[workspace.id] ?? ''}
                            onChange={(event) => setGrantTarget({ ...grantTarget, [workspace.id]: event.target.value })}>
                      <option value="">选择员工…</option>
                      {employees.data?.items.map((employee) => (
                        <option key={employee.id} value={employee.id}>{employee.name}</option>
                      ))}
                    </select>
                    <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                            data-testid={`ws-grant-access-${workspace.id}`}
                            value={grantAccess[workspace.id] ?? 'read'}
                            onChange={(event) => setGrantAccess({ ...grantAccess, [workspace.id]: event.target.value })}>
                      <option value="read">只读</option>
                      <option value="write">读写</option>
                    </select>
                    <button className="rounded bg-sky-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                            data-testid={`ws-grant-submit-${workspace.id}`}
                            disabled={!grantTarget[workspace.id] || grant.isPending}
                            onClick={() => grant.mutate({ workspaceId: workspace.id })}>
                      授权
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
