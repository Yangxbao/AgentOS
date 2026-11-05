import { api } from './client'

export interface ToolExecutionState {
  env_enabled: boolean
  kill_switch: boolean
  enabled: boolean
}

/** 系统级控制（M3-E）：全局工具执行紧急开关。 */
export const systemApi = {
  toolExecution: () => api.get<ToolExecutionState>('/api/v1/system/tool-execution'),
  setToolExecution: (enabled: boolean) =>
    api.post<ToolExecutionState>('/api/v1/system/tool-execution', { enabled }),
}
