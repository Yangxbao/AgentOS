import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'

interface ShowcaseProject {
  id: string
  workspace_id: string
  workspace_name: string
  entry: string
  type: string
  icon: string
  title: string
  desc: string
  highlights: string[]
}

/** 成品展示中心：AI 团队交付的网站/文档，点击直接在页内打开真实效果。 */
export default function ShowcasePage() {
  const showcase = useQuery({
    queryKey: ['showcase'],
    queryFn: () => api.get<{ projects: ShowcaseProject[] }>('/api/v1/showcase'),
  })
  const [active, setActive] = useState<ShowcaseProject | null>(null)

  if (showcase.isLoading) return <p className="p-6 text-slate-400">加载中…</p>
  if (showcase.isError) return <p className="p-6 text-red-400">加载失败：{(showcase.error as Error).message}</p>

  const projects = showcase.data?.projects ?? []

  if (active) {
    const siteUrl = `${api.baseUrl}/api/v1/workspaces/${active.workspace_id}/site/${active.entry
      .split('/')
      .map((segment) => encodeURIComponent(segment))
      .join('/')}`
    const isDoc = active.type === 'doc'
    return (
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-3">
          <button className="text-sm text-slate-400 hover:text-slate-200" onClick={() => setActive(null)}>
            ← 成果展示
          </button>
          <h2 className="text-lg font-semibold text-slate-100">
            {active.icon} {active.title}
          </h2>
          <a
            className="text-xs text-sky-400 hover:underline"
            href={siteUrl}
            target="_blank"
            rel="noreferrer"
          >
            新窗口打开 ↗
          </a>
        </div>
        <div className="min-h-0 flex-1 bg-white">
          {isDoc ? (
            <DocPreview workspaceId={active.workspace_id} path={active.entry} />
          ) : (
            <iframe
              title={active.title}
              className="h-full w-full"
              src={siteUrl}
              sandbox="allow-scripts allow-forms allow-same-origin"
            />
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">成果展示</h2>
        <p className="mt-1 text-xs text-slate-500">
          AI 员工团队交付的成品——点击任意项目，直接在页内打开真实效果（网站可交互、文档可阅读）。
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {projects.map((project) => (
          <button
            key={project.id}
            className="group rounded-lg border border-slate-800 bg-slate-900 p-5 text-left transition hover:border-sky-600 hover:bg-slate-800/60"
            onClick={() => setActive(project)}
          >
            <div className="text-3xl">{project.icon}</div>
            <div className="mt-3 text-base font-medium text-slate-100 group-hover:text-sky-300">
              {project.title}
            </div>
            <div className="mt-2 text-xs leading-5 text-slate-400">{project.desc}</div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {project.highlights.map((h) => (
                <span key={h} className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-400">
                  {h}
                </span>
              ))}
            </div>
            <div className="mt-3 text-xs text-sky-400 group-hover:underline">打开成品 →</div>
          </button>
        ))}
        {projects.length === 0 && (
          <p className="text-sm text-slate-500">
            暂无登记的成品——AI 团队完成任务后，把成果登记到工作区的 showcase.json 即可在这里展示。
          </p>
        )}
      </div>
    </div>
  )
}

/** 文档类成品：原文阅读（带简单样式）。 */
function DocPreview({ workspaceId, path }: { workspaceId: string; path: string }) {
  const doc = useQuery({
    queryKey: ['showcase-doc', workspaceId, path],
    queryFn: () =>
      api.get<{ content: string }>(
        `/api/v1/workspaces/${workspaceId}/files/content?path=${encodeURIComponent(path)}`,
      ),
  })
  if (doc.isLoading) return <p className="p-6 text-slate-400">加载中…</p>
  if (doc.isError) return <p className="p-6 text-red-400">加载失败：{(doc.error as Error).message}</p>
  return (
    <div className="mx-auto max-w-3xl px-8 py-6">
      <pre className="whitespace-pre-wrap font-sans text-sm leading-6 text-slate-800">
        {doc.data?.content}
      </pre>
    </div>
  )
}
