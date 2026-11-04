# Agent Adapter 统一接口设计

> v0.1｜2026-11-05｜解决"API 与 CLI 统一接入"难点
> 依据：codex.md / copilot-sdk.md / litellm.md 调研结论【已验证】

## 1. 设计目标

1. 任务引擎对"背后是 API 模型还是 CLI 工具"完全透明
2. 能力差异显式化——**能力声明机制**，不支持的功能明确标记，不伪装
3. 审批统一——任何执行体的高危动作都翻译为同一种 ApprovalRequest

## 2. 统一接口（Python Protocol）

```python
class AgentAdapter(Protocol):
    # 生命周期
    async def connect(self) -> None: ...
    async def health_check(self) -> HealthStatus: ...
    async def close(self) -> None: ...

    # 能力声明（连接后立即可得，静态+动态探测结合）
    def get_capabilities(self) -> CapabilitySet: ...

    # 执行
    async def execute(self, task: AgentTask, ctx: ExecutionContext) -> ExecutionHandle: ...
    async def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self, handle: ExecutionHandle, reason: str) -> None: ...
    async def cancel(self, handle: ExecutionHandle) -> None: ...

    # 计量
    async def get_usage(self, handle: ExecutionHandle) -> UsageReport: ...
```

### AgentEvent（统一事件流，借鉴 codex exec --json 的 JSONL 范式【已验证】）

```python
AgentEvent = {
    "type": "started|message|reasoning|tool_call|file_change|approval_required|usage|completed|failed|cancelled",
    "ts": datetime,
    "payload": dict,        # 各 Adapter 私有细节放这里
    "usage": UsageDelta|None,
}
```

## 3. CapabilitySet（能力声明矩阵）

| 能力 | 说明 | LiteLLM API | Codex CLI | Copilot SDK | Claude Code |
|---|---|---|---|---|---|
| streaming | 流式输出 | ✅ | ✅ | ✅ | 未验证 |
| interruptible | 可中断 | ⚠️仅取消请求 | ✅ | ✅ | 未验证 |
| structured_output | 结构化输出 | ✅(json mode) | ✅(--output-schema) | ✅(elicitation) | 未验证 |
| tool_calling | 工具调用 | ✅ | ✅(内置工具) | ✅ | 未验证 |
| file_ops | 文件操作 | ❌ | ✅(沙箱三档) | ✅(经审批) | 未验证 |
| approval_hook | 审批回调 | ❌(框架侧实现) | ⚠️(exec 模式不可交互，前置沙箱) | ✅(permission handler) | 未验证 |
| session_resume | 会话恢复 | ❌(无状态) | ✅(exec resume) | ✅ | 未验证 |
| usage_report | 费用统计 | ✅(token+cost) | ✅(turn.completed) | ⚠️(按订阅) | 未验证 |

> 上表 LiteLLM/Codex/Copilot 列【已验证-调研】；Claude Code 列待 M2 实测。
> Adapter 实现必须返回真实能力；`stream_events` 对不支持流式的实现返回 `CapabilityNotSupported`，任务引擎据此降级（一次性返回）。

## 4. 两个参考实现

### 4.1 LiteLLMAdapter（API 型）
- `execute` → `litellm.acompletion(model, messages, tools, fallbacks=[备用模型])`
- `stream_events` → 流式 chunk 翻译为 message/usage 事件
- `get_usage` → response.usage + `litellm.completion_cost()`；计价失败 cost=null【设计】
- 审批：无原生工具执行能力 → 文件/命令类工具由 workflow-engine 的工具层发起，经审批中心【设计】

### 4.2 CodexCLIAdapter（CLI 型）
- `connect` → 检测 `codex --version`，校验认证状态
- `execute` → spawn `codex exec --json --output-schema <schema> -C <workspace>`；**参数数组传参，禁止 shell 拼接**；沙箱默认 `read-only`，写操作必须审批后 `workspace-write`
- `stream_events` → 逐行解析 stdout JSONL（thread.started/item.*/turn.completed/error）
- `interrupt/cancel` → 进程组终止（Windows Job Object）【未验证，M0 实测】
- 审批映射：exec 模式不能交互审批【已验证】→ 策略为"前置授权"：任务计划中声明所需权限档位，用户批准后才 spawn 对应沙箱级别
- `get_usage` → `turn.completed` 事件的 token usage

## 5. 审批统一翻译

```
Adapter 原生审批点                    →  ApprovalRequest(action_type, risk_level, params, evidence)
LiteLLM: 无（工具由引擎层发起）        →  引擎在工具调用前生成
Codex: 前置沙箱档位 + execpolicy      →  计划阶段生成
Copilot: permission handler 回调      →  回调内同步生成并等待用户决定
```

**铁律**：ApprovalRequest 只能由用户裁决；Adapter 不得提供"自动批准自己"的路径（对应红线 11/12/13）。

## 6. 错误与超时模型【设计】

| 场景 | 行为 |
|---|---|
| 连接失败 | health_check 标记 unhealthy → 该员工任务挂起等待，不静默切模型 |
| 执行超时 | adapter 级 timeout → cancel → task_run 记 failed，可触发备用模型重试（员工配置了 fallback 时） |
| 主模型失败 | LiteLLM fallbacks 自动切备用模型，事件流记 `model_fallback` 事件（审计可见） |
| 能力不支持 | 任务规划期校验 CapabilitySet，不支持即拒绝派单并说明 |
