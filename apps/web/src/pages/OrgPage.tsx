import { useQuery } from '@tanstack/react-query'
import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { orgApi, type OrgNode, type OrgTree } from '../api/org'
import { peopleApi, type Employee } from '../api/people'

const DEPT_W = 210
const EMP_W = 172
const ROW_H = 84
const H_GAP = 310

const deptStyle = {
  width: DEPT_W,
  whiteSpace: 'pre-line' as const,
  fontSize: 12,
  fontWeight: 600,
  borderRadius: 10,
  border: '1px solid #334155',
  background: '#0f172a',
  color: '#e2e8f0',
  padding: 8,
}

const empStyle = {
  width: EMP_W,
  whiteSpace: 'pre-line' as const,
  fontSize: 11,
  borderRadius: 8,
  border: '1px solid #1e40af',
  background: '#0b1220',
  color: '#dbeafe',
  padding: 6,
}

/**
 * 组织架构布局（横向树 + 行区间分配，结构性无重叠）：
 * - 每个部门占一段连续"行带"，部门节点垂直居中于自己的行带；
 * - 部门直属员工排在部门右侧一列（紧跟其后）；子部门排在员工行之后；
 * - 兄弟部门的行带首尾相接、互不交叠，员工数与子树深度自动撑开行带高度。
 */
function buildGraph(tree: OrgTree, employees: Employee[], showEmployees: boolean): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = []
  const edges: Edge[] = []
  const rootId = 'company-root'

  const empByDept = new Map<string, Employee[]>()
  for (const employee of employees) {
    const key = employee.department_id ?? '__root__'
    if (!empByDept.has(key)) empByDept.set(key, [])
    empByDept.get(key)!.push(employee)
  }

  const placeDept = (node: OrgNode, depth: number, rowStart: number, parentId: string | null): number => {
    const id = `dept-${node.id}`
    const emps = empRowsByDept.get(node.id) ?? []
    let cursor = rowStart

    // 本部门直属员工：紧跟部门节点右侧一列
    const empStartRow = cursor
    cursor += Math.max(emps.length, 0)

    // 子部门依次向下排
    for (const child of node.children) {
      cursor += placeDept(child, depth + 1, cursor, id)
    }

    const totalRows = Math.max(cursor - rowStart, 1)
    const centerRow = rowStart + (totalRows - 1) / 2
    const positionNames = node.positions.map((p) => p.name).join(' / ')
    nodes.push({
      id,
      position: { x: depth * H_GAP, y: centerRow * ROW_H },
      data: {
        label: `${node.name}\n${node.positions.length} 岗位${positionNames ? `：${positionNames}` : ''}${emps.length ? `\n👥 员工 ${emps.length} 人` : ''}`,
      },
      style: deptStyle,
    })
    if (parentId) {
      edges.push({ id: `edge-${parentId}-${id}`, source: parentId, target: id })
    }
    if (showEmployees) {
      emps.forEach((employee, index) => {
        nodes.push({
          id: `emp-${employee.id}`,
          position: { x: depth * H_GAP + DEPT_W + 44, y: (empStartRow + index) * ROW_H },
          data: { label: `${employee.avatar || '🤖'} ${employee.name}\n${employee.title || '员工'}` },
          style: empStyle,
        })
        edges.push({
          id: `edge-${id}-emp-${employee.id}`,
          source: id,
          target: `emp-${employee.id}`,
          style: { strokeDasharray: '4 2' },
        })
      })
    }
    return totalRows
  }

  const empRowsByDept = new Map<string, Employee[]>()
  for (const employee of employees) {
    const key = employee.department_id ?? '__root__'
    if (!empRowsByDept.has(key)) empRowsByDept.set(key, [])
    empRowsByDept.get(key)!.push(employee)
  }

  let cursor = 0
  for (const dept of tree.departments) {
    cursor += placeDept(dept, 0, cursor, rootId)
  }

  // 公司根节点：垂直居中于整棵树
  nodes.push({
    id: rootId,
    position: { x: 0, y: -ROW_H },
    data: { label: `🏢 ${tree.company.name}` },
    style: {
      width: DEPT_W,
      fontSize: 13,
      fontWeight: 600,
      borderRadius: 10,
      border: '1px solid #0f766e',
      background: '#042f2e',
      color: '#ccfbf1',
      padding: 8,
    },
  })

  // 未分配部门的员工：默认聚合为一个节点（避免长列表撑爆画布），勾选后逐个显示
  const orphans = empRowsByDept.get('__root__') ?? []
  if (orphans.length > 0) {
    if (showEmployees) {
      orphans.forEach((employee, index) => {
        nodes.push({
          id: `emp-${employee.id}`,
          position: { x: H_GAP, y: -(index + 1) * ROW_H - 60 },
          data: { label: `${employee.avatar || '🤖'} ${employee.name}\n${employee.title || '员工'}` },
          style: empStyle,
        })
        edges.push({
          id: `edge-${rootId}-emp-${employee.id}`,
          source: rootId,
          target: `emp-${employee.id}`,
          style: { strokeDasharray: '4 2' },
        })
      })
    } else {
      nodes.push({
        id: 'orphan-group',
        position: { x: H_GAP, y: -150 },
        data: { label: `未分配部门的员工 ×${orphans.length}\n（可在员工详情中分配部门）` },
        style: { ...empStyle, width: 250, border: '1px solid #78350f', background: '#1c1917', color: '#fde68a' },
      })
      edges.push({
        id: `edge-${rootId}-orphan-group`,
        source: rootId,
        target: 'orphan-group',
        style: { strokeDasharray: '4 2' },
      })
    }
  }

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
  const [showEmployees, setShowEmployees] = useState(false)
  const graph = useMemo(
    () => (tree.data ? buildGraph(tree.data, employees.data?.items ?? [], showEmployees) : { nodes: [], edges: [] }),
    [tree.data, employees.data, showEmployees],
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
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={showEmployees} onChange={(e) => setShowEmployees(e.target.checked)} />
          显示员工节点
        </label>
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
            fitViewOptions={{ padding: 0.2 }}
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
