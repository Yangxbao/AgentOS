# AgentOS 系统架构

> v0.1｜2026-11-05｜依据：PROJECT_SELECTION.md（已定案选型）
> 标注：【定案】调研支撑的决策｜【设计】待验证的设计｜【未验证】假设

## 1. 总体分层

```
┌────────────────────────────────────────────────────────┐
│ apps/web  React 18 + TS + Vite + Tailwind + shadcn/ui  │
│  组织图(React Flow) / 任务面板 / 审批台 / 会议室 / 成本仪表盘 │
├────────────────────────────────────────────────────────┤
│ apps/api  FastAPI（REST + WebSocket）                    │
│  ┌──────────────────────────────────────────────────┐ │
│  │ 治理层（全自研 = 产品本体）                          │ │
│  │ organization  公司/部门/岗位/上下级                  │ │
│  │ task-engine   任务状态机/调度/执行记录               │ │
│  │ supervision   独立审查/交叉审查/返工                 │ │
│  │ permissions   权限/审批中心/审计日志                 │ │
│  │ performance   成本/Token/绩效归因                   │ │
│  ├──────────────────────────────────────────────────┤ │
│  │ agent-core    Agent 身份/能力声明/提示词/记忆        │ │
│  │ agent-adapter 统一接口（connect/execute/stream/     │ │
│  │               interrupt/cancel/capabilities/usage）│ │
│  ├──────────────┬───────────────────┬────────────────┤ │
│  │ model-gateway│ cli-runtime       │ workflow-engine│ │
│  │ LiteLLM SDK  │ Codex SDK/受控子进程│ LangGraph 内核 │ │
│  ├──────────────┴───────────────────┴────────────────┤ │
│  │ SQLAlchemy 2.x → SQLite(WAL) 本地 / PostgreSQL 云端  │ │
│  └──────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────┘
        ▲ 本地模式完整自包含（除模型 API 外呼）
        │ M5 增加：AgentOS Connector ↔ 云端控制平面
```

## 2. 核心架构原则（与立项文档对齐）

1. **前后端分离**——web 只经 REST/WS 与 api 通信
2. **模型供应商可替换**——业务代码只依赖 model-gateway 的统一接口，不出现供应商 SDK
3. **API/CLI 统一 Adapter**——执行层对任务引擎透明【设计，详见 AGENT_ADAPTER.md】
4. **Agent 身份与模型连接分离**——两张表、引用关系，非嵌入
5. **任务状态与 Agent 执行状态分离**——task / task_run / agent_run 三层记录
6. **本地模式不依赖云**——SQLite + 本地文件工作空间即可完整运行
7. **云端不破坏本地**——云端是可选控制平面，本地可拒绝被管
8. **模块化 Monorepo**——packages/ 按域分包，禁止跨域直接 import 内部实现（只走 `__init__` 暴露的接口）
9. **关键任务全持久化**——状态机每次迁移落库
10. **审计留痕**——审批、状态变更、高危操作独立 audit_log 表
11. **断点恢复**——LangGraph checkpointer + 任务状态机双保险
12. **多租户预留**——所有业务表带 `owner_id`，M0–M1 单用户写死默认值

## 3. 关键数据流

### 3.1 任务全生命周期【设计】

```
用户目标 → CEO Agent(澄清/拆解) → 计划待审批 ──用户批准──→ 任务 DAG 落库
  → task-engine 按依赖调度 → agent_run（经 Adapter 执行）
  → 事件流经 WebSocket 推前端 + 落 task_event
  → 成果进入 supervision → 结构化审查报告
  → 通过 → 最终验收（用户或授权人）→ 已完成
  → 退回 → 返工（rework_count+1，超上限→ 执行失败，通知用户）
```

### 3.2 审批流【设计】

```
Agent 发起高危动作请求（API 工具调用 / CLI permission 回调）
  → Adapter 统一翻译为 ApprovalRequest（动作类型/风险等级/参数/证据）
  → task 状态 → 等待权限审批（LangGraph interrupt 挂起 / CLI 子进程挂起）
  → 前端审批台展示 → 用户批准/拒绝/修改参数
  → resume 注入决定 → 继续执行；audit_log 全程留痕
```

### 3.3 成本归因流【设计】

```
每次模型调用 → LiteLLM 返回 usage → completion_cost() 计价
  → usage_record(employee_id, task_run_id, model, tokens, cost_usd)
  → 聚合：员工绩效 / 任务成本 / 公司成本
```

## 4. 包职责边界

| 包 | 职责 | 禁止 |
|---|---|---|
| agent-core | 员工身份、能力声明、提示词渲染、记忆读写 | 直接调模型 |
| model-gateway | LiteLLM 封装、连接测试、重试、回退、计价 | 知道"员工"概念 |
| cli-runtime | 受控子进程、JSONL 事件解析、CLI 能力声明 | 拼接 shell 字符串 |
| workflow-engine | LangGraph 图构建、节点库、checkpointer | 业务规则 |
| organization | 公司/部门/岗位/汇报关系 CRUD 与校验 | 任务逻辑 |
| task-engine | 状态机、DAG 调度、执行记录 | 直接调 Adapter 之外层 |
| supervision | 审查流程、报告模板、返工裁决 | 修改任务状态（只提建议给 task-engine） |
| permissions | 审批策略、风险分级、audit_log | 执行动作 |
| shared | 跨域类型/常量/错误码 | 任何业务逻辑 |

## 5. 部署形态

| 形态 | 组成 | 里程碑 |
|---|---|---|
| Windows 本地 | `python -m apps.api` + `npm run dev`（或打包静态资源由 api 托管） | M0–M4 |
| Docker Compose | api + web + postgres（可选） | M5 |
| 云端 | 控制平面 + AgentOS Connector（本地设备注册接入） | M5，见 LOCAL_CLOUD_ARCHITECTURE.md |

## 6. 已知风险

| 风险 | 缓解 |
|---|---|
| LangGraph interrupt 节点重放语义要求副作用幂等 | 节点设计规范：副作用放独立节点 + 幂等键【已验证-官方文档】 |
| LiteLLM 价格表对国产模型覆盖不全 | completion_cost 失败时降级为"仅记 token"，标记 cost 为 null【设计】 |
| Windows 子进程信号处理差异（CLI 中断） | cli-runtime 用进程组 + Job Object 封装【未验证】 |
| SQLite 并发写 | WAL 模式 + 单写者任务调度器【设计】 |
