import { api } from './client'

export interface ImportSummary {
  dry_run: boolean
  company_name: string
  company_id?: string
  conflict?: boolean
  strategy?: string
  counts: Record<string, number>
}

const BASE = api.baseUrl

export const configApi = {
  async downloadExport(companyId: string): Promise<void> {
    const response = await fetch(`${BASE}/api/v1/companies/${companyId}/export`, {
      headers: { 'X-AgentOS-Client': 'web' },
    })
    if (!response.ok) throw new Error(`导出失败（HTTP ${response.status}）`)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `agentos-${companyId}.zip`
    anchor.click()
    URL.revokeObjectURL(url)
  },

  async importBundle(data: ArrayBuffer, dryRun: boolean): Promise<ImportSummary> {
    const response = await fetch(`${BASE}/api/v1/config/import?dry_run=${dryRun}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/zip', 'X-AgentOS-Client': 'web' },
      body: data,
    })
    const payload = await response.json()
    if (!response.ok) {
      const error = payload?.error
      throw new Error(error ? `${error.code}：${error.message}` : `导入失败（HTTP ${response.status}）`)
    }
    return payload as ImportSummary
  },
}
