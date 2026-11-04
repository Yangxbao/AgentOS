import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { peopleApi } from '../api/people'
import { promptsApi } from '../api/prompts'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

export default function EmployeeDetailPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const employee = useQuery({ queryKey: ['employee', id], queryFn: () => peopleApi.getEmployee(id) })
  const connections = useQuery({
    queryKey: ['connections', employee.data?.company_id],
    queryFn: () => peopleApi.listConnections(employee.data!.company_id),
    enabled: Boolean(employee.data?.company_id),
  })

  const [primary, setPrimary] = useState('')
  const [fallback, setFallback] = useState('')
  const [reason, setReason] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const prompts = useQuery({ queryKey: ['prompts', id], queryFn: () => promptsApi.list(id) })
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

  if (employee.isLoading) return <p className="p-6 text-slate-400">加载中…</p>
  if (employee.isError || !employee.data) return <p className="p-6 text-red-400">员工不存在</p>
  const data = employee.data

  return (
    <div className="space-y-6 p-6">
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
          <h3 className="text-sm font-medium text-slate-200">档案</h3>
          <dl className="mt-3 space-y-1 text-sm text-slate-400">
            <div>岗位：{data.positions.map((p) => `${p.name}${p.is_primary ? '（主）' : ''}`).join('、') || '—'}</div>
            <div>简介：{data.bio || '—'}</div>
            <div>性格：{data.personality || '—'}</div>
            <div>汇报对象：{data.reports_to || '无'}</div>
            <div>工具授权：{data.tools_allowed.join('、') || '无'}</div>
          </dl>
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
