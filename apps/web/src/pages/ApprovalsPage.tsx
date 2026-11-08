import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { tasksApi, type Approval } from '../api/tasks'
import { Toast, useToast } from '../components/Toast'

const GATE_LABEL: Record<string, string> = {
  before_run: '执行前', after_run: '交付前', tool_call: '工具调用',
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

function DecisionButtons({ approval, onDone }: { approval: Approval; onDone: (ok: boolean, text: string) => void }) {
  const [comment, setComment] = useState('')
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject') =>
      tasksApi.decide(approval.id, { decision, comment: comment.trim() }),
    onSuccess: (_result, decision) => {
      onDone(true, decision === 'approve' ? `审批 ${approval.id.slice(0, 8)} 已批准` : `审批 ${approval.id.slice(0, 8)} 已驳回`)
    },
    onError: (error) => onDone(false, errorText(error)),
  })
  return (
    <div className="flex items-center gap-1">
      <input
        className="w-36 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
        placeholder="备注（驳回原因写审计）"
        value={comment}
        onChange={(event) => setComment(event.target.value)}
      />
      <button
        className="rounded bg-emerald-700 px-2 py-1 text-xs text-white hover:bg-emerald-600 disabled:opacity-50"
        disabled={decide.isPending}
        onClick={() => decide.mutate('approve')}
      >
        批准
      </button>
      <button
        className="rounded bg-rose-700 px-2 py-1 text-xs text-white hover:bg-rose-600 disabled:opacity-50"
        disabled={decide.isPending}
        onClick={() => decide.mutate('reject')}
      >
        驳回
      </button>
    </div>
  )
}

export default function ApprovalsPage() {
  const queryClient = useQueryClient()
  const { toast, showToast } = useToast()
  const [statusFilter, setStatusFilter] = useState('pending')

  const approvals = useQuery({
    queryKey: ['approvals', statusFilter],
    queryFn: () =>
      tasksApi.pendingApprovals(statusFilter === 'all' ? {} : { status_filter: statusFilter }),
    refetchInterval: 4000,
  })

  const onDone = (ok: boolean, text: string) => {
    showToast(ok ? 'success' : 'error', text)
    queryClient.invalidateQueries({ queryKey: ['approvals'] })
    queryClient.invalidateQueries({ queryKey: ['monitor'] })
  }

  return (
    <div className="space-y-5 p-6">
      <Toast toast={toast} />
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">审批中心</h1>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="pending">待审批</option>
          <option value="approved">已批准</option>
          <option value="rejected">已驳回</option>
          <option value="changes_requested">要求修改</option>
          <option value="all">全部</option>
        </select>
        {approvals.isFetching && <span className="text-xs text-slate-500">刷新中…</span>}
      </div>

      <p className="text-xs text-slate-500">
        工具调用类审批（gate=tool_call）只决定这一次调用是否放行；批准后任务自动继续，
        员工授权、工作区、预算与熔断检查均不因审批而放宽。
      </p>

      <table className="w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="py-1">任务</th><th>闸门</th><th>状态</th><th>请求时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {(approvals.data?.items ?? []).map((approval) => (
            <tr key={approval.id} className="border-t border-slate-800 align-top">
              <td className="py-2">
                <Link className="text-sky-400 hover:underline" to={`/tasks/${approval.task_id}`}>
                  {approval.task_title || approval.task_id.slice(0, 10)}
                </Link>
              </td>
              <td className="text-slate-300">{GATE_LABEL[approval.gate] ?? approval.gate}</td>
              <td className={approval.status === 'pending' ? 'text-amber-400' : 'text-slate-500'}>
                {approval.status}
                {approval.decided_by && <span className="ml-1 text-slate-600">by {approval.decided_by}</span>}
              </td>
              <td className="text-slate-500">
                {(approval.created_at ?? '').replace('T', ' ').slice(0, 19)}
              </td>
              <td>
                {approval.status === 'pending' ? (
                  <DecisionButtons approval={approval} onDone={onDone} />
                ) : (
                  <span className="text-slate-600">{approval.comment || '—'}</span>
                )}
              </td>
            </tr>
          ))}
          {(approvals.data?.items ?? []).length === 0 && (
            <tr><td colSpan={5} className="py-3 text-slate-500">没有符合条件的审批</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
