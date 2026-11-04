import { useQuery } from '@tanstack/react-query'
import { Navigate, NavLink, Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { api } from './api/client'
import type { HealthResponse } from './api/types'
import OrganizationSettings from './pages/OrganizationSettings'
import OrgPage from './pages/OrgPage'

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
          <NavItem to="/org">组织架构</NavItem>
          <NavItem to="/settings/organization">组织设置</NavItem>
        </nav>
        <div className="ml-auto">
          <HealthBadge />
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Navigate to="/org" replace />} />
          <Route path="/org" element={<OrgPage />} />
          <Route path="/settings/organization" element={<OrganizationSettings />} />
          <Route path="*" element={<p className="p-6 text-slate-400">页面不存在</p>} />
        </Routes>
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
