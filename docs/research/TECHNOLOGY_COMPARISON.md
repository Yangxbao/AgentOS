# AgentOS 技术选型对比报告

> 2026-11-05｜输入：`docs/research/raw/` 12 份调研笔记 + COMPETITOR_ANALYSIS.md
> 本文只做"候选方案对比与倾向"，最终决策见 PROJECT_SELECTION.md

---

## 1. 工作流引擎（核心决策）

候选：LangGraph / CrewAI / Microsoft Agent Framework / openai-agents-python / 纯自研

| 评估维度（权重） | LangGraph | CrewAI | Agent Framework | openai-agents | 纯自研 |
|---|---|---|---|---|---|
| 任务状态机可控性（高） | ★★★★★ 图+条件边显式建模 | ★★☆ 仅 sequential/hierarchical | ★★★★ workflow 图 | ★★★ handoffs 黑盒循环 | ★★★★★ |
| 人工审批原语（高） | ★★★★★ interrupt/resume 语义级 | ★★☆ 任务级 human_input | ★★★★ 内置 HITL | ★★★ 内置 HITL | ★★★★★ 但工作量大 |
| 持久化/断点恢复（高） | ★★★★★ checkpointer 一等公民 | ★★★ 有 checkpointing | ★★★★ checkpoint+time-travel | ★★★ Sessions | 全部自建 |
| 云厂商中立（高） | ★★★★ 模型无关 | ★★★★ 模型无关 | ★★ Azure 深度耦合 | ★★★ OpenAI 概念耦合 | ★★★★★ |
| 角色/组织抽象（中） | ★☆ 无角色概念 | ★★★★★ 原生 role/manager | ★★★ 有 Agent 抽象 | ★★★ 声明式 Agent | ★★★★★ |
| 学习/维护成本（中） | ★★★ 概念多但文档好 | ★★★★★ 上手最快 | ★★★ 双语言复杂 | ★★★★ 轻量 | ★★ 状态机自研易错 |
| 生态风险（中） | ★★★★ MIT、最活跃 | ★★★ 企业功能在商业版、默认遥测 | ★★★ 项目年轻、API 演进中 | ★★ 不接受外部 PR | — |

**倾向**：**LangGraph 作为执行内核，其上自研"角色/任务/审批"概念层**（即 CrewAI 那层，但我们自己的）。
理由：
1. AgentOS 最难的部分是**任务状态机 + 审批暂停恢复 + 监督返工回路**——这正是 LangGraph 最强、其他框架最弱的地方
2. interrupt 的"暂停即持久化、恢复即传值"语义与人工审批中心一一对应
3. 角色抽象恰恰是我们必须自研的（12 个竞品无一满足组织模型），CrewAI 的角色层反而是" borrow 思想、不 borrow 代码"
4. CrewAI 作为**对照组**在 M0 验证一个顺序协作场景，用实测数据对比两者在"任务交接可控性"上的差异，而非仅凭文档定论

**风险备案**：若 LangGraph 实测与 SQLAlchemy/异步模型冲突严重，退回方案为"自研轻量状态机 + openai-agents-python 的 Runner 处理单 Agent 循环"。

---

## 2. 模型接入层

候选：LiteLLM SDK / LiteLLM Proxy / 直连各供应商 SDK / OpenRouter

| 维度 | LiteLLM SDK | LiteLLM Proxy | 直连 SDK | OpenRouter |
|---|---|---|---|---|
| 本地模式零依赖 | ★★★★★ pip 包 | ★★ 需 Postgres | ★★★★ | ★★★★ |
| 供应商覆盖 | ★★★★★ 100+（含国内） | 同左 | ★☆ 每家单独接 | ★★★★ |
| 费用统计 | ★★★★★ 价格表+completion_cost | ★★★★★ 含预算限额 | ★☆ 自建 | ★★★ |
| 故障回退 | ★★★★ fallbacks 参数 | ★★★★★ | ★☆ | ★★★ |
| 凭证隔离 | ★★★ 应用层管理 | ★★★★★ 虚拟密钥 | ★★ | ★★ |

**倾向**：M0–M2 用 **LiteLLM Python SDK**（本地模式零额外服务）；M5 云端模式评估 Proxy（虚拟密钥体系正好支撑多租户成本隔离）。主备模型回退用 LiteLLM `fallbacks` 机制 + 自研员工级主备配置映射。

---

## 3. CLI Agent 接入

候选：Codex / Copilot SDK / Claude Code / Gemini CLI / 自定义 CLI

**已验证结论**（详见 codex.md / copilot-sdk.md）：
- Codex：`codex exec --json` headless 模式 + 官方 TS/Python SDK，能力完整（流式、结构化输出、resume、token usage）✅
- Copilot SDK：六语言官方 SDK + JSON-RPC + permission handler，已 GA ✅
- Claude Code / Gemini CLI：M0 不验证（无对应账号/安装授权），架构上以同一 Adapter 接口预留，标记【未验证】

**倾向**：M0 验证 **Codex**（有官方 Python SDK、headless 能力文档最完整）作为 CLI 接入的第一个实例；Adapter 接口按 Copilot SDK 的 permission handler 模式设计审批挂点。**能力声明矩阵**必须落地（流式/中断/结构化输出/工具调用/文件操作/审批/会话恢复/费用统计逐项声明），因为两个工具能力差异已被实证。

---

## 4. 后端框架与数据层

| 项 | 选择 | 理由 |
|---|---|---|
| Web 框架 | **FastAPI** | 与 HALF 同栈已被同类产品验证；Pydantic 原生；异步生态好 |
| ORM | **SQLAlchemy 2.x** | SQLite/PostgreSQL 双后端切换成本低 |
| 本地库 | **SQLite**（WAL 模式） | 本地模式零依赖；任务事件流足够 |
| 云端库 | PostgreSQL | M5 再启用，schema 设计时就按双后端兼容（不用 SQLite 专有特性） |
| 事件推送 | **WebSocket**（FastAPI 原生） | 任务状态/会议消息实时推送 |
| Redis | **M0 不引入** | 遵守"不过度设计"；M2 并行任务量大后再评估 |

## 5. 前端

| 项 | 选择 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript + Vite | 团队熟悉度最高组合，HALF/Cebus 同栈验证 |
| UI 库 | Tailwind CSS + shadcn/ui | 立项文档已指定 |
| 组织图/任务 DAG | **React Flow** | HALF 已用其做 DAG 可视化验证可行 |
| 状态 | Zustand（轻量） | 避免 Redux 过重 |

## 6. 互联协议

- **MCP**：作为 host 兼容（工具接入），M2 引入官方 Python SDK
- **A2A**：M6 再做；内部 Agent 注册表现在就按 Agent Card 思想设计（能力自描述）

## 7. 许可对比（MIT vs Apache-2.0）——用户已确认 MIT

| 维度 | MIT | Apache-2.0 |
|---|---|---|
| 宽松度 | 最宽松 | 宽松 |
| 专利授权 | 无明确条款 | 有明确专利授权与反诉终止条款 |
| 商标保护 | 无 | 有 |
| 与竞品生态一致性 | LangGraph/CrewAI/LiteLLM/Copilot SDK 均 MIT | AgentTeams/HALF/Codex/A2A 均 Apache-2.0 |
| 贡献者门槛 | 最低 | 略高（专利条款需理解） |

**结论**：用户已拍板 **MIT**。补充理由：AgentOS 计划大量借鉴 MIT 系项目（LangGraph/CrewAI/LiteLLM）的设计并保持依赖兼容；作为基础设施型开源项目，MIT 采用率最高。专利风险对该项目体量可接受。
