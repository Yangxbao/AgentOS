import type { Approval } from '../api/tasks'

/** 把审批上下文转成给审批人看的摘要（tool_call 显示工具/风险/参数；其余显示步骤或摘要）。 */
export function approvalContextText(approval: Approval): string {
  const context = approval.context as Record<string, unknown> | undefined
  if (!context || typeof context !== 'object') return ''
  if (context.tool) {
    const args = typeof context.args === 'string'
      ? context.args
      : JSON.stringify(context.args ?? '')
    const argsPart = args && args !== '{}' ? ` · 参数 ${args.slice(0, 160)}` : ''
    return `调用工具 ${context.tool}（风险 ${context.risk ?? '—'}）${argsPart}`
  }
  if (context.summary) return `交付摘要：${String(context.summary).slice(0, 160)}`
  if (Array.isArray(context.steps) && context.steps.length > 0) {
    return `涉及步骤：${(context.steps as unknown[]).join('、')}`
  }
  if (context.title) return `任务：${context.title}`
  return ''
}
