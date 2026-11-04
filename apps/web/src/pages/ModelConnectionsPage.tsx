import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { peopleApi } from '../api/people'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

export default function ModelConnectionsPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const providers = useQuery({ queryKey: ['providers'], queryFn: peopleApi.providers })
  const connections = useQuery({
    queryKey: ['connections', activeCompanyId],
    queryFn: () => peopleApi.listConnections(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  const [name, setName] = useState('')
  const [provider, setProvider] = useState('deepseek')
  const [model, setModel] = useState('')
  const [keyRef, setKeyRef] = useState('env:DEEPSEEK_API_KEY')
  const [message, setMessage] = useState<string | null>(null)

  const providerInfo = providers.data?.providers.find((p) => p.id === provider)

  const create = useMutation({
    mutationFn: () =>
      peopleApi.createConnection(activeCompanyId as string, {
        name: name.trim(),
        provider,
        model: model || providerInfo?.models[0]?.id || '',
        api_key_ref: keyRef.trim(),
      }),
    onSuccess: () => {
      setName('')
      setMessage('连接已创建')
      queryClient.invalidateQueries({ queryKey: ['connections'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const test = useMutation({
    mutationFn: (id: string) => peopleApi.testConnection(id),
    onSuccess: (result) => setMessage(`连接正常，延迟 ${result.latency_ms}ms`),
    onError: (error) => setMessage(errorText(error)),
  })

  const remove = useMutation({
    mutationFn: (id: string) => peopleApi.deleteConnection(id),
    onSuccess: () => {
      setMessage('连接已删除')
      queryClient.invalidateQueries({ queryKey: ['connections'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先在组织设置中创建公司。</p>

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-100">模型连接</h2>
        <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                value={activeCompanyId} onChange={(e) => setCompanyId(e.target.value)}>
          {companies.data?.items.map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
      </div>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">新增连接</h3>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                 placeholder="连接名称" value={name} onChange={(e) => setName(e.target.value)} />
          <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={provider} onChange={(e) => { setProvider(e.target.value); setModel('') }}>
            {providers.data?.providers.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
          <select className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                  value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">默认模型</option>
            {providerInfo?.models.map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
          <input className="w-64 rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                 placeholder="env:DEEPSEEK_API_KEY" value={keyRef} onChange={(e) => setKeyRef(e.target.value)} />
          <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                  disabled={!name.trim() || !keyRef.trim() || create.isPending}
                  onClick={() => create.mutate()}>
            创建
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          只填写凭据引用（env:变量名），不要粘贴密钥本体；密钥不会入库、不会回显。
        </p>
      </section>

      <section className="space-y-2">
        {connections.data?.map((conn) => (
          <div key={conn.id} className="flex flex-wrap items-center justify-between gap-3 rounded border border-slate-800 px-4 py-3">
            <div>
              <div className="flex items-center gap-2 text-sm text-slate-100">
                <span className={`h-2 w-2 rounded-full ${
                  conn.last_health_status === 'ok' ? 'bg-emerald-400'
                    : conn.last_health_status === 'fail' ? 'bg-red-400' : 'bg-slate-600'
                }`} />
                {conn.name}
                <span className="text-xs text-slate-500">{conn.provider} · {conn.model}</span>
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {conn.api_key_ref} · {conn.has_credential ? '凭据可用' : '凭据缺失'}
                {conn.last_health_latency_ms != null && ` · 最近延迟 ${conn.last_health_latency_ms}ms`}
              </div>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <button className="text-sky-400 hover:underline" onClick={() => test.mutate(conn.id)}>测试连接</button>
              <button className="text-red-400 hover:underline" onClick={() => remove.mutate(conn.id)}>删除</button>
            </div>
          </div>
        ))}
        {connections.data?.length === 0 && <p className="text-sm text-slate-500">还没有模型连接。</p>}
      </section>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}
    </div>
  )
}
