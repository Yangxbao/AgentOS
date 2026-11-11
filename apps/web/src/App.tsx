import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { api } from './api/client'
import type { HealthResponse } from './api/types'
import { ErrorBoundary } from './components/ErrorBoundary'

// 路由级代码分割：首屏只加载当前页面（此前 15 个页面打进一个 527kB bundle）
const OrganizationSettings = lazy(() => import('./pages/OrganizationSettings'))
const EmployeeDetailPage = lazy(() => import('./pages/EmployeeDetailPage'))
const EmployeesPage = lazy(() => import('./pages/EmployeesPage'))
const AssignmentPage = lazy(() => import('./pages/AssignmentPage'))
const AuditPage = lazy(() => import('./pages/AuditPage'))
const ImportExportPage = lazy(() => import('./pages/ImportExportPage'))
const ModelConnectionsPage = lazy(() => import('./pages/ModelConnectionsPage'))
const ApprovalsPage = lazy(() => import('./pages/ApprovalsPage'))
const MemoryPage = lazy(() => import('./pages/MemoryPage'))
const MonitorPage = lazy(() => import('./pages/MonitorPage'))
const OrgPage = lazy(() => import('./pages/OrgPage'))
const TaskDetailPage = lazy(() => import('./pages/TaskDetailPage'))
const TasksPage = lazy(() => import('./pages/TasksPage'))
const ToolPolicyPage = lazy(() => import('./pages/ToolPolicyPage'))
const WorkspacesPage = lazy(() => import('./pages/WorkspacesPage'))

function PageFallback() {
  return <p className="p-6 text-slate-500">页面加载中…</p>
}

function HealthBadge() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<HealthResponse>('/api/health'),
    retry: 0,
    refetchInterval: 30_000,
  })

  if (health.isLoading) return <span className="text-xs text-slate-500">检测后端…</span>
  if (health.isError) {
    return <span className="text-xs text-red-400">后端未连接</span>
  }
  return (
    <span className="text-xs text-emerald-400">
      后端已连接 · v{health.data?.version}
    </span>
  )
}

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `rounded px-3 py-1.5 text-sm ${
          isActive ? 'bg-slate-800 text-slate-100' : 'text-slate-400 hover:text-slate-200'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

function Shell() {
  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center gap-4 border-b border-slate-800 px-4 py-3">
        <span className="font-semibold">AgentOS</span>
        <nav className="flex items-center gap-1">
          <NavItem to="/tasks">任务中心</NavItem>
          <NavItem to="/monitor">执行监控</NavItem>
          <NavItem to="/approvals">审批中心</NavItem>
          <NavItem to="/org">组织架构</NavItem>
          <NavItem to="/employees">AI 员工</NavItem>
          <NavItem to="/assignments">派工预览</NavItem>
          <NavItem to="/settings/workspaces">工作区</NavItem>
          <NavItem to="/settings/tools">工具策略</NavItem>
          <NavItem to="/settings/memory">记忆中心</NavItem>
          <NavItem to="/settings/models">模型连接</NavItem>
          <NavItem to="/settings/import-export">导入导出</NavItem>
          <NavItem to="/settings/audit">审计</NavItem>
          <NavItem to="/settings/organization">组织设置</NavItem>
        </nav>
        <div className="ml-auto">
          <HealthBadge />
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto">
        <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Navigate to="/tasks" replace />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/tasks/:id" element={<TaskDetailPage />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="/approvals" element={<ApprovalsPage />} />
              <Route path="/org" element={<OrgPage />} />
              <Route path="/employees" element={<EmployeesPage />} />
              <Route path="/employees/:id" element={<EmployeeDetailPage />} />
              <Route path="/settings/workspaces" element={<WorkspacesPage />} />
              <Route path="/settings/tools" element={<ToolPolicyPage />} />
              <Route path="/settings/memory" element={<MemoryPage />} />
              <Route path="/settings/models" element={<ModelConnectionsPage />} />
              <Route path="/assignments" element={<AssignmentPage />} />
              <Route path="/settings/import-export" element={<ImportExportPage />} />
              <Route path="/settings/audit" element={<AuditPage />} />
              <Route path="/settings/organization" element={<OrganizationSettings />} />
              <Route path="*" element={<p className="p-6 text-slate-400">页面不存在</p>} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Router>
      <Shell />
    </Router>
  )
}
