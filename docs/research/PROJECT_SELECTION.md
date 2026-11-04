# AgentOS 项目选型决策书

> 2026-11-05｜依据：COMPETITOR_ANALYSIS.md + TECHNOLOGY_COMPARISON.md
> 状态说明：✅ 已定案（调研支撑）｜🧪 已定案但需 M0 实测确认｜⏳ 后置决策

---

## 1. 最终技术栈（M0 定案）

### 执行内核与接入层

| 组件 | 决策 | 状态 | 依据 |
|---|---|---|---|
| 工作流引擎 | **LangGraph（Python）** | 🧪 | 唯一具备 interrupt+checkpoint+resume 审批语义级原语的框架；任务状态机可控性最强；MIT、模型无关。M0 需实测：与 FastAPI 异步模型集成、SqliteSaver 持久化、interrupt 恢复链路 |
| 角色对照验证 | CrewAI | 🧪 | M0 用同一双 Agent 顺序任务做对照实测，验证"自研概念层 + LangGraph 内核"优于直接用 CrewAI |
| 模型网关 | **LiteLLM（Python SDK 形态）** | 🧪 | 100+ 供应商统一 OpenAI 格式；价格表 + completion_cost 覆盖成本中心需求；本地零依赖。M0 需实测 DeepSeek 真实调用 |
| CLI 接入（首个实例） | **Codex（codex exec + 官方 Python SDK）** | 🧪 | headless JSONL 事件流 + 沙箱三档 + 官方 SDK，全部官方允许方式。M0 需实测（需用户安装 Codex 并授权） |
| 工具协议 | 兼容 MCP（作为 host） | ✅（设计定案，M2 实施） | 已是事实标准，不自造 |
| Agent 互联 | 兼容 A2A | ✅（设计定案，M6 实施） | Agent Card 思想现在就用于内部能力声明 |

### 应用层

| 组件 | 决策 | 状态 |
|---|---|---|
| 后端 | Python 3.11+ / FastAPI / Pydantic v2 / SQLAlchemy 2.x | ✅ |
| 数据库 | 本地 SQLite（WAL）／云端 PostgreSQL，schema 双后端兼容设计 | ✅ |
| 前端 | React 18 + TypeScript + Vite + Tailwind + shadcn/ui + React Flow + Zustand | ✅ |
| 实时通信 | WebSocket（FastAPI 原生） | ✅ |
| 许可证 | **MIT**（用户已确认） | ✅ |
| 部署 | Windows 本地直跑 → Docker Compose（M5 云端） | ✅ |

### 明确不采用

| 方案 | 原因 |
|---|---|
| fork 任何竞品改名 | 无一覆盖组织/权限/审批/监督模型；立项文档禁止 |
| MS Agent Framework | Azure 深度耦合，违背"供应商可替换"原则（保留为替代方案研究档案） |
| CrewAI 作为主框架 | 审批/权限为零、遥测默认开启、编排模型仅两种（保留为对照组） |
| LiteLLM Proxy | M0 阶段引入 Postgres 违背本地零依赖原则（M5 再评估） |
| Redis / K8s / 消息队列 | 过度设计，里程碑未要求 |
| AgentTeams 式容器基础设施 | 违背 Windows 本地轻量运行约束 |

## 2. 分层架构决策（自研 vs 复用的边界）

```
┌─────────────────────────────────────────────┐
│  React 前端（组织图/任务/审批/会议 UI）        │ ← 全自研
├─────────────────────────────────────────────┤
│  组织模型 / 任务状态机 / 审批中心 / 监督闭环    │ ← 全自研（产品本体，无现成方案）
│  成本绩效 / 权限 / 审计                        │
├─────────────────────────────────────────────┤
│  Agent Adapter 统一接口 + 能力声明             │ ← 自研抽象层
├──────────────┬───────────────┬──────────────┤
│ API Adapter  │ CLI Adapter   │ MCP host     │
│ (LiteLLM SDK)│ (Codex SDK…)  │ (官方 SDK)   │ ← 复用
├──────────────┴───────────────┴──────────────┤
│  LangGraph 执行内核（状态机/中断/恢复）         │ ← 复用 + 自研概念层
├─────────────────────────────────────────────┤
│  SQLAlchemy / SQLite·PostgreSQL              │ ← 复用
└─────────────────────────────────────────────┘
```

**核心原则**：复用层全在"管道"（模型调用、CLI 驱动、图执行），自研层全在"治理"（组织、任务、审批、监督、成本）。这正是 12 个竞品都没有做的部分，也是 AgentOS 的产品本体。

## 3. M0 实测验证清单（选型生效的前提）

| # | 验证项 | 通过标准 | 依赖 |
|---|--------|---------|------|
| V1 | LiteLLM → DeepSeek 真实调用 | 返回内容 + token 用量 + 费用可计算 | 用户 DeepSeek Key |
| V2 | 第二个供应商调用 | 任一第二供应商成功，或如实标记"缺 Key 未验证" | 用户决定 |
| V3 | AgentAdapter 接口落地 | API 型 Adapter 通过接口完成 V1 | 无 |
| V4 | 双 Agent 顺序协作 | 研究员→审查员交接真实任务，产出结构化交接物 | V1 |
| V5 | LangGraph interrupt 审批暂停/恢复 | 任务在审批点挂起，外部 resume 后继续 | V1 |
| V6 | 执行记录持久化 | SQLite 落库，进程重启后记录仍在；失败任务有错误记录 | 无 |
| V7 | Codex CLI headless | `codex exec --json` 完成真实任务并解析事件流（**需用户授权安装**） | 用户授权 |
| V8 | CrewAI 对照 | 同任务跑通，输出对比结论 | V1 |

未通过的项在 M0_TEST_REPORT.md 中如实标记【未完成/被阻塞】，不降级验收标准。

## 4. 后置决策（现在不定）

- ⏳ LiteLLM Proxy 是否上云端（M5）
- ⏳ Redis 引入时机（M2 视并行任务实测）
- ⏳ A2A server 适配层形态（M6）
- ⏳ AgentOS Connector 加密方案细节（M5，安全模型文档先定信任边界）
