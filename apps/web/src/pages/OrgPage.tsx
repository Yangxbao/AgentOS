import { useQuery } from '@tanstack/react-query'
import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { orgApi, type OrgNode, type OrgTree } from '../api/org'
import { peopleApi, type Employee } from '../api/people'

const NODE_WIDTH = 200
const X_GAP = 260
const Y_GAP = 120

function buildGraph(tree: OrgTree, employees: Employee[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []
  const departmentLevels = new Map<string, number>()
  let row = 0

  // 公司根节点必须真实存在：否则员工挂到 company-root 时会产生悬空边
  nodes.push({
    id: 'company-root',
    position: { x: 0, y: -150 },
    data: { label: `🏢 ${tree.company.name}` },
    style: {
      width: NODE_WIDTH,
      fontSize: 13,
      fontWeight: 600,
      borderRadius: 10,
      border: '1px solid #0f766e',
      background: '#042f2e',
      color: '#ccfbf1',
      padding: 8,
    },
  })

  const walk = (node: OrgNode, level: number, parentId: string | null) => {
    const id = `dept-${node.id}`
    departmentLevels.set(node.id, level)
    const positionNames = node.positions.map((p) => p.name).join(' / ')
    nodes.push({
      id,
      position: { x: level * X_GAP, y: row * Y_GAP },
      data: {
        label: `${node.name}\n${node.positions.length} 岗位${positionNames ? `：${positionNames}` : ''}`,
      },
      style: {
        width: NODE_WIDTH,
        whiteSpace: 'pre-line',
        fontSize: 12,
        borderRadius: 10,
        border: '1px solid #334155',
        background: '#0f172a',
        color: '#e2e8f0',
        padding: 8,
      },
    })
    row += 1
    if (parentId) {
      edges.push({ id: `edge-${parentId}-${id}`, source: parentId, target: id, animated: false })
    }
    node.children.forEach((child) => walk(child, level + 1, id))
  }

  tree.departments.forEach((dept) => walk(dept, 0, 'company-root'))

  // 员工节点：挂在所属部门右侧；无部门则挂公司根节点左侧，避免与部门重叠
  const counters = new Map<string, number>()
  const addEmployeeNode = (employee: Employee, sourceId: string, x: number) => {
    const index = counters.get(sourceId) ?? 0
    counters.set(sourceId, index + 1)
    const id = `emp-${employee.id}`
    nodes.push({
      id,
      position: { x, y: index * 90 },
      data: { label: `${employee.avatar || '🤖'} ${employee.name}\n${employee.title || '员工'}` },
      style: {
        width: 160,
        whiteSpace: 'pre-line',
        fontSize: 11,
        borderRadius: 8,
        border: '1px solid #1e40af',
        background: '#0b1220',
        color: '#dbeafe',
        padding: 6,
      },
    })
    edges.push({ id: `edge-${sourceId}-${id}`, source: sourceId, target: id, style: { strokeDasharray: '4 2' } })
  }
  employees.forEach((employee) => {
    const departmentId = employee.department_id
    if (departmentId && departmentLevels.has(departmentId)) {
      addEmployeeNode(employee, `dept-${departmentId}`, (departmentLevels.get(departmentId)! + 1) * X_GAP)
    } else {
      addEmployeeNode(employee, 'company-root', -260)
    }
  })
  return { nodes, edges }
}

export default function OrgPage() {
  const [companyId, setCompanyId] = useState<string | null>(null)

  const companies = useQuery({ queryKey: ['companies'], queryFn: orgApi.listCompanies })
  const activeCompanyId = companyId ?? companies.data?.items[0]?.id ?? null

  const tree = useQuery({
    queryKey: ['org-tree', activeCompanyId],
    queryFn: () => orgApi.orgTree(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })

  const employees = useQuery({
    queryKey: ['employees', activeCompanyId],
    queryFn: () => peopleApi.listEmployees(activeCompanyId as string),
    enabled: Boolean(activeCompanyId),
  })
  const graph = useMemo(
    () => (tree.data ? buildGraph(tree.data, employees.data?.items ?? []) : { nodes: [], edges: [] }),
    [tree.data, employees.data],
  )

  if (companies.isLoading) return <p className="p-6 text-slate-400">正在加载公司…</p>

  if (!companies.data || companies.data.items.length === 0) {
    return (
      <div className="p-6">
        <h2 className="text-xl font-semibold text-slate-100">还没有公司</h2>
        <p className="mt-2 text-slate-400">先到组织设置创建一家公司，再回来查看组织架构。</p>
        <Link className="mt-4 inline-block rounded bg-sky-600 px-4 py-2 text-white" to="/settings/organization">
          去组织设置
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-slate-800 px-4 py-3">
        <h2 className="text-lg font-semibold text-slate-100">组织架构</h2>
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
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
        <button
          className="rounded border border-slate-700 px-3 py-1 text-sm text-slate-300"
          onClick={() => tree.refetch()}
        >
          刷新
        </button>
        {tree.isError && <span className="text-sm text-red-400">加载失败：{(tree.error as Error).message}</span>}
      </div>

      <div className="min-h-0 flex-1">
        {tree.isLoading ? (
          <p className="p-6 text-slate-400">正在加载组织树…</p>
        ) : !tree.data ? (
          <p className="p-6 text-slate-400">暂无组织数据</p>
        ) : (
          <ReactFlow
            key={graph.nodes.map((node) => node.id).join('|')}
            nodes={graph.nodes}
            edges={graph.edges}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls position="bottom-right" />
          </ReactFlow>
        )}
      </div>

      {tree.data && tree.data.departments.length === 0 && (
        <div className="border-t border-slate-800 px-4 py-3 text-sm text-slate-400">
          这家公司还没有部门，员工暂时挂在公司节点下。
          <Link className="ml-2 text-sky-400 underline" to="/settings/organization">去添加部门</Link>
        </div>
      )}

      {tree.data && tree.data.unassigned_positions.length > 0 && (
        <div className="border-t border-slate-800 px-4 py-3 text-sm text-slate-400">
          未归属部门的岗位：{tree.data.unassigned_positions.map((p) => p.name).join('、')}
        </div>
      )}
    </div>
  )
}
