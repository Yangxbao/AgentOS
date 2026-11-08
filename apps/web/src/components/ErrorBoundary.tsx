import { Component, type ReactNode } from 'react'

/** 全局错误边界：页面子树崩溃时显示可读信息，而不是白屏。 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-6 text-sm text-rose-300">
          <p className="font-medium">页面渲染出错：</p>
          <p className="mt-2 font-mono text-xs text-rose-400">{String(this.state.error)}</p>
          <button
            className="mt-4 rounded border border-slate-600 px-3 py-1 text-slate-200"
            onClick={() => this.setState({ error: null })}
          >
            重试渲染
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
