import { useEffect, useState } from 'react'
import { ApiError, api } from './api/client'
import type { HealthResponse } from './api/types'

type HealthStatus = 'checking' | 'connected' | 'disconnected'

function App() {
  const [status, setStatus] = useState<HealthStatus>('checking')
  const [detail, setDetail] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api
      .get<HealthResponse>('/api/health', { signal: controller.signal })
      .then((data) => {
        setStatus('connected')
        setDetail(`v${data.version} · ${data.mode}`)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setStatus('disconnected')
        setDetail(error instanceof ApiError ? error.message : '未知错误')
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-950 text-gray-100">
      <h1 className="text-3xl font-bold">AgentOS — AI 数字员工协作操作系统</h1>
      <p className="text-gray-400">M1 / B1 骨架运行中</p>
      <p
        className={
          status === 'connected'
            ? 'text-green-400'
            : status === 'disconnected'
              ? 'text-red-400'
              : 'text-gray-500'
        }
      >
        {status === 'checking'
          ? '正在检测后端连接…'
          : status === 'connected'
            ? `后端已连接（${detail}）`
            : `后端未连接：${detail}`}
      </p>
    </div>
  )
}

export default App
