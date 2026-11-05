import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { orgApi } from '../api/org'
import { systemApi } from '../api/system'
import { tasksApi } from '../api/tasks'
import { StateBadge } from './TasksPage'

const STATE_LABEL: Record<string, string> = {
  draft: '草稿', pending: '待调度', queued: '排队中', running: '执行中',
  paused: '已暂停', awaiting_approval: '待审批', rework_required: '待返工',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过',
  review_passed: '已通过（遗留）', in_review: '审查中（遗留）',
}

function ts(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
}

export default function MonitorPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const summary = useQuery({
    queryKey: ['monitor', activeCompanyId],
    queryFn: () => tasksApi.monitor(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
    refetchInterval: 3000,
  })

  const toolEnabled = summary.data?.tool_execution?.enabled ?? false
  const switchToolExecution = useMutation({
    mutationFn: (enabled: boolean) => systemApi.setToolExecution(enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitor'] }),
  })

  const data = summary.data
  const maxState = Math.max(1, ...Object.values(data?.states ?? {}))

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">执行监控</h1>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          value={activeCompanyId ?? ''}
          onChange={(event) => setCompanyId(event.target.value)}
        >
          {(companies.data?.items ?? []).map((company) => (
            <option key={company.id} value={company.id}>{company.name}</option>
          ))}
        </select>
        {summary.isFetching && <span className="text-xs text-slate-500">刷新中…</span>}
      </div>

      {!data && <p className="text-sm text-slate-500">暂无数据</p>}

      {data && (
        <>
          <section className="grid gap-3 md:grid-cols-5">
            {[
              { label: '任务总数', value: data.task_total },
              { label: '进行中执行', value: data.active_runs },
              { label: '待审批', value: data.pending_approvals },
              { label: '失败任务', value: data.failed_tasks },
              { label: '今日成本', value: `$${data.today_cost_usd.toFixed(6)}` },
            ].map((card) => (
              <div key={card.label} className="rounded border border-slate-800 p-3">
                <div className="text-xs text-slate-500">{card.label}</div>
                <div className="text-xl font-semibold">{card.value}</div>
              </div>
            ))}
          </section>

          <section className="rounded border border-slate-800 p-4">
            <h2 className="text-sm font-medium">状态分布</h2>
            <div className="mt-3 space-y-2">
              {Object.entries(data.states).length === 0 && (
                <p className="text-sm text-slate-500">还没有任务</p>
              )}
              {Object.entries(data.states).map(([state, count]) => (
                <div key={state} className="flex items-center gap-3 text-xs">
                  <span className="w-28 text-slate-400">{STATE_LABEL[state] ?? state}</span>
                  <div className="h-2 rounded bg-slate-800" style={{ width: `${Math.max(4, (count / maxState) * 60)}%` }}>
                    <div className="h-2 rounded bg-sky-600" />
                  </div>
                  <span className="text-slate-300">{count}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="grid gap-3 md:grid-cols-2">
            <div className="rounded border border-slate-800 p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-medium">工具执行（全局）</h2>
                <button
                  className={`rounded px-2 py-1 text-xs ${
                    toolEnabled
                      ? 'bg-rose-700 text-white hover:bg-rose-600'
                      : 'bg-emerald-700 text-white hover:bg-emerald-600'
                  }`}
                  disabled={switchToolExecution.isPending}
                  onClick={() => switchToolExecution.mutate(!toolEnabled)}
                >
                  {toolEnabled ? '紧急停止工具执行' : '恢复工具执行'}
                </button>
              </div>
              <p className="mt-2 text-xs text-slate-400">
                当前状态：
                <span className={toolEnabled ? 'text-emerald-400' : 'text-rose-400'}>
                  {toolEnabled ? ' 开启' : ' 关闭（一切工具调用将被拒绝）'}
                </span>
                。开关立即生效、写审计留痕；进程重启后回到 AGENTOS_TOOL_EXECUTION 的初始值。
              </p>
              {data?.tools && (
                <p className="mt-1 text-xs text-slate-500">
                  累计调用 {data.tools.total} 次
                  {Object.entries(data.tools.by_status).map(([status, count]) => ` · ${status} ${count}`).join('')}
                </p>
              )}
            </div>

            <div className="rounded border border-slate-800 p-4">
              <h2 className="text-sm font-medium">拒绝原因 Top N</h2>
              <ul className="mt-2 space-y-1 text-xs">
                {(data?.tools?.denials_top ?? []).map((item) => (
                  <li key={item.code} className="flex items-center justify-between">
                    <span className="font-mono text-slate-300">{item.code}</span>
                    <span className="text-slate-500">{item.count} 次</span>
                  </li>
                ))}
                {(data?.tools?.denials_top ?? []).length === 0 && (
                  <li className="text-slate-500">没有被拒绝的工具调用</li>
                )}
              </ul>
            </div>
          </section>

          <section className="rounded border border-slate-800 p-4">
            <h2 className="text-sm font-medium">预算使用率（进行中的任务）</h2>
            <table className="mt-2 w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">任务</th><th>状态</th><th>已用 / 预算</th><th>使用率</th>
                </tr>
              </thead>
              <tbody>
                {(data?.budgets?.watching ?? []).map((item) => (
                  <tr key={item.task_id} className="border-t border-slate-800">
                    <td className="py-1 text-slate-300">{item.title}</td>
                    <td><StateBadge state={item.state} /></td>
                    <td className="text-slate-400">
                      ${item.spent_usd.toFixed(4)} / ${item.budget_usd.toFixed(2)}
                    </td>
                    <td className={item.ratio >= 0.9 ? 'text-rose-400' : 'text-slate-300'}>
                      {(item.ratio * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
                {(data?.budgets?.watching ?? []).length === 0 && (
                  <tr><td className="py-3 text-slate-500" colSpan={4}>没有设置预算的进行中任务</td></tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="rounded border border-slate-800 p-4">
            <h2 className="text-sm font-medium">最近 Agent 执行</h2>
            <table className="mt-2 w-full text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-1">步骤</th><th>员工</th><th>模型</th><th>状态</th><th>开始</th><th>耗时</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_agent_runs.map((agent) => {
                  const started = agent.started_at ? new Date(agent.started_at).getTime() : 0
                  const ended = agent.ended_at ? new Date(agent.ended_at).getTime() : 0
                  return (
                    <tr key={agent.id} className="border-t border-slate-800">
                      <td className="py-1 text-slate-400">{agent.step_id ?? '—'}</td>
                      <td>{agent.employee_name}</td>
                      <td className="text-slate-400">{agent.model}</td>
                      <td><StateBadge state={agent.state} /></td>
                      <td className="text-slate-500">{ts(agent.started_at)}</td>
                      <td className="text-slate-500">{started && ended ? `${ended - started}ms` : '—'}</td>
                    </tr>
                  )
                })}
                {data.recent_agent_runs.length === 0 && (
                  <tr><td className="py-4 text-slate-500" colSpan={6}>还没有执行记录</td></tr>
                )}
              </tbody>
            </table>
          </section>

          <p className="text-xs text-slate-500">
            今日调用 {data.today_calls} 次。Mock 执行不计费（billable=false），成本列显示 0 是真实记录而非估算。
          </p>
        </>
      )}
    </div>
  )
}
