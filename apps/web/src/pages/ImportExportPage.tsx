import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { configApi, type ImportSummary } from '../api/config'
import { orgApi } from '../api/org'

export default function ImportExportPage() {
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportSummary | null>(null)
  const [result, setResult] = useState<ImportSummary | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const runDryRun = async () => {
    if (!file) return
    try {
      setMessage(null)
      setPreview(await configApi.importBundle(await file.arrayBuffer(), true))
    } catch (error) {
      setMessage(String(error))
    }
  }

  const runImport = async () => {
    if (!file) return
    try {
      setMessage(null)
      setResult(await configApi.importBundle(await file.arrayBuffer(), false))
      setPreview(null)
      setMessage('导入完成')
    } catch (error) {
      setMessage(String(error))
    }
  }

  if (!activeCompanyId) return <p className="p-6 text-slate-400">请先创建公司。</p>

  return (
    <div className="space-y-6 p-6">
      <h2 className="text-lg font-semibold text-slate-100">导入 / 导出</h2>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">导出公司配置</h3>
        <div className="mt-3 flex items-center gap-3">
          <select className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
                  value={activeCompanyId} onChange={(e) => setCompanyId(e.target.value)}>
            {companies.data?.items.map((company) => (
              <option key={company.id} value={company.id}>{company.name}</option>
            ))}
          </select>
          <button className="rounded bg-sky-600 px-4 py-2 text-sm text-white"
                  onClick={() => configApi.downloadExport(activeCompanyId).catch((e) => setMessage(String(e)))}>
            下载 zip
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">导出包只包含凭据引用（env:…），不包含密钥明文。</p>
      </section>

      <section className="rounded border border-slate-800 p-4">
        <h3 className="text-sm font-medium text-slate-200">导入配置</h3>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input type="file" accept=".zip"
                 className="text-sm text-slate-300"
                 onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); setResult(null) }} />
          <button className="rounded border border-slate-700 px-4 py-2 text-sm text-slate-200 disabled:opacity-50"
                  disabled={!file} onClick={runDryRun}>
            预检（dry-run）
          </button>
          <button className="rounded bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                  disabled={!preview} onClick={runImport}>
            确认导入
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">冲突策略：rename（保留双方，同名公司自动加后缀）。</p>

        {preview && (
          <div className="mt-4 rounded border border-slate-700 bg-slate-900 p-3 text-sm text-slate-300">
            <div>公司：{preview.company_name}（{preview.conflict ? '同名冲突，将改名' : '将新建'}）</div>
            <div className="mt-1 text-xs text-slate-400">
              部门 {preview.counts.departments} · 岗位 {preview.counts.positions} ·
              连接 {preview.counts.model_connections} · 员工 {preview.counts.employees} ·
              提示词 {preview.counts.prompts}
            </div>
          </div>
        )}
        {result && (
          <div className="mt-4 rounded border border-emerald-800 bg-emerald-950 p-3 text-sm text-emerald-200">
            已导入公司「{result.company_name}」：员工 {result.counts.employees} 人，提示词 {result.counts.prompts} 个
          </div>
        )}
      </section>

      {message && <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm">{message}</div>}
    </div>
  )
}
