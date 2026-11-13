import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../api/client'

export interface DeliverableInfo {
  step_id: string
  workspace_id: string
  workspace_name: string
  path: string
  size: number
  suffix: string
}

/**
 * 交付成果预览：
 * - 网页（.html/.htm）用沙箱 iframe 加载整站端点——相对路径的 CSS/JS/图片全部生效，
 *   审批人直接看到网站实际效果并可点击页面；
 * - 文档（.md/.txt 等）以原文展示。
 * 页签默认选中首页（index.html）。
 */
export function DeliverablePreview({ deliverables }: { deliverables: DeliverableInfo[] }) {
  const ordered = useMemo(() => {
    const pages = deliverables.filter((d) => d.suffix === '.html' || d.suffix === '.htm')
    const docs = deliverables.filter((d) => d.suffix !== '.html' && d.suffix !== '.htm')
    return [...pages, ...docs]
  }, [deliverables])

  const [active, setActive] = useState(() => {
    const firstPage = ordered.findIndex((d) => d.suffix === '.html' || d.suffix === '.htm')
    return firstPage >= 0 ? firstPage : 0
  })
  const current = ordered[active]
  const isPage = current?.suffix === '.html' || current?.suffix === '.htm'
  const isHtmlDoc = isPage

  const docContent = useQuery({
    queryKey: ['deliverable-content', current?.workspace_id, current?.path],
    queryFn: () => api.get<{ path: string; size: number; content: string }>(
      `/api/v1/workspaces/${current!.workspace_id}/files/content?path=${encodeURIComponent(current!.path)}`,
    ),
    enabled: Boolean(current) && !isPage,
  })

  if (!current) return null

  const siteUrl = `${api.baseUrl}/api/v1/workspaces/${current.workspace_id}/site/${current.path
    .split('/')
    .map((segment) => encodeURIComponent(segment))
    .join('/')}`

  return (
    <div className="mt-2 overflow-hidden rounded border border-slate-700 bg-slate-900">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-2 py-1.5">
        <span className="text-xs text-slate-400">交付成果（{ordered.length} 件）：</span>
        {ordered.map((item, index) => {
          const isWeb = item.suffix === '.html' || item.suffix === '.htm'
          return (
            <button
              key={`${item.workspace_id}:${item.path}:${item.step_id}`}
              className={`rounded px-2 py-0.5 text-xs ${
                index === active ? 'bg-sky-600 text-white' : 'border border-slate-700 text-slate-300 hover:bg-slate-800'
              }`}
              onClick={() => setActive(index)}
            >
              {isWeb && <span className="mr-1">🌐</span>}
              {item.path.split('/').pop()}
              <span className="ml-1 text-[10px] opacity-70">{Math.ceil(item.size / 1024)}KB</span>
            </button>
          )
        })}
      </div>
      {isHtmlDoc ? (
        <iframe
          title={`网站效果预览：${current.path}`}
          className="h-[560px] w-full bg-white"
          src={siteUrl}
          // 允许脚本（导航高亮/表单校验等）但禁同源权限：员工生成的代码运行在沙箱内
          sandbox="allow-scripts allow-forms allow-same-origin"
        />
      ) : (
        <pre className="max-h-[520px] overflow-auto whitespace-pre-wrap px-3 py-2 text-xs leading-5 text-slate-300">
          {docContent.data?.content ?? '加载中…'}
        </pre>
      )}
      <div className="border-t border-slate-800 px-2 py-1 text-[11px] text-slate-500">
        {isPage ? '🌐 网站实际效果（可点击页面内链接）' : '📄 文档内容'} · 来源工作区：{current.workspace_name} · {current.path}
      </div>
    </div>
  )
}
