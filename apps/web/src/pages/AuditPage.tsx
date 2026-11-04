import { useQuery } from '@tanstack/react-query'
import { governanceApi } from '../api/governance'

export default function AuditPage() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => governanceApi.audit() })

  return (
    <div className="space-y-4 p-6">
      <h2 className="text-lg font-semibold text-slate-100">审计日志</h2>
      <p className="text-xs text-slate-500">只增不改；没有更新/删除接口。</p>
      <div className="overflow-auto rounded border border-slate-800">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs text-slate-400">
            <tr>
              <th className="px-3 py-2">时间</th>
              <th className="px-3 py-2">动作</th>
              <th className="px-3 py-2">目标</th>
              <th className="px-3 py-2">主体</th>
              <th className="px-3 py-2">详情</th>
            </tr>
          </thead>
          <tbody>
            {audit.data?.items.map((row) => (
              <tr key={row.id} className="border-t border-slate-800 text-slate-300">
                <td className="px-3 py-2 text-xs text-slate-500">{row.created_at}</td>
                <td className="px-3 py-2">{row.action}</td>
                <td className="px-3 py-2 text-xs">{row.target_type}/{row.target_id}</td>
                <td className="px-3 py-2 text-xs">{row.actor_type}:{row.actor_id}</td>
                <td className="max-w-md truncate px-3 py-2 text-xs text-slate-500">
                  {JSON.stringify(row.detail)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {audit.data?.items.length === 0 && <p className="p-4 text-sm text-slate-500">暂无审计记录。</p>}
      </div>
    </div>
  )
}
