import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'
import { toolsApi, type ToolPolicy } from '../api/tools'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

const RISK_STYLE: Record<string, string> = {
  low: 'bg-emerald-900 text-emerald-300',
  medium: 'bg-amber-900 text-amber-300',
  high: 'bg-orange-900 text-orange-300',
  critical: 'bg-red-900 text-red-300',
}

const CATEGORY_LABEL: Record<string, string> = {
  file_read: '文件读取',
  file_write: '文件写入',
  network: '网络访问',
  shell: 'Shell（永久禁用）',
}

const RISK_OPTIONS = ['low', 'medium', 'high', 'critical']

export default function ToolPolicyPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const policyQuery = useQuery({
    queryKey: ['toolPolicy', activeCompanyId],
    queryFn: () => toolsApi.getPolicy(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const catalogue = useQuery({ queryKey: ['toolCatalogue'], queryFn: toolsApi.catalogue })

  const [draft, setDraft] = useState<ToolPolicy | null>(null)
  const [domainsText, setDomainsText] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (policyQuery.data) {
      setDraft(policyQuery.data.policy)
      setDomainsText(policyQuery.data.policy.network_domains.join('\n'))
    }
  }, [policyQuery.data])

  const save = useMutation({
    mutationFn: () => {
      if (!draft || !activeCompanyId) throw new ApiError(0, null, '尚未加载策略')
      return toolsApi.updatePolicy(activeCompanyId, {
        ...draft,
        network_domains: domainsText.split('\n').map((line) => line.trim()).filter(Boolean),
      })
    },
    onSuccess: (result) => {
      setDraft(result.policy)
      setMessage('策略已保存')
      queryClient.invalidateQueries({ queryKey: ['toolPolicy'] })
      queryClient.invalidateQueries({ queryKey: ['toolCatalogue'] })
    },
    onError: (error) => setMessage(errorText(error)),
  })

  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先在组织设置中创建公司。</p>
  if (policyQuery.isLoading || !draft) return <p className="p-6 text-slate-400">加载中…</p>
  if (policyQuery.isError) return <p className="p-6 text-red-400">{errorText(policyQuery.error)}</p>

  const globalOn = policyQuery.data?.global_enabled ?? false
  const specs = catalogue.data?.items ?? []

  const toggleTool = (name: string) => {
    const next = draft.allowed_tools.includes(name)
      ? draft.allowed_tools.filter((item) => item !== name)
      : [...draft.allowed_tools, name]
    setDraft({ ...draft, allowed_tools: next })
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-100">工具策略</h2>
        <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                value={activeCompanyId} onChange={(event) => setCompanyId(event.target.value)}>
          {companies.data?.items.map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
      </div>

      <div className={`rounded border px-3 py-2 text-sm ${globalOn ? 'border-emerald-800 bg-emerald-950/30 text-emerald-200' : 'border-amber-800 bg-amber-950/40 text-amber-200'}`}>
        全局工具执行开关：{globalOn ? '已开启' : '已关闭'}
        <span className="ml-3 text-xs opacity-80">
          由环境变量 AGENTOS_TOOL_EXECUTION 控制（默认 off）；关闭时所有工具调用被拒绝，但不影响普通任务。
        </span>
      </div>

      <div className="rounded border border-red-900 bg-red-950/30 px-3 py-2 text-sm text-red-200">
        Shell 执行在 M3 永久禁用：没有任何命令执行代码路径，公司策略也无法开启。
      </div>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">公司级开关</h3>
        <div className="mt-3 grid gap-4 md:grid-cols-2">
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={draft.enabled}
                   onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />
            允许本公司的 Agent 使用工具
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={draft.allow_http_write}
                   onChange={(event) => setDraft({ ...draft, allow_http_write: event.target.checked })} />
            允许 HTTP 写方法（POST/PUT/PATCH/DELETE，仍需逐次审批）
          </label>
        </div>

        <div className="mt-4 grid gap-2 md:grid-cols-4">
          {Object.entries(CATEGORY_LABEL).map(([category, label]) => {
            const disabled = category === 'shell'
            const checked = category === 'shell' ? false : Boolean(draft.categories[category])
            return (
              <label key={category}
                     className={`flex items-center gap-2 rounded border border-slate-800 px-2 py-1 text-sm ${disabled ? 'opacity-50' : ''}`}>
                <input type="checkbox" checked={checked} disabled={disabled}
                       onChange={(event) => setDraft({
                         ...draft,
                         categories: { ...draft.categories, [category]: event.target.checked },
                       })} />
                {label}
              </label>
            )
          })}
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="text-sm text-slate-300">
            单步工具调用上限
            <input type="number" min={1} max={50}
                   className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                   value={draft.max_tool_calls_per_step}
                   onChange={(event) => setDraft({ ...draft, max_tool_calls_per_step: Number(event.target.value) })} />
          </label>
          <label className="text-sm text-slate-300">
            自动执行风险上限
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={draft.auto_execute_max_risk}
                    onChange={(event) => setDraft({ ...draft, auto_execute_max_risk: event.target.value })}>
              {RISK_OPTIONS.map((risk) => <option key={risk} value={risk}>{risk}</option>)}
            </select>
          </label>
          <label className="text-sm text-slate-300">
            绝对风险上限（超过即拒绝）
            <select className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                    value={draft.max_risk_level}
                    onChange={(event) => setDraft({ ...draft, max_risk_level: event.target.value })}>
              {RISK_OPTIONS.map((risk) => <option key={risk} value={risk}>{risk}</option>)}
            </select>
          </label>
        </div>

        <label className="mt-4 block text-sm text-slate-300">
          网络域名白名单（每行一个 host 或 host:port，支持 *.example.com）
          <textarea className="mt-1 h-24 w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs"
                    value={domainsText} onChange={(event) => setDomainsText(event.target.value)}
                    placeholder={'api.github.com\n*.githubusercontent.com'} />
        </label>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">工具白名单</h3>
        <p className="mt-1 text-xs text-slate-500">
          只有被勾选、且员工 tools_allowed 也包含的工具，才可能被模型看到并执行。
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {specs.map((spec) => {
            const disabled = !spec.enabled
            return (
              <label key={spec.name}
                     className={`flex items-start gap-2 rounded border border-slate-800 p-2 text-sm ${disabled ? 'opacity-60' : ''}`}>
                <input type="checkbox" className="mt-1"
                       checked={!disabled && draft.allowed_tools.includes(spec.name)}
                       disabled={disabled}
                       onChange={() => toggleTool(spec.name)} />
                <span>
                  <span className="font-mono text-xs text-slate-200">{spec.name}</span>
                  <span className={`ml-2 rounded px-1.5 py-0.5 text-xs ${RISK_STYLE[spec.risk]}`}>{spec.risk}</span>
                  {spec.requires_approval && (
                    <span className="ml-1 rounded bg-purple-900 px-1.5 py-0.5 text-xs text-purple-300">需审批</span>
                  )}
                  <span className="block text-xs text-slate-500">{spec.description}</span>
                </span>
              </label>
            )
          })}
        </div>
      </section>

      <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
              data-testid="policy-save"
              disabled={save.isPending} onClick={() => save.mutate()}>
        保存策略
      </button>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">工具目录（只读）</h3>
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th className="py-1">工具</th>
              <th>类别</th>
              <th>风险</th>
              <th>副作用</th>
              <th>超时</th>
              <th>最大输出</th>
              <th>默认</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {specs.map((spec) => (
              <tr key={spec.name} className="border-t border-slate-800">
                <td className="py-1 font-mono">{spec.name}</td>
                <td>{CATEGORY_LABEL[spec.category] ?? spec.category}</td>
                <td><span className={`rounded px-1.5 py-0.5 ${RISK_STYLE[spec.risk]}`}>{spec.risk}</span></td>
                <td>{spec.side_effects}</td>
                <td>{spec.timeout_s}s</td>
                <td>{Math.round(spec.max_output_bytes / 1024)}KB</td>
                <td>{spec.enabled_by_default ? '开启' : '关闭'}</td>
                <td>{spec.enabled ? '可用' : '禁用'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
