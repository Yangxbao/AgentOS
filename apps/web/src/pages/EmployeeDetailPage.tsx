import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'
import { promptsApi } from '../api/prompts'
import { governanceApi } from '../api/governance'
import { toolsApi, type ToolSpec } from '../api/tools'
import { memoryApi, type MemoryItem } from '../api/memory'
import { Toast, useToast } from '../components/Toast'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

const CATEGORY_LABEL: Record<string, string> = {
  file_read: '文件读取', file_write: '文件写入', network: '网络', shell: 'Shell', memory: '记忆',
}
const RISK_LABEL: Record<string, string> = {
  low: '低', medium: '中', high: '高', critical: '严重',
}
const REASON_LABEL: Record<string, string> = {
  available: '可执行',
  shell_disabled: 'Shell 永久禁用',
  tool_disabled: '公司策略未开启',
  category_disabled: '类别未开启',
  tool_not_granted: '白名单/策略未包含',
  workspace_not_granted: '未授权工作区',
  network_not_configured: '未配置网络白名单',
}

export default function EmployeeDetailPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const { toast, showToast } = useToast()
  const employee = useQuery({ queryKey: ['employee', id], queryFn: () => peopleApi.getEmployee(id) })
  const companyId = employee.data?.company_id
  const connections = useQuery({
    queryKey: ['connections', companyId],
    queryFn: () => peopleApi.listConnections(companyId!),
    enabled: Boolean(companyId),
  })
  const departments = useQuery({
    queryKey: ['departments', companyId],
    queryFn: () => orgApi.listDepartments(companyId!),
    enabled: Boolean(companyId),
  })
  const positions = useQuery({
    queryKey: ['positions', companyId],
    queryFn: () => orgApi.listPositions(companyId!),
    enabled: Boolean(companyId),
  })

  const [primary, setPrimary] = useState('')
  const [fallback, setFallback] = useState('')
  const [reason, setReason] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const prompts = useQuery({ queryKey: ['prompts', id], queryFn: () => promptsApi.list(id) })
  const permissions = useQuery({
    queryKey: ['permissions', id],
    queryFn: () => governanceApi.effectivePermissions(id),
  })
  const capabilities = useQuery({
    queryKey: ['capabilities', id],
    queryFn: () => governanceApi.capabilities(id),
  })
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState('')
  const [diff, setDiff] = useState('')
  const savePrompt = useMutation({
    mutationFn: () => promptsApi.create(id, draft, note),
    onSuccess: () => {
      setDraft('')
      setMessage('已保存为新版本（不可变）')
      queryClient.invalidateQueries({ queryKey: ['prompts', id] })
    },
    onError: (error) => setMessage(errorText(error)),
  })
  const activatePrompt = useMutation({
    mutationFn: (revisionId: string) => promptsApi.activate(revisionId),
    onSuccess: () => {
      setMessage('已切换激活版本')
      queryClient.invalidateQueries({ queryKey: ['prompts', id] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const bind = useMutation({
    mutationFn: () =>
      peopleApi.bindModels(id, {
        primary_model_id: primary || employee.data?.primary_model_id || '',
        fallback_model_id: fallback || null,
        reason,
      }),
    onSuccess: (result) => {
      setWarnings(result.warnings ?? [])
      setMessage('模型绑定已更新，历史记录保留')
      queryClient.invalidateQueries({ queryKey: ['employee', id] })
      queryClient.invalidateQueries({ queryKey: ['employees'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  // ---------- A. 基本信息编辑 ----------
  const [profile, setProfile] = useState<Record<string, string> | null>(null)
  const [profilePositions, setProfilePositions] = useState<string[] | null>(null)
  const [primaryPosition, setPrimaryPosition] = useState<string | null>(null)
  const profileDraft = profile ?? {
    name: employee.data?.name ?? '',
    title: employee.data?.title ?? '',
    bio: employee.data?.bio ?? '',
    personality: employee.data?.personality ?? '',
    department_id: employee.data?.department_id ?? '',
  }
  const saveProfile = useMutation({
    mutationFn: () =>
      peopleApi.patchEmployee(id, {
        name: profileDraft.name.trim(),
        title: profileDraft.title.trim(),
        bio: profileDraft.bio,
        personality: profileDraft.personality,
        department_id: profileDraft.department_id || null,
        ...(profilePositions !== null
          ? { positions: profilePositions.map((positionId) => ({
              position_id: positionId,
              is_primary: positionId === (primaryPosition ?? data?.positions.find((p) => p.is_primary)?.position_id),
            })) }
          : {}),
      }),
    onSuccess: (updated) => {
      setProfile(null)
      setProfilePositions(null)
      setPrimaryPosition(null)
      showToast('success', `员工「${updated.name}」基本信息已保存`)
      queryClient.invalidateQueries({ queryKey: ['employee', id] })
      queryClient.invalidateQueries({ queryKey: ['employees'] })
      queryClient.invalidateQueries({ queryKey: ['org-tree'] })
    },
    onError: (error) => showToast('error', errorText(error)),
  })

  // ---------- B. 工具授权管理 ----------
  const catalogue = useQuery({ queryKey: ['tool-catalogue'], queryFn: () => toolsApi.catalogue() })
  const toolPolicy = useQuery({
    queryKey: ['tool-policy', companyId],
    queryFn: () => toolsApi.getPolicy(companyId!),
    enabled: Boolean(companyId),
  })
  const toolPermissions = useQuery({
    queryKey: ['tool-permissions', id],
    queryFn: () => toolsApi.employeePermissions(id),
  })
  // null = 未编辑（展示后端已保存值）；编辑中的草稿与后端分离，保存失败不丢失
  const [toolDraft, setToolDraft] = useState<string[] | null>(null)
  const savedTools = employee.data?.tools_allowed ?? []
  const currentTools = toolDraft ?? savedTools

  const toggleTool = (tool: ToolSpec) => {
    if (toolDraft === null) setToolDraft([...savedTools])
    setToolDraft((prev) => {
      const base = prev ?? [...savedTools]
      return base.includes(tool.name)
        ? base.filter((t) => t !== tool.name)
        : [...base, tool.name]
    })
  }
  const toolDiff = (() => {
    if (toolDraft === null) return null
    const added = toolDraft.filter((t) => !savedTools.includes(t))
    const removed = savedTools.filter((t) => !toolDraft.includes(t))
    return { added, removed }
  })()
  const policyAllows = (tool: ToolSpec): boolean => {
    const policy = toolPolicy.data?.policy
    if (!policy) return false
    return Boolean(policy.categories?.[tool.category]) && policy.allowed_tools.includes(tool.name)
  }
  const permissionOf = (tool: ToolSpec) =>
    toolPermissions.data?.tools.find((item) => item.tool === tool.name)

  const saveTools = useMutation({
    mutationFn: () => peopleApi.patchEmployee(id, { tools_allowed: toolDraft ?? [] }),
    onSuccess: (updated) => {
      setToolDraft(null)
      showToast('success', `工具白名单已保存：${updated.tools_allowed.length} 项`)
      queryClient.invalidateQueries({ queryKey: ['employee', id] })
      queryClient.invalidateQueries({ queryKey: ['employees'] })
      queryClient.invalidateQueries({ queryKey: ['tool-permissions', id] })
    },
    onError: (error) => showToast('error', errorText(error)), // 失败保留 toolDraft 便于重新提交
  })

  // ---------- C. 工作区授权管理 ----------
  const workspaces = useQuery({
    queryKey: ['workspaces', companyId],
    queryFn: () => toolsApi.listWorkspaces(companyId!),
    enabled: Boolean(companyId),
  })
  const [grantAccess, setGrantAccess] = useState<Record<string, 'read' | 'write'>>({})
  const grant = useMutation({
    mutationFn: (workspaceId: string) =>
      toolsApi.grant(workspaceId, id, grantAccess[workspaceId] ?? 'read'),
    onSuccess: (row) => {
      showToast('success', `已授权工作区（${row.access === 'write' ? '读写' : '只读'}）`)
      queryClient.invalidateQueries({ queryKey: ['workspaces', companyId] })
      queryClient.invalidateQueries({ queryKey: ['tool-permissions', id] })
    },
    onError: (error) => showToast('error', errorText(error)),
  })
  const revoke = useMutation({
    mutationFn: (workspaceId: string) => toolsApi.revoke(workspaceId, id),
    onSuccess: () => {
      showToast('success', '已撤销该工作区授权')
      queryClient.invalidateQueries({ queryKey: ['workspaces', companyId] })
      queryClient.invalidateQueries({ queryKey: ['tool-permissions', id] })
    },
    onError: (error) => showToast('error', errorText(error)),
  })

  // ---------- D. 员工记忆（该员工的私有记忆 + 快速写入） ----------
  const memories = useQuery({
    queryKey: ['employee-memories', companyId, id],
    queryFn: () => memoryApi.list(companyId!, { scope: 'employee', employee_id: id as string }),
    enabled: Boolean(companyId),
  })
  const [memoryTitle, setMemoryTitle] = useState('')
  const [memoryContent, setMemoryContent] = useState('')
  const createMemory = useMutation({
    mutationFn: () =>
      memoryApi.create(companyId!, {
        scope: 'employee', employee_id: id,
        title: memoryTitle.trim(), content: memoryContent.trim(), kind: 'note',
      }),
    onSuccess: () => {
      setMemoryTitle('')
      setMemoryContent('')
      showToast('success', '已写入员工私有记忆（其他员工检索不到）')
      queryClient.invalidateQueries({ queryKey: ['employee-memories', companyId, id] })
    },
    onError: (error) => showToast('error', errorText(error)),
  })
  const deleteMemory = useMutation({
    mutationFn: (memoryId: string) => memoryApi.remove(memoryId),
    onSuccess: () => {
      showToast('success', '已删除记忆')
      queryClient.invalidateQueries({ queryKey: ['employee-memories', companyId, id] })
    },
    onError: (error) => showToast('error', errorText(error)),
  })

  if (employee.isLoading) return <p className="p-6 text-slate-400">加载中…</p>
  if (employee.isError || !employee.data) return <p className="p-6 text-red-400">员工不存在</p>
  const data = employee.data

  return (
    <div className="space-y-6 p-6">
      <Toast toast={toast} />
      <div className="flex items-center gap-3">
        <h2 className="text-xl font-semibold text-slate-100">
          {data.avatar || '🤖'} {data.name}
        </h2>
        <span className="text-sm text-slate-400">{data.title}</span>
        <span className={`rounded px-2 py-0.5 text-xs ${
          data.status === 'active' ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-800 text-slate-400'
        }`}>
          {data.status === 'active' ? '在职' : '停用'}
        </span>
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded border border-slate-800 p-4">
          <h3 className="text-sm font-medium text-slate-200">基本信息（可编辑）</h3>
          <div className="mt-3 space-y-2 text-sm">
            <input className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
                   placeholder="姓名" value={profileDraft.name}
                   onChange={(e) => setProfile({ ...profileDraft, name: e.target.value })} />
            <input className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
                   placeholder="岗位头衔" value={profileDraft.title}
                   onChange={(e) => setProfile({ ...profileDraft, title: e.target.value })} />
            <textarea className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
                      placeholder="简介" value={profileDraft.bio}
                      onChange={(e) => setProfile({ ...profileDraft, bio: e.target.value })} />
            <input className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
                   placeholder="工作风格 / 性格" value={profileDraft.personality}
                   onChange={(e) => setProfile({ ...profileDraft, personality: e.target.value })} />
            <select className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
                    value={profileDraft.department_id}
                    onChange={(e) => setProfile({ ...profileDraft, department_id: e.target.value })}>
              <option value="">未分配部门</option>
              {departments.data?.items.map((dept) => (
                <option key={dept.id} value={dept.id}>{dept.name}</option>
              ))}
            </select>
            <div className="rounded border border-slate-700 bg-slate-900 p-2">
              <div className="text-xs text-slate-500">岗位（可多选；保存后全量替换）</div>
              <div className="mt-1 space-y-1">
                {(positions.data?.items ?? []).map((position) => {
                  const current = profilePositions ?? data?.positions.map((p) => p.position_id) ?? []
                  const checked = current.includes(position.id)
                  const primaryId = primaryPosition ?? data?.positions.find((p) => p.is_primary)?.position_id
                  return (
                    <label key={position.id} className="flex items-center gap-2 text-xs text-slate-300">
                      <input type="checkbox" checked={checked}
                             onChange={() => {
                               const next = checked ? current.filter((x) => x !== position.id) : [...current, position.id]
                               setProfilePositions(next)
                               if (!checked && primaryId === null) setPrimaryPosition(position.id)
                             }} />
                      {position.name}
                      {checked && (
                        <label className="ml-auto flex items-center gap-1 text-slate-500">
                          <input type="radio" name="primary-position"
                                 checked={primaryId === position.id}
                                 onChange={() => setPrimaryPosition(position.id)} />
                          主岗
                        </label>
                      )}
                    </label>
                  )
                })}
                {(positions.data?.items ?? []).length === 0 && (
                  <span className="text-slate-500">本公司还没有岗位，请到「组织设置」创建</span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="rounded bg-sky-600 px-4 py-1.5 text-sm text-white disabled:opacity-50"
                      disabled={saveProfile.isPending || !profileDraft.name.trim()}
                      onClick={() => saveProfile.mutate()}>
                保存基本信息
              </button>
              {profile !== null && (
                <button className="text-xs text-slate-400 hover:underline"
                        onClick={() => setProfile(null)}>
                  放弃修改
                </button>
              )}
            </div>
            <p className="text-xs text-slate-600">岗位清单来自组织设置；新岗位请先到「组织设置」创建。</p>
          </div>
        </div>

        <div className="rounded border border-slate-800 p-4">
          <h3 className="text-sm font-medium text-slate-200">模型绑定（与身份解耦）</h3>
          <p className="mt-2 text-xs text-slate-500">
            当前主模型：{data.model.primary?.name}（{data.model.primary?.model}）
            {data.model.health === false && <span className="ml-2 text-red-400">不可用</span>}
          </p>
          <div className="mt-3 space-y-2">
            <select className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                    value={primary || data.primary_model_id} onChange={(e) => setPrimary(e.target.value)}>
              {connections.data?.map((conn) => (
                <option key={conn.id} value={conn.id}>{conn.name}（{conn.model}）</option>
              ))}
            </select>
            <select className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                    value={fallback || data.fallback_model_id || ''} onChange={(e) => setFallback(e.target.value)}>
              <option value="">无备用模型</option>
              {connections.data?.map((conn) => (
                <option key={conn.id} value={conn.id}>{conn.name}</option>
              ))}
            </select>
            <input className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                   placeholder="切换原因（写入审计）" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                    disabled={bind.isPending} onClick={() => bind.mutate()}>
              保存模型绑定
            </button>
          </div>
          {warnings.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-400">
              {warnings.map((warning) => <li key={warning}>{warning}</li>)}
            </ul>
          )}
        </div>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">工具授权管理</h3>
        <p className="mt-1 text-xs text-slate-500">
          勾选 = 员工工具白名单（五层权限之一）。「实际可执行」来自后端五层诊断，
          还需全局开关、公司工具策略、工作区授权配合——勾选不等于一定可执行。
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <button className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
                  onClick={() => setToolDraft([
                    ...(catalogue.data?.items ?? [])
                      .filter((tool) => tool.enabled && tool.category !== 'shell')
                      .map((tool) => tool.name),
                  ])}>
            全选可配置工具
          </button>
          <button className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:bg-slate-800"
                  onClick={() => setToolDraft([])}>
            全部取消
          </button>
          <button className="rounded bg-sky-600 px-3 py-1 text-white disabled:opacity-50"
                  disabled={saveTools.isPending || toolDiff === null || (toolDiff && toolDiff.added.length === 0 && toolDiff.removed.length === 0)}
                  onClick={() => saveTools.mutate()}>
            保存工具白名单
          </button>
          {toolDiff && (toolDiff.added.length > 0 || toolDiff.removed.length > 0) && (
            <span className="text-amber-400">
              本次变更：新增 {toolDiff.added.join('、') || '无'}；移除 {toolDiff.removed.join('、') || '无'}
            </span>
          )}
        </div>
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1">授权</th><th>工具</th><th>分类</th><th>风险</th>
              <th>说明</th><th>全局策略允许</th><th>实际可执行</th>
            </tr>
          </thead>
          <tbody>
            {(catalogue.data?.items ?? []).map((tool) => {
              const perm = permissionOf(tool)
              const policyOk = policyAllows(tool)
              const checked = currentTools.includes(tool.name)
              const disabled = !tool.enabled || tool.category === 'shell'
              return (
                <tr key={tool.name} className="border-t border-slate-800 align-top">
                  <td className="py-1.5">
                    <input type="checkbox" checked={checked} disabled={disabled}
                           onChange={() => toggleTool(tool)} />
                  </td>
                  <td className="font-mono text-slate-200">{tool.name}</td>
                  <td className="text-slate-400">{CATEGORY_LABEL[tool.category] ?? tool.category}</td>
                  <td className="text-slate-400">{RISK_LABEL[tool.risk] ?? tool.risk}</td>
                  <td className="max-w-xs text-slate-500">{tool.description}</td>
                  <td className={policyOk ? 'text-emerald-400' : 'text-slate-500'}>
                    {policyOk ? '允许' : '未允许'}
                  </td>
                  <td className={perm?.available ? 'text-emerald-400' : 'text-slate-500'}>
                    {perm ? (REASON_LABEL[perm.reason] ?? perm.reason) : '…'}
                    {!disabled && checked && !perm?.available && (
                      <span className="ml-1 text-amber-500">（勾选了但还不可执行，见上一列与工作区授权）</span>
                    )}
                  </td>
                </tr>
              )
            })}
            {(catalogue.data?.items ?? []).length === 0 && (
              <tr><td colSpan={7} className="py-2 text-slate-500">工具目录加载中…</td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">工作区授权管理</h3>
        <p className="mt-1 text-xs text-slate-500">
          文件工具只能在已授权的工作区内操作；根目录与路径安全边界不受本页影响（后端强制）。
        </p>
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1">工作区</th><th>根目录</th><th>状态</th><th>当前授权</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {(workspaces.data ?? []).map((workspace) => {
              const existing = workspace.grants.find((g) => g.employee_id === id)
              return (
                <tr key={workspace.id} className="border-t border-slate-800">
                  <td className="py-1.5 text-slate-200">
                    {workspace.name}
                    {workspace.mode === 'read_only' && (
                      <span className="ml-2 rounded bg-slate-800 px-1.5 py-0.5 text-slate-400">只读工作区</span>
                    )}
                  </td>
                  <td className="max-w-xs truncate font-mono text-slate-500">{workspace.root_path}</td>
                  <td className={workspace.status === 'active' ? 'text-emerald-400' : 'text-slate-500'}>
                    {workspace.status === 'active' ? '启用' : '已归档'}
                  </td>
                  <td className={existing ? 'text-emerald-400' : 'text-slate-500'}>
                    {existing ? (existing.access === 'write' ? '读写' : '只读') : '未授权'}
                  </td>
                  <td>
                    {existing ? (
                      <button className="text-rose-400 hover:underline"
                              disabled={revoke.isPending}
                              onClick={() => revoke.mutate(workspace.id)}>
                        撤销授权
                      </button>
                    ) : (
                      <span className="flex items-center gap-2">
                        <select className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-slate-200"
                                value={grantAccess[workspace.id] ?? 'read'}
                                onChange={(e) => setGrantAccess({
                                  ...grantAccess,
                                  [workspace.id]: e.target.value as 'read' | 'write',
                                })}>
                          <option value="read">只读</option>
                          <option value="write">读写</option>
                        </select>
                        <button className="text-sky-400 hover:underline disabled:opacity-50"
                                disabled={grant.isPending || workspace.status !== 'active'}
                                onClick={() => grant.mutate(workspace.id)}>
                          授权
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              )
            })}
            {(workspaces.data ?? []).length === 0 && (
              <tr><td colSpan={5} className="py-2 text-slate-500">
                本公司还没有工作区，请到「工作区管理」创建。
              </td></tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">员工记忆（employee 作用域，仅本人可检索）</h3>
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input className="w-48 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
                   placeholder="标题" value={memoryTitle}
                   onChange={(event) => setMemoryTitle(event.target.value)} />
            <input className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-100"
                   placeholder="内容（密钥会自动脱敏）" value={memoryContent}
                   onChange={(event) => setMemoryContent(event.target.value)} />
            <button className="rounded bg-sky-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                    disabled={!memoryContent.trim() || createMemory.isPending}
                    onClick={() => createMemory.mutate()}>
              写入
            </button>
          </div>
          <ul className="space-y-1 text-xs">
            {(memories.data?.items ?? []).map((item: MemoryItem) => (
              <li key={item.id} className="flex items-center justify-between rounded border border-slate-800 px-2 py-1">
                <span className="text-slate-300">
                  <span className="font-medium">{item.title || '（无标题）'}</span>
                  <span className="ml-2 text-slate-500">{item.content.slice(0, 80)}</span>
                </span>
                <button className="text-rose-400 hover:underline"
                        onClick={() => deleteMemory.mutate(item.id)}>
                  删除
                </button>
              </li>
            ))}
            {(memories.data?.items ?? []).length === 0 && (
              <li className="text-slate-500">该员工还没有私有记忆</li>
            )}
          </ul>
          <p className="text-xs text-slate-600">
            Agent 也可通过 memory.remember 工具写入自己的私有记忆；提升为项目/公司共享请在「记忆中心」操作。
          </p>
        </div>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">有效权限（三层交集，只许收窄）</h3>
        <div className="mt-3 grid gap-2 text-xs text-slate-400 md:grid-cols-2">
          {permissions.data && Object.entries(permissions.data.permissions).map(([key, value]) => (
            <div key={key} className="flex items-start justify-between gap-2 rounded bg-slate-900 px-2 py-1">
              <span className="text-slate-500">{key}</span>
              <span className="text-right text-slate-300">
                {JSON.stringify(value)}
                <span className="ml-1 text-slate-600">
                  ({permissions.data.sources[key]?.map((item) => item.layer).join(' ∩ ')})
                </span>
              </span>
            </div>
          ))}
        </div>
        {capabilities.data && (
          <p className="mt-2 text-xs text-slate-500">
            能力：结构化输出 {String(capabilities.data.effective && (capabilities.data.effective as Record<string, unknown>).structured_output)} ·
            文件操作 {String(capabilities.data.effective && (capabilities.data.effective as Record<string, unknown>).file_ops)} ·
            模型可用 {String(capabilities.data.model_available)}
          </p>
        )}
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">提示词版本（外置文件，不可变）</h3>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <div>
            <ul className="space-y-1 text-sm">
              {prompts.data?.map((revision) => (
                <li key={revision.id} className="flex items-center justify-between rounded border border-slate-800 px-2 py-1">
                  <span className="text-slate-300">
                    v{revision.version}
                    {revision.is_active && <span className="ml-2 rounded bg-emerald-900 px-2 py-0.5 text-xs text-emerald-300">激活</span>}
                    <span className="ml-2 text-xs text-slate-500">{revision.note}</span>
                  </span>
                  <span className="flex gap-2 text-xs">
                    <button className="text-slate-400 hover:underline"
                            onClick={async () => setDiff((await promptsApi.diff(revision.id)).diff)}>对比</button>
                    {!revision.is_active && (
                      <button className="text-sky-400 hover:underline" onClick={() => activatePrompt.mutate(revision.id)}>
                        激活
                      </button>
                    )}
                  </span>
                </li>
              ))}
              {prompts.data?.length === 0 && <li className="text-sm text-slate-500">还没有提示词</li>}
            </ul>
            {diff && (
              <pre className="mt-3 max-h-48 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-400">{diff}</pre>
            )}
          </div>
          <div>
            <textarea className="h-40 w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-slate-100"
                      placeholder="输入提示词内容，保存后会生成新版本…"
                      value={draft} onChange={(event) => setDraft(event.target.value)} />
            <input className="mt-2 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                   placeholder="版本说明（可选）" value={note} onChange={(event) => setNote(event.target.value)} />
            <button className="mt-2 rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                    disabled={!draft.trim() || savePrompt.isPending} onClick={() => savePrompt.mutate()}>
              保存为新版本
            </button>
          </div>
        </div>
      </section>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}
    </div>
  )
}
