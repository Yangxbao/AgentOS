import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toolsApi } from '../api/tools'

export interface DeliverableInfo {
  step_id: string
  workspace_id: string
  workspace_name: string
  path: string
  size: number
  suffix: string
}

/** 交付成果预览：HTML 用沙箱 iframe 渲染，文本类直接展示——审批人先看到成果再签字。 */
export function DeliverablePreview({ deliverables }: { deliverables: DeliverableInfo[] }) {
  const [active, setActive] = useState(0)
  const current = deliverables[active]
  const content = useQuery({
    queryKey: ['deliverable-content', current?.workspace_id, current?.path],
    queryFn: () => toolsApi.fileContent(current!.workspace_id, current!.path),
    enabled: Boolean(current),
  })

  const isHtml = current?.suffix === '.html'
  const isMarkdown = current?.suffix === '.md'

  return (
    <div className="mt-2 overflow-hidden rounded border border-slate-700 bg-slate-900">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-2 py-1.5">
        <span className="text-xs text-slate-400">交付成果（{deliverables.length} 件）：</span>
        {deliverables.map((item, index) => (
          <button
            key={`${item.workspace_id}:${item.path}:${item.step_id}`}
            className={`rounded px-2 py-0.5 text-xs ${
              index === active ? 'bg-sky-600 text-white' : 'border border-slate-700 text-slate-300 hover:bg-slate-800'
            }`}
            onClick={() => setActive(index)}
          >
            {item.path.split('/').pop()}
            <span className="ml-1 text-[10px] opacity-70">{Math.ceil(item.size / 1024)}KB</span>
          </button>
        ))}
        {content.isError && (
          <span className="text-xs text-red-400">预览加载失败：{(content.error as Error).message}</span>
        )}
      </div>
      {current && isHtml ? (
        <iframe
          title={`交付物预览：${current.path}`}
          className="h-[520px] w-full bg-white"
          srcDoc={content.data?.content ?? ''}
          // 允许脚本（导航高亮等效果）但禁同源权限：员工生成的内容运行在沙箱内，无法触达父页面
          sandbox="allow-scripts"
        />
      ) : (
        <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap px-3 py-2 text-xs leading-5 text-slate-300">
          {content.data?.content ?? '加载中…'}
        </pre>
      )}
      <div className="border-t border-slate-800 px-2 py-1 text-[11px] text-slate-500">
        来源工作区：{current?.workspace_name} · {current?.path}
        {isMarkdown && '（Markdown 原文）'}
      </div>
    </div>
  )
}
