import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { tasksApi, type PlanStep } from '../api/tasks'
import { toolsApi } from '../api/tools'
import { StateBadge } from './TasksPage'

const ACTIVE_STATES = new Set(['queued', 'running', 'paused', 'awaiting_approval', 'rework_required'])

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

function ts(value: string | null | undefined): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
}

export default function TaskDetailPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const [message, setMessage] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [rewind, setRewind] = useState('')
  const [steps, setSteps] = useState<PlanStep[]>([])
  const [maxParallel, setMaxParallel] = useState(4)
  const [planDirty, setPlanDirty] = useState(false)

  const task = useQuery({
    queryKey: ['task', id],
    queryFn: () => tasksApi.detail(id),
    refetchInterval: (query) => {
      const state = query.state.data?.state
      return state && ACTIVE_STATES.has(state) ? 1500 : false
    },
  })

  useEffect(() => {
    if (task.data && !planDirty) {
      setSteps(task.data.plan?.steps ?? [])
      setMaxParallel(task.data.plan?.max_parallel ?? 4)
    }
  }, [task.data, planDirty])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['task', id] })
    queryClient.invalidateQueries({ queryKey: ['timeline', id] })
    queryClient.invalidateQueries({ queryKey: ['toolCalls', id] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }

  const action = (fn: (taskId: string) => Promise<unknown>, label: string) =>
    useMutation({
      mutationFn: () => fn(id),
      onSuccess: () => { setMessage(`${label}已提交`); refresh() },
      onError: (error) => setMessage(errorText(error)),
    })

  const run = action(tasksApi.run, '执行')
  const pause = action(tasksApi.pause, '暂停')
  const resume = action(tasksApi.resume, '恢复')
  const retry = action(tasksApi.retry, '重试')
  const cancel = action(tasksApi.cancel, '取消')

  const savePlan = useMutation({
    mutationFn: () => tasksApi.setPlan(id, {
      steps: steps.map((step, index) => ({
        id: step.id || `s${index + 1}`,
        title: step.title || '',
        employee_id: step.employee_id,
        instruction: step.instruction,
        deliverable: step.deliverable || '',
        depends_on: step.depends_on ?? [],
      })),
      max_parallel: maxParallel,
    }),
    onSuccess: () => { setPlanDirty(false); setMessage('计划已保存'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  const decide = useMutation({
    mutationFn: (payload: { approvalId: string; decision: string }) =>
      tasksApi.decide(payload.approvalId, {
        decision: payload.decision,
        comment,
        rewind_step_id: rewind || null,
      }),
    onSuccess: () => { setComment(''); setRewind(''); setMessage('审批已处理'); refresh() },
    onError: (error) => setMessage(errorText(error)),
  })

  const timeline = useQuery({
    queryKey: ['timeline', id],
    queryFn: () => tasksApi.timeline(id),
    enabled: Boolean(id),
    refetchInterval: 3000,
  })

  const toolCalls = useQuery({
    queryKey: ['toolCalls', id],
    queryFn: () => toolsApi.taskToolCalls(id),
    enabled: Boolean(id),
    // 与时间线一致：工具调用可能由后台 worker 在其他页面触发，固定轮询最稳
    refetchInterval: 3000,
  })

  // M3-B：失败/待返工任务的重规划（≤3 次；只重置失败步骤及其下游）
    const [replanSteps, setReplanSteps] = useState<Record<string, string> | null>(null)
  const [replanFailedStep, setReplanFailedStep] = useState<string>('')
  const replan = useMutation({
    mutationFn: () => {
      const current = data.plan?.steps ?? []
      const steps = current.map((step) => ({
        id: step.id,
        employee_id: step.employee_id,
        instruction: replanSteps?.[step.id] ?? step.instruction,
        depends_on: step.depends_on,
        tools: step.tools,
      }))
      return tasksApi.replan(id, {
        steps,
        failed_step_id: replanFailedStep || undefined,
        reason: '页面重规划',
      })
    },
    onSuccess: (result) => {
      setReplanSteps(null)
      setMessage(`重规划完成：计划版本 v${result.plan_revision}（第 ${result.replan_count}/3 次），失败步骤及下游已重置`)
      refresh()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  if (task.isLoading) return <p className="p-6 text-slate-400">加载中…</p>
  if (task.isError || !task.data) return <p className="p-6 text-red-400">{errorText(task.error)}</p>

  const data = task.data
  const employees = Object.values(data.employees)
  const stepOptions = data.plan?.steps ?? []

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/tasks" className="text-sm text-slate-400 hover:text-slate-200">← 任务中心</Link>
        <h1 className="text-lg font-semibold">{data.title}</h1>
        <StateBadge state={data.state} />
        <span className="text-xs text-slate-500">
          {data.priority} · 风险 {data.risk_level} · 模式 {data.execution_mode}
        </span>
        <div className="ml-auto flex flex-wrap gap-2 text-sm">
          <button className="rounded bg-sky-600 px-3 py-1.5 text-white disabled:opacity-40"
                  disabled={data.state !== 'draft'} onClick={() => run.mutate()}>执行</button>
          <button className="rounded border border-amber-700 px-3 py-1.5 text-amber-300 disabled:opacity-40"
                  disabled={!['running', 'queued'].includes(data.state)} onClick={() => pause.mutate()}>暂停</button>
          <button className="rounded border border-sky-700 px-3 py-1.5 text-sky-300 disabled:opacity-40"
                  disabled={!['paused', 'rework_required'].includes(data.state)} onClick={() => resume.mutate()}>恢复</button>
          <button className="rounded border border-slate-600 px-3 py-1.5 text-slate-300 disabled:opacity-40"
                  disabled={!['failed', 'cancelled'].includes(data.state)} onClick={() => retry.mutate()}>重试</button>
          <button className="rounded border border-red-800 px-3 py-1.5 text-red-300 disabled:opacity-40"
                  disabled={['succeeded', 'cancelled', 'skipped', 'review_passed'].includes(data.state)}
                  onClick={() => cancel.mutate()}>取消</button>
        </div>
      </div>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}

      <section className="grid gap-3 text-sm md:grid-cols-4">
        <div className="rounded border border-slate-800 p-3">
          <div className="text-xs text-slate-500">执行员工</div>
          <div>{data.employees[data.assignee_employee_id ?? '']?.name ?? '—'}</div>
        </div>
        <div className="rounded border border-slate-800 p-3">
          <div className="text-xs text-slate-500">审批</div>
          <div>{data.approval_required ? `${data.approval_stage === 'before_run' ? '执行前' : '交付后'}审批` : '不需要'}</div>
        </div>
        <div className="rounded border border-slate-800 p-3">
          <div className="text-xs text-slate-500">Token / 成本</div>
          <div>{data.usage.total_tokens} / ${data.usage.total_cost_usd.toFixed(6)}</div>
        </div>
        <div className="rounded border border-slate-800 p-3">
          <div className="text-xs text-slate-500">返工</div>
          <div>{data.rework_count} / {data.max_rework}</div>
        </div>
      </section>

      {data.pending_approvals.length > 0 && (
        <section className="rounded border border-purple-800 bg-purple-950/30 p-4">
          <h2 className="text-sm font-medium text-purple-200">待审批</h2>
          {data.pending_approvals.map((approval) => (
            <div key={approval.id} className="mt-3 space-y-2 text-sm">
              <div className="text-slate-300">
                关卡：{approval.gate === 'before_run' ? '执行前' : approval.gate === 'tool_call' ? '工具调用' : '交付后'} · 发起人 {approval.requested_by}
                {approval.reviewer_employee_id && ` · 指定审查员工 ${data.employees[approval.reviewer_employee_id]?.name ?? approval.reviewer_employee_id}`}
              </div>
              <input className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                     placeholder="审批意见（驳回时必填）" value={comment}
                     onChange={(event) => setComment(event.target.value)} />
              <select className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2"
                      value={rewind} onChange={(event) => setRewind(event.target.value)}>
                <option value="">驳回时回退到（默认第一步）</option>
                {stepOptions.map((step) => (
                  <option key={step.id} value={step.id}>{step.id} · {step.title || step.instruction.slice(0, 30)}</option>
                ))}
              </select>
              <div className="flex gap-2">
                <button className="rounded bg-emerald-600 px-3 py-1.5 text-white"
                        onClick={() => decide.mutate({ approvalId: approval.id, decision: 'approve' })}>批准</button>
                <button className="rounded bg-orange-700 px-3 py-1.5 text-white"
                        onClick={() => decide.mutate({ approvalId: approval.id, decision: 'request_changes' })}>要求修改</button>
                <button className="rounded bg-red-700 px-3 py-1.5 text-white"
                        onClick={() => decide.mutate({ approvalId: approval.id, decision: 'reject' })}>驳回</button>
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="rounded border border-slate-800 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-medium">工具调用</h2>
          <span className="text-xs text-slate-500">
            {toolCalls.data?.total ?? 0} 次
            {(toolCalls.data?.items ?? []).some((item) => ['high', 'critical'].includes(item.risk_level)) && (
              <span className="ml-2 rounded bg-red-900 px-1.5 py-0.5 text-red-300">含高风险调用</span>
            )}
          </span>
          <span className="ml-auto text-xs text-slate-500">被拒绝的调用同样留痕，不隐藏</span>
        </div>
        {toolCalls.isLoading && <p className="mt-2 text-xs text-slate-500">加载中…</p>}
        {toolCalls.data && toolCalls.data.total === 0 && (
          <p className="mt-2 text-xs text-slate-500">
            本任务没有工具调用（员工未获授权工具、全局开关关闭，或模型未请求工具）。
          </p>
        )}
        {toolCalls.data && toolCalls.data.total > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full table-fixed text-left text-xs">
              <thead className="text-slate-500">
                <tr>
                  <th className="w-28 py-1">工具</th>
                  <th className="w-24">状态</th>
                  <th className="w-16">风险</th>
                  <th className="w-16">步骤</th>
                  <th className="w-56">参数摘要</th>
                  <th className="w-16">耗时</th>
                  <th className="w-44">结果 / 错误</th>
                  <th className="w-28">审批</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {toolCalls.data.items.map((call) => {
                  const risky = ['high', 'critical'].includes(call.risk_level)
                  return (
                    <tr key={call.id}
                        className={`border-t border-slate-800 align-top ${risky ? 'bg-red-950/20' : ''}`}>
                      <td className="py-1 font-mono">{call.tool_name}</td>
                      <td>
                        <span className={`rounded px-1.5 py-0.5 ${
                          call.status === 'succeeded' ? 'bg-emerald-900 text-emerald-300'
                            : call.status === 'denied' ? 'bg-red-900 text-red-300'
                            : call.status === 'awaiting_approval' ? 'bg-purple-900 text-purple-300'
                            : call.status === 'timeout' ? 'bg-amber-900 text-amber-300'
                            : 'bg-slate-800 text-slate-300'
                        }`}>
                          {call.status}
                        </span>
                      </td>
                      <td>
                        <span className={`rounded px-1.5 py-0.5 ${
                          risky ? 'bg-red-900 text-red-300' : 'bg-slate-800 text-slate-300'
                        }`}>{call.risk_level}</span>
                      </td>
                      <td>{call.step_id || '—'} / #{call.call_index}</td>
                      <td className="break-all font-mono text-[11px] text-slate-400"
                          title={JSON.stringify(call.args_summary)}>
                        {JSON.stringify(call.args_summary).slice(0, 90)}
                        {JSON.stringify(call.args_summary).length > 90 ? '…' : ''}
                      </td>
                      <td>{call.duration_ms}ms</td>
                      <td className="break-all">
                        {call.error_code
                          ? <span className="text-red-300">{call.error_code}：{call.error_message}</span>
                          : (
                            <span className="text-slate-400" title={JSON.stringify(call.output_summary)}>
                              {JSON.stringify(call.output_summary).slice(0, 110)}
                              {JSON.stringify(call.output_summary).length > 110 ? '…' : ''}
                            </span>
                          )}
                      </td>
                      <td>
                        {call.approval_status === 'pending' && call.approval_id ? (
                          <span className="flex gap-1">
                            <button className="rounded bg-emerald-600 px-2 py-0.5 text-white"
                                    data-testid={`tool-approve-${call.id}`}
                                    onClick={() => decide.mutate({ approvalId: call.approval_id as string, decision: 'approve' })}>
                              批准调用
                            </button>
                            <button className="rounded bg-red-700 px-2 py-0.5 text-white"
                                    data-testid={`tool-reject-${call.id}`}
                                    onClick={() => decide.mutate({ approvalId: call.approval_id as string, decision: 'reject' })}>
                              驳回调用
                            </button>
                          </span>
                        ) : (
                          <span className="text-slate-500">{call.approval_status ?? '—'}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {(data.state === 'failed' || data.state === 'rework_required') && (
        <section className="rounded border border-amber-800 bg-amber-950/20 p-4">
          <div className="flex items-center gap-3">
            <h2 className="text-sm font-medium text-amber-200">重规划</h2>
            <span className="text-xs text-slate-500">
              已用 {data.replan_count}/3 次 · 计划版本 v{data.plan_revision ?? 1}；只重置失败步骤及其下游，上游产出保留
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {(data.plan?.steps ?? []).map((step) => (
              <div key={step.id} className="flex items-center gap-2 text-xs">
                <span className="w-10 font-mono text-slate-400">{step.id}</span>
                <span className="w-40 truncate text-slate-500">
                  {data.employees[step.employee_id ?? '']?.name ?? step.employee_id?.slice(0, 8) ?? '—'}
                </span>
                <input
                  className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-100"
                  value={replanSteps?.[step.id] ?? step.instruction}
                  onChange={(event) =>
                    setReplanSteps({ ...(replanSteps ?? {}), [step.id]: event.target.value })
                  }
                />
                <label className="flex items-center gap-1 text-slate-500">
                  <input
                    type="radio"
                    name="failed_step"
                    checked={replanFailedStep === step.id}
                    onChange={() => setReplanFailedStep(step.id)}
                  />
                  标记失败
                </label>
              </div>
            ))}
            <div className="flex items-center gap-3">
              <button
                className="rounded bg-amber-700 px-3 py-1.5 text-sm text-white disabled:opacity-50"
                disabled={replan.isPending || data.replan_count >= 3}
                onClick={() => replan.mutate()}
              >
                {data.replan_count >= 3 ? '重规划次数已用尽' : '提交重规划'}
              </button>
              {replanSteps !== null && (
                <button className="text-xs text-slate-400 hover:underline" onClick={() => setReplanSteps(null)}>
                  放弃修改
                </button>
              )}
              <span className="text-xs text-slate-500">提交后请点「重试」让任务重新入队。</span>
            </div>
          </div>
        </section>
      )}

      <section className="rounded border border-slate-800 p-4">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium">执行计划</h2>
          <span className="text-xs text-slate-500">{data.plan?.steps.length ?? 0} 步，最大并行 {data.plan?.max_parallel ?? 1}</span>
          <button className="ml-auto rounded border border-slate-700 px-2 py-1 text-xs"
                  disabled={data.state !== 'draft' || savePlan.isPending}
                  onClick={() => savePlan.mutate()}>保存计划</button>
        </div>
        {steps.length === 0 && (
          <p className="mt-2 text-xs text-slate-500">
            未设计划：按单员工单步执行（执行记录里仍会显示步骤 s1）。
          </p>
        )}
        <div className="mt-3 space-y-2">
          {steps.map((step, index) => (
            <div key={index} className="grid gap-2 rounded border border-slate-800 p-2 md:grid-cols-12">
              <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs md:col-span-1"
                     value={step.id} placeholder={`s${index + 1}`}
                     onChange={(event) => {
                       const next = [...steps]
                       next[index] = { ...step, id: event.target.value }
                       setSteps(next); setPlanDirty(true)
                     }} />
              <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs md:col-span-3"
                      value={step.employee_id}
                      onChange={(event) => {
                        const next = [...steps]
                        next[index] = { ...step, employee_id: event.target.value }
                        setSteps(next); setPlanDirty(true)
                      }}>
                <option value="">选择员工</option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>{employee.name}</option>
                ))}
              </select>
              <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs md:col-span-4"
                     value={step.instruction} placeholder="该员工要做什么"
                     onChange={(event) => {
                       const next = [...steps]
                       next[index] = { ...step, instruction: event.target.value }
                       setSteps(next); setPlanDirty(true)
                     }} />
              <input className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs md:col-span-3"
                     value={(step.depends_on ?? []).join(',')} placeholder="依赖，如 s1,s2"
                     onChange={(event) => {
                       const next = [...steps]
                       next[index] = {
                         ...step,
                         depends_on: event.target.value.split(',').map((item) => item.trim()).filter(Boolean),
                       }
                       setSteps(next); setPlanDirty(true)
                     }} />
              <button className="text-xs text-red-400 md:col-span-1"
                      disabled={data.state !== 'draft'}
                      onClick={() => { setSteps(steps.filter((_, i) => i !== index)); setPlanDirty(true) }}>删除</button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
          <button className="rounded border border-slate-700 px-2 py-1"
                  disabled={data.state !== 'draft'}
                  onClick={() => {
                    setSteps([...steps, {
                      id: `s${steps.length + 1}`, employee_id: employees[0]?.id ?? '',
                      instruction: '', depends_on: [],
                    }])
                    setPlanDirty(true)
                  }}>+ 添加步骤</button>
          <label>
            最大并行
            <input type="number" min={1} max={8} className="ml-2 w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1"
                   value={maxParallel}
                   onChange={(event) => { setMaxParallel(Number(event.target.value)); setPlanDirty(true) }} />
          </label>
          {data.state !== 'draft' && <span>计划只能在草稿状态修改</span>}
        </div>
      </section>

      {data.children.length > 0 && (
        <section className="rounded border border-slate-800 p-4">
          <h2 className="text-sm font-medium">子任务</h2>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr><th className="py-1">步骤</th><th>标题</th><th>执行员工</th><th>状态</th><th>产出</th></tr>
            </thead>
            <tbody>
              {data.children.map((child) => (
                <tr key={child.id} className="border-t border-slate-800">
                  <td className="py-1 text-slate-400">
                    {(child.plan as unknown as { step_id?: string })?.step_id ?? '—'}
                  </td>
                  <td>{child.title}</td>
                  <td className="text-slate-300">{data.employees[child.assignee_employee_id ?? '']?.name ?? '—'}</td>
                  <td><StateBadge state={child.state} /></td>
                  <td className="max-w-md truncate text-slate-500">
                    {String((child.result as Record<string, unknown>)?.content ?? '')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded border border-slate-800 p-4">
        <h2 className="text-sm font-medium">执行记录</h2>
        <div className="mt-2 space-y-3">
          {data.runs.length === 0 && <p className="text-sm text-slate-500">尚未执行</p>}
          {[...data.runs].reverse().map((runInfo) => (
            <div key={runInfo.id} className="rounded border border-slate-800 p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-slate-300">#{runInfo.run_no}</span>
                <StateBadge state={runInfo.state} />
                <span className="text-slate-500">{runInfo.trigger} · {runInfo.mode}</span>
                <span className="text-slate-500">{ts(runInfo.started_at)} → {ts(runInfo.ended_at)}</span>
                <span className="text-slate-500">完成步骤 {(runInfo.checkpoint.completed_steps ?? []).join(', ') || '—'}</span>
              </div>
              {runInfo.error && <div className="mt-1 text-red-400">{runInfo.error}</div>}
              {runInfo.agent_runs.map((agent) => (
                <details key={agent.id} className="mt-2 rounded border border-slate-800 p-2">
                  <summary className="cursor-pointer text-slate-300">
                    {agent.step_id} · {agent.employee_name} · {agent.model} ·{' '}
                    <StateBadge state={agent.state} />
                    <span className="ml-2 text-slate-500">{ts(agent.started_at)}</span>
                  </summary>
                  <div className="mt-2 space-y-1 text-slate-400">
                    <div>提示词版本：{agent.prompt_version ?? '未使用版本化提示词'}</div>
                    <div className="whitespace-pre-wrap break-all">输入：{String(agent.input.instruction ?? '').slice(0, 1200)}</div>
                    <div className="whitespace-pre-wrap break-all">输出：{String(agent.output.content ?? '').slice(0, 1200)}</div>
                    {agent.error && <div className="text-red-400">错误：{agent.error}</div>}
                  </div>
                </details>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h2 className="text-sm font-medium">时间线</h2>
        <ol className="mt-2 space-y-1 text-xs">
          {(timeline.data?.items ?? []).map((item, index) => (
            <li key={index} className="flex gap-3 border-t border-slate-800 py-1">
              <span className="w-36 shrink-0 text-slate-500">{ts(item.at)}</span>
              <span className="w-40 shrink-0 text-slate-400">{item.type}</span>
              <span className="text-slate-300">
                {item.kind === 'agent_run' && `${item.step_id} · ${item.employee_name} · ${item.model}`}
                {item.kind === 'handoff' && `交接 → ${item.step_id}：${item.summary ?? ''}`}
                {item.kind === 'approval' && `${item.status ?? ''} ${item.comment ?? ''}`}
                {item.kind === 'tool_call' && `${item.tool ?? ''} · ${item.status ?? ''}${item.error_code ? ` · ${item.error_code}` : ''}`}
                {item.kind === 'tool_call' && `${item.tool ?? ''} · ${item.status ?? ''}${item.error_code ? ` · ${item.error_code}` : ''}`}
                {item.kind === 'event' && JSON.stringify(item.payload ?? {}).slice(0, 160)}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h2 className="text-sm font-medium">成本明细</h2>
        <p className="mt-1 text-xs text-slate-500">
          调用 {data.usage.calls} 次 · 合计 {data.usage.total_tokens} tokens · ${data.usage.total_cost_usd.toFixed(6)}
          {data.usage.unknown_cost_records > 0 && `（${data.usage.unknown_cost_records} 条计价失败，未编造金额）`}
        </p>
        <table className="mt-2 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr><th className="py-1">员工</th><th>模型</th><th>Prompt</th><th>Completion</th><th>成本</th><th>计费</th></tr>
          </thead>
          <tbody>
            {data.usage.records.map((record) => (
              <tr key={record.agent_run_id} className="border-t border-slate-800">
                <td className="py-1">{record.employee_name}</td>
                <td className="text-slate-400">{record.model}</td>
                <td>{record.prompt_tokens}</td>
                <td>{record.completion_tokens}</td>
                <td>{record.cost_usd === null ? '—' : `$${record.cost_usd.toFixed(6)}`}</td>
                <td className="text-slate-500">{record.billable ? '真实' : 'Mock'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
