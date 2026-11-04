import { useEffect, useState } from 'react'

type HealthStatus = 'checking' | 'connected' | 'disconnected'

function App() {
  const [status, setStatus] = useState<HealthStatus>('checking')

  useEffect(() => {
    fetch('http://localhost:8000/api/health')
      .then((res) => setStatus(res.ok ? 'connected' : 'disconnected'))
      .catch(() => setStatus('disconnected'))
  }, [])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-950 text-gray-100">
      <h1 className="text-3xl font-bold">AgentOS — AI 数字员工协作操作系统</h1>
      <p className="text-gray-400">M0 骨架运行中</p>
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
            ? '后端已连接'
            : '后端未连接'}
      </p>
    </div>
  )
}

export default App
