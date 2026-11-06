import { useEffect, useState } from 'react'

export type ToastState = { kind: 'success' | 'error'; text: string } | null

/** 操作反馈 Toast：成功/失败都必须有明确提示（项目无第三方 UI 库，内联实现）。 */
export function useToast(): { toast: ToastState; showToast: (kind: 'success' | 'error', text: string) => void } {
  const [toast, setToast] = useState<ToastState>(null)
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 4000)
    return () => clearTimeout(timer)
  }, [toast])
  return { toast, showToast: (kind, text) => setToast({ kind, text }) }
}

export function Toast({ toast }: { toast: ToastState }) {
  if (!toast) return null
  return (
    <div
      role="status"
      className={`fixed right-6 top-6 z-50 max-w-md rounded border px-4 py-2 text-sm shadow-lg ${
        toast.kind === 'success'
          ? 'border-emerald-600 bg-emerald-900/90 text-emerald-100'
          : 'border-rose-600 bg-rose-900/90 text-rose-100'
      }`}
    >
      {toast.text}
    </div>
  )
}
