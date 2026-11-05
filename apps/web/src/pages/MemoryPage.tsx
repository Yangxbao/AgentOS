import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { orgApi } from '../api/org'
import { memoryApi, type MemoryItem } from '../api/memory'

const SCOPE_LABEL: Record<string, string> = {
  employee: '员工私有',
  project: '项目共享',
  company: '公司共享',
}

function MemoryCard({ item, onChanged }: { item: MemoryItem; onChanged: () => void }) {
  const remove = useMutation({ mutationFn: () => memoryApi.remove(item.id), onSuccess: onChanged })
  const promote = useMutation({
    mutationFn: (to: 'project' | 'company') => memoryApi.promote(item.id, to),
    onSuccess: onChanged,
  })
  return (
    <div className="rounded border border-slate-800 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-300">
            {SCOPE_LABEL[item.scope] ?? item.scope}
          </span>
          <span className="text-sm font-medium">{item.title || '（无标题）'}</span>
          <span className="text-xs text-slate-500">{item.kind}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {item.scope === 'employee' && (
            <>
              <button
                className="text-sky-400 hover:underline"
                onClick={() => promote.mutate('project')}
              >
                提升为项目
              </button>
              <button
                className="text-sky-400 hover:underline"
                onClick={() => promote.mutate('company')}
              >
                提升为公司
              </button>
            </>
          )}
          <button
            className="text-rose-400 hover:underline"
            onClick={() => remove.mutate()}
          >
            删除
          </button>
        </div>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-xs text-slate-300">{item.content}</p>
      <p className="mt-1 text-xs text-slate-500">
        来源：{item.created_by_type} · {item.created_at.replace('T', ' ').slice(0, 19)}
      </p>
    </div>
  )
}

export default function MemoryPage() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const companyId = companies.data?.items[0]?.id ?? null
  const [scopeFilter, setScopeFilter] = useState('')
  const [search, setSearch] = useState('')
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [scope, setScope] = useState<'employee' | 'project' | 'company'>('project')

  const list = useQuery({
    queryKey: ['memories', companyId, scopeFilter],
    queryFn: () =>
      memoryApi.list(companyId as string, scopeFilter ? { scope: scopeFilter } : {}),
    enabled: Boolean(companyId),
  })
  const searchResult = useQuery({
    queryKey: ['memory-search', companyId, search],
    queryFn: () => memoryApi.search({ q: search, company_id: companyId as string, top_k: 10 }),
    enabled: Boolean(companyId) && search.trim().length > 0,
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['memories'] })
    queryClient.invalidateQueries({ queryKey: ['memory-search'] })
  }
  const create = useMutation({
    mutationFn: () =>
      memoryApi.create(companyId as string, { scope, title, content, kind: 'note' }),
    onSuccess: () => {
      setTitle('')
      setContent('')
      refresh()
    },
  })

  const items = search.trim() ? (searchResult.data?.items ?? []) : (list.data?.items ?? [])

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">记忆中心</h1>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          value={scopeFilter}
          onChange={(event) => setScopeFilter(event.target.value)}
        >
          <option value="">全部作用域</option>
          <option value="employee">员工私有</option>
          <option value="project">项目共享</option>
          <option value="company">公司共享</option>
        </select>
        <input
          className="w-64 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
          placeholder="检索记忆（FTS）…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <section className="rounded border border-slate-800 p-4">
        <h2 className="text-sm font-medium">写入记忆</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <select
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
            value={scope}
            onChange={(event) => setScope(event.target.value as typeof scope)}
          >
            <option value="project">项目共享</option>
            <option value="company">公司共享</option>
          </select>
          <input
            className="w-56 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
            placeholder="标题"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <input
            className="w-96 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
            placeholder="内容（密钥会自动脱敏）"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
          <button
            className="rounded bg-sky-700 px-3 py-1 text-sm text-white hover:bg-sky-600"
            disabled={!companyId || !content.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            写入
          </button>
          <span className="text-xs text-slate-500">
            员工私有记忆由 Agent 通过 memory.remember 写入；提升需人工操作并留审计。
          </span>
        </div>
      </section>

      <section className="space-y-2">
        {items.length === 0 && <p className="text-sm text-slate-500">没有记忆（无记忆时任务执行自动降级）</p>}
        {items.map((item) => (
          <MemoryCard key={item.id} item={item} onChanged={refresh} />
        ))}
      </section>
    </div>
  )
}
