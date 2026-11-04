import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { peopleApi } from '../api/people'

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

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}
    </div>
  )
}
