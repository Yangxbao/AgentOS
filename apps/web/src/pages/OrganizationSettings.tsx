import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { orgApi } from '../api/org'

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

export default function OrganizationSettings() {
  const queryClient = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const [companyId, setCompanyId] = useState<string | null>(null)
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  useEffect(() => {
    if (companies.data && companies.data.items.length > 0 && !companyId) {
      setCompanyId(companies.data.items[0].id)
    }
  }, [companies.data, companyId])

  const [companyName, setCompanyName] = useState('')
  const [deptName, setDeptName] = useState('')
  const [deptParent, setDeptParent] = useState('')
  const [positionName, setPositionName] = useState('')
  const [positionDept, setPositionDept] = useState('')
  const [canReview, setCanReview] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const departments = useQuery({
    queryKey: ['departments', activeCompanyId],
    queryFn: () => orgApi.listDepartments(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const positions = useQuery({
    queryKey: ['positions', activeCompanyId],
    queryFn: () => orgApi.listPositions(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  const invalidateOrg = () => {
    queryClient.invalidateQueries({ queryKey: ['companies'] })
    queryClient.invalidateQueries({ queryKey: ['departments'] })
    queryClient.invalidateQueries({ queryKey: ['positions'] })
    queryClient.invalidateQueries({ queryKey: ['org-tree'] })
  }

  const createCompany = useMutation({
    mutationFn: () => orgApi.createCompany({ name: companyName.trim() }),
    onSuccess: (company) => {
      setCompanyName('')
      setCompanyId(company.id)
      setMessage(`公司「${company.name}」已创建`)
      invalidateOrg()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const createDepartment = useMutation({
    mutationFn: () =>
      orgApi.createDepartment(activeCompanyId as string, {
        name: deptName.trim(),
        parent_id: deptParent || null,
      }),
    onSuccess: (dept) => {
      setDeptName('')
      setMessage(`部门「${dept.name}」已创建（第 ${dept.depth + 1} 层）`)
      invalidateOrg()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const createPosition = useMutation({
    mutationFn: () =>
      orgApi.createPosition(activeCompanyId as string, {
        name: positionName.trim(),
        department_id: positionDept || null,
        can_review: canReview,
      }),
    onSuccess: (position) => {
      setPositionName('')
      setCanReview(false)
      setMessage(`岗位「${position.name}」已创建`)
      invalidateOrg()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const removeDepartment = useMutation({
    mutationFn: (id: string) => orgApi.deleteDepartment(id),
    onSuccess: () => {
      setMessage('部门已删除')
      invalidateOrg()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const removePosition = useMutation({
    mutationFn: (id: string) => orgApi.deletePosition(id),
    onSuccess: () => {
      setMessage('岗位已删除')
      invalidateOrg()
    },
    onError: (error) => setMessage(errorText(error)),
  })

  const busy =
    createCompany.isPending || createDepartment.isPending || createPosition.isPending ||
    removeDepartment.isPending || removePosition.isPending

  return (
    <div className="space-y-8 p-6">
      <section>
        <h2 className="text-lg font-semibold text-slate-100">公司</h2>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            placeholder="新公司名称"
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
          />
          <button
            className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
            disabled={!companyName.trim() || busy}
            onClick={() => createCompany.mutate()}
          >
            创建公司
          </button>
          {companies.data && companies.data.items.length > 0 && (
            <select
              className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
              value={activeCompanyId ?? ''}
              onChange={(event) => setCompanyId(event.target.value)}
            >
              {companies.data.items.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                  {company.status === 'archived' ? '（已归档）' : ''}
                </option>
              ))}
            </select>
          )}
        </div>
      </section>

      {activeCompanyId && (
        <>
          <section>
            <h2 className="text-lg font-semibold text-slate-100">部门</h2>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input
                className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                placeholder="部门名称"
                value={deptName}
                onChange={(event) => setDeptName(event.target.value)}
              />
              <select
                className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={deptParent}
                onChange={(event) => setDeptParent(event.target.value)}
              >
                <option value="">（作为顶级部门）</option>
                {departments.data?.items.map((dept) => (
                  <option key={dept.id} value={dept.id}>
                    {'　'.repeat(dept.depth)}
                    {dept.name}
                  </option>
                ))}
              </select>
              <button
                className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                disabled={!deptName.trim() || busy}
                onClick={() => createDepartment.mutate()}
              >
                添加部门
              </button>
            </div>

            <ul className="mt-4 space-y-2">
              {departments.data?.items.map((dept) => (
                <li
                  key={dept.id}
                  className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm"
                >
                  <span className="text-slate-200">
                    {'　'.repeat(dept.depth)}
                    {dept.name}
                    <span className="ml-2 text-xs text-slate-500">L{dept.depth + 1}</span>
                  </span>
                  <button
                    className="text-xs text-red-400 hover:underline"
                    onClick={() => removeDepartment.mutate(dept.id)}
                  >
                    删除
                  </button>
                </li>
              ))}
              {departments.data?.items.length === 0 && (
                <li className="text-sm text-slate-500">还没有部门</li>
              )}
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-slate-100">岗位</h2>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <input
                className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                placeholder="岗位名称（如 技术审查官）"
                value={positionName}
                onChange={(event) => setPositionName(event.target.value)}
              />
              <select
                className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
                value={positionDept}
                onChange={(event) => setPositionDept(event.target.value)}
              >
                <option value="">（跨部门岗位）</option>
                {departments.data?.items.map((dept) => (
                  <option key={dept.id} value={dept.id}>
                    {dept.name}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input type="checkbox" checked={canReview} onChange={(event) => setCanReview(event.target.checked)} />
                具备审查资格
              </label>
              <button
                className="rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
                disabled={!positionName.trim() || busy}
                onClick={() => createPosition.mutate()}
              >
                添加岗位
              </button>
            </div>

            <ul className="mt-4 space-y-2">
              {positions.data?.items.map((position) => (
                <li
                  key={position.id}
                  className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm"
                >
                  <span className="text-slate-200">
                    {position.name}
                    {position.can_review && (
                      <span className="ml-2 rounded bg-emerald-900 px-2 py-0.5 text-xs text-emerald-300">
                        可审查
                      </span>
                    )}
                    {position.is_managerial && (
                      <span className="ml-2 rounded bg-indigo-900 px-2 py-0.5 text-xs text-indigo-300">
                        管理岗
                      </span>
                    )}
                  </span>
                  <button
                    className="text-xs text-red-400 hover:underline"
                    onClick={() => removePosition.mutate(position.id)}
                  >
                    删除
                  </button>
                </li>
              ))}
              {positions.data?.items.length === 0 && (
                <li className="text-sm text-slate-500">还没有岗位</li>
              )}
            </ul>
          </section>
        </>
      )}

      {message && (
        <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">
          {message}
        </div>
      )}
    </div>
  )
}
