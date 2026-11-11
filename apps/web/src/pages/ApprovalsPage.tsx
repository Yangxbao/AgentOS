import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { tasksApi, type Approval } from '../api/tasks'
import { Toast, useToast } from '../components/Toast'
import { approvalContextText } from '../components/approvalText'

const GATE_LABEL: Record<string, string> = {
  before_run: '执行前', after_run: '交付前', tool_call: '工具调用',
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

function DecisionButtons({ approval, onDone }: { approval: Approval; onDone: (ok: boolean, text: string) => void }) {
  const [comment, setComment] = useState('')
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject' | 'request_changes') =>
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
      <button
        className="rounded bg-orange-700 px-2 py-1 text-xs text-white hover:bg-orange-600 disabled:opacity-50"
        disabled={decide.isPending}
        onClick={() => decide.mutate('request_changes')}
      >
        要求修改
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

  // 审批历史 CSV 导出（带 BOM，Excel 打开中文不乱码）
  const exportCsv = () => {
    const rows = approvals.data?.items ?? []
    const escape = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
    const csv = [
      'id,task_title,gate,status,decided_by,comment,created_at',
      ...rows.map((a) =>
        [a.id, a.task_title ?? '', a.gate, a.status, a.decided_by ?? '', a.comment ?? '', a.created_at ?? '']
          .map(escape).join(','),
      ),
    ].join('\r\n')
    const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `approvals_${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
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
        <button
          className="ml-auto rounded border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-40"
          disabled={(approvals.data?.items ?? []).length === 0}
          onClick={exportCsv}
        >
          导出 CSV
        </button>
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
              <td className="text-slate-300">
                {GATE_LABEL[approval.gate] ?? approval.gate}
                <div className="mt-1 max-w-xs text-slate-500">{approvalContextText(approval) || '—'}</div>
              </td>
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
            <tr>
              <td colSpan={5} className="py-3 text-slate-500">
                <p>没有符合条件的审批。</p>
                {statusFilter === 'pending' && (
                  <p className="mt-2 max-w-3xl text-slate-600">
                    审批会在这些情况出现：① 创建任务时勾选「需要人工审批」；② 步骤/工具风险高于公司策略的
                    自动执行上限；③ 员工调用了需要审批的高风险工具。Mock 或免费模型的低风险文本任务通常
                    不会产生审批——想体验完整审批流，可在创建任务时勾选「需要人工审批（执行前）」。
                  </p>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
