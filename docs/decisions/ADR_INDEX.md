# 架构决策记录（ADR）索引

> 每条 ADR 记录：背景 / 选项 / 决策 / 后果。新增决策追加，不修改历史。

| ADR | 标题 | 状态 | 日期 | 摘要 |
|---|---|---|---|---|
| ADR-0001 | 工作流引擎选 LangGraph 而非 CrewAI/Agent Framework | 已接受（待 V5 实测复核） | 2026-11-05 | interrupt+checkpoint+resume 是唯一语义级审批原语；角色概念层自研。详见 TECHNOLOGY_COMPARISON.md §1 |
| ADR-0002 | 模型网关用 LiteLLM SDK 形态，M0 不上 Proxy | 已接受 | 2026-11-05 | Proxy 需 Postgres，违背本地零依赖；M5 云端再评估 |
| ADR-0003 | API/CLI 统一 AgentAdapter + 能力声明矩阵 | 已接受 | 2026-11-05 | Codex/Copilot 能力差异已实证，必须显式声明不伪装。详见 AGENT_ADAPTER.md |
| ADR-0004 | 任务状态机由后端唯一裁决，AI 自称不改变状态 | 已接受（不可协商） | 2026-11-05 | 立项红线；监督中心的前提 |
| ADR-0005 | 任务与执行记录分离（task/task_run/agent_run 三层） | 已接受 | 2026-11-05 | 历史不覆盖；返工即新 run。详见 DATABASE_DESIGN.md |
| ADR-0006 | 许可证 MIT | 已接受（用户确认） | 2026-11-05 | 对比见 TECHNOLOGY_COMPARISON.md §7 |
| ADR-0007 | 本地优先，云端为可选控制平面 | 已接受 | 2026-11-05 | 本地模式 100% 功能可用；信任边界见 LOCAL_CLOUD_ARCHITECTURE.md |
| ADR-0008 | M0 不引入 Redis/K8s/消息队列 | 已接受 | 2026-11-05 | 反过度设计；引入需新 ADR |
| ADR-0009 | 事件流与审计日志分表 | 已接受 | 2026-11-05 | 借鉴 HALF TaskEvent/AuditLog 分离设计 |
| ADR-0010 | CLI 接入只走官方接口，Codex 为首个验证实例 | 已接受 | 2026-11-05 | exec --json + 官方 SDK；禁止逆向与抓会话 |
