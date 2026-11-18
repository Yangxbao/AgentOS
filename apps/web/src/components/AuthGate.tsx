import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { authApi, authStore } from '../api/auth'

/** 登录/注册表单（M4 账号体系：AGENTOS_AUTH=on 时展示）。 */
function AuthForm({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'register') {
        await authApi.register(username.trim(), password, displayName.trim())
      }
      const result = await authApi.login(username.trim(), password)
      authStore.save(result.token, result.user)
      onSignedIn()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto mt-24 w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900 p-6">
      <div className="mb-5 text-center">
        <div className="text-xl font-semibold text-slate-100">🏢 AgentOS</div>
        <div className="mt-1 text-xs text-slate-500">
          {mode === 'login' ? '登录你的 AI 公司' : '注册新账号'}
        </div>
      </div>
      <div className="space-y-3">
        <input
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          placeholder="用户名"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        {mode === 'register' && (
          <input
            className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            placeholder="显示名称（可选）"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        )}
        <input
          type="password"
          className="w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
          placeholder="密码（注册需至少 8 位）"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        {error && <div className="rounded bg-red-950 px-2 py-1.5 text-xs text-red-300">{error}</div>}
        <button
          className="w-full rounded bg-sky-600 px-4 py-2 text-sm text-white disabled:opacity-50"
          disabled={busy || !username.trim() || !password}
          onClick={submit}
        >
          {busy ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}
        </button>
        <button
          className="w-full text-xs text-slate-500 hover:text-slate-300"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
        >
          {mode === 'login' ? '还没有账号？去注册' : '已有账号？去登录'}
        </button>
      </div>
    </div>
  )
}

/**
 * 认证闸门（M4）：认证关闭（默认）时直接放行（行为与历史版本一致）；
 * 认证开启且未登录时展示登录页；已登录渲染子内容。
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const status = useQuery({ queryKey: ['auth-status'], queryFn: () => authApi.status(), staleTime: 60_000 })
  const [, setAuthVersion] = useState(0)

  // 监听登出/登录事件刷新
  useEffect(() => {
    const handler = () => setAuthVersion((v) => v + 1)
    window.addEventListener('agentos-auth-changed', handler)
    return () => window.removeEventListener('agentos-auth-changed', handler)
  }, [])

  if (status.isLoading) return <p className="p-6 text-slate-500">正在连接后端…</p>
  if (status.isError) return <p className="p-6 text-red-400">后端未连接：{(status.error as Error).message}</p>
  if (!status.data?.enabled) return <>{children}</>
  if (!authStore.token() || !authStore.user()) return <AuthForm onSignedIn={() => setAuthVersion((v) => v + 1)} />
  return <>{children}</>
}

/** 顶栏当前用户与登出按钮（认证关闭时不渲染）。 */
export function AuthBadge() {
  const status = useQuery({ queryKey: ['auth-status'], queryFn: () => authApi.status(), staleTime: 60_000 })
  const [, setVersion] = useState(0)
  const [showPwd, setShowPwd] = useState(false)
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [pwdMsg, setPwdMsg] = useState<string | null>(null)
  const [pwdBusy, setPwdBusy] = useState(false)

  useEffect(() => {
    const handler = () => setVersion((v) => v + 1)
    window.addEventListener('agentos-auth-changed', handler)
    return () => window.removeEventListener('agentos-auth-changed', handler)
  }, [])

  if (!status.data?.enabled) return null
  const user = authStore.user()
  const logout = async () => {
    try {
      await authApi.logout()
    } catch {
      /* 会话可能已过期 */
    }
    authStore.clear()
    setVersion((v) => v + 1)
  }
  if (!user) return null
  return (
    <span className="relative flex items-center gap-2 text-xs text-slate-400">
      <span className="rounded bg-slate-800 px-2 py-0.5">{user.display_name || user.username}</span>
      <button className="text-slate-500 hover:text-slate-300" onClick={() => setShowPwd(!showPwd)}>
        改密
      </button>
      <button className="text-slate-500 hover:text-slate-300" onClick={logout}>
        登出
      </button>
      {showPwd && (
        <div className="absolute right-0 top-7 z-50 w-64 rounded border border-slate-700 bg-slate-900 p-3 shadow-xl">
          <div className="mb-2 text-xs font-medium text-slate-200">修改密码</div>
          <input
            type="password"
            className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
            placeholder="旧密码"
            value={oldPwd}
            onChange={(e) => setOldPwd(e.target.value)}
          />
          <input
            type="password"
            className="mb-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100"
            placeholder="新密码（至少 8 位）"
            value={newPwd}
            onChange={(e) => setNewPwd(e.target.value)}
          />
          {pwdMsg && <div className="mb-2 text-[11px] text-amber-300">{pwdMsg}</div>}
          <button
            className="w-full rounded bg-sky-600 px-2 py-1.5 text-xs text-white disabled:opacity-50"
            disabled={pwdBusy || !oldPwd || newPwd.length < 8}
            onClick={async () => {
              setPwdBusy(true)
              setPwdMsg(null)
              try {
                const r = await authApi.changePassword(oldPwd, newPwd)
                setPwdMsg(r.message + '，请重新登录')
                authStore.clear()
              } catch (err) {
                setPwdMsg(err instanceof Error ? err.message : String(err))
              } finally {
                setPwdBusy(false)
              }
            }}
          >
            {pwdBusy ? '提交中…' : '确认修改'}
          </button>
        </div>
      )}
    </span>
  )
}
