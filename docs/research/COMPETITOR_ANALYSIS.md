# AgentOS 竞品分析报告

> 调研时间：2026-11-05｜调研人：AgentOS CTO（AI）
> 数据来源：12 个 GitHub 项目/组织的实地抓取笔记，原始证据见 `docs/research/raw/*.md`
> 来源标注约定：【已验证】= 实际抓取到页面内容；【官方文档】= 官方文档/README 明确陈述；【推断】= 基于证据推断；【未找到】= 公开页面未披露，**本文不编造任何 Star 数、日期或功能**

---

## 1. 总览与分类

| # | 项目 | 分类 | 可访问 | License | 维护状态 | 一句话定位 |
|---|------|------|--------|---------|----------|-----------|
| 1 | agentscope-ai/AgentTeams | A 完整产品 | ✅ | Apache-2.0 | 活跃（2026-11-04 有提交，v1.2.5） | K8s 容器化多 Agent 协作平台，Matrix 房间做人机协同 |
| 2 | keting/half | A 完整产品 | ✅ | Apache-2.0 | 早期迭代（v0.2.1，有 CI） | 人工派发 + Git 轮询的 CLI Agent 任务管理平台 |
| 3 | cebus-ai/cebus | D CLI 工具（带 B 特征） | ✅ | MIT | ⚠️ 存疑（约 8 个月无提交） | LangGraph(JS) 驱动的多模型终端群聊 |
| 4 | langchain-ai/langgraph | B 工作流框架 | ✅ | MIT | 高度活跃（7,268 提交） | 低层图编排框架 + 运行时，checkpoint/interrupt 一等公民 |
| 5 | crewAIInc/crewAI | B 工作流框架 | ✅ | MIT | 活跃 | role/goal/backstory 角色协作框架，Crews + Flows 双层 |
| 6 | microsoft/agent-framework | B 工作流框架 | ✅ | 未找到（不采信猜测） | 高度活跃 | Semantic Kernel + AutoGen 后继，Agent/Workflow 二元 |
| 7 | openai/openai-agents-python | B 工作流框架 | ✅ | MIT | 活跃 | 轻量多 Agent SDK：Agent/Runner/Handoffs/Guardrails |
| 8 | BerriAI/litellm | C 模型网关 | ✅ | MIT（含企业版商业许可目录） | 极活跃（55,859 提交） | 统一 OpenAI 格式 API 的 AI Gateway + Python SDK |
| 9 | modelcontextprotocol | E 互联协议（工具侧） | ✅ | Apache-2.0/MIT 混合 | 活跃（Linux Foundation） | 应用↔工具/数据源协议，事实标准 |
| 10 | a2aproject/A2A | E 互联协议（Agent 侧） | ✅ | Apache-2.0 | 活跃（v1.0 RC 重构期） | Agent↔Agent 不透明协作协议 |
| 11 | openai/codex | D CLI 执行工具 | ✅ | Apache-2.0 | 极活跃（133.2k stars【已验证】） | 终端编码 Agent，headless exec + JSONL + 官方 SDK |
| 12 | github/copilot-sdk | D CLI 工具（SDK 化内核） | ✅ | MIT | 活跃（已 GA） | JSON-RPC 驱动 Copilot CLI runtime 的六语言 SDK |

**分类结论**：
- **A 完整产品（2 个）**：AgentTeams、HALF —— 与 AgentOS 形态最接近，是主要对标对象
- **B 工作流框架（4 个）**：LangGraph、CrewAI、Agent Framework、openai-agents-python —— 是 AgentOS 工作流引擎的候选
- **C 模型网关（1 个）**：LiteLLM —— 模型接入层的直接候选
- **D CLI 执行工具（3 个）**：Cebus、Codex、Copilot SDK —— CLI Agent 接入的参照与接入对象
- **E 互联协议（2 个）**：MCP、A2A —— 应当**兼容**而非自造的标准

---

## 2. 两个完整产品的深度对比（AgentOS 的直接对标）

### 2.1 AgentTeams（agentscope-ai）

- **架构**：K8s CRD（Worker/Manager/Team/Human 四类资源）+ Go controller；通信走 Matrix 协议（房间即协作空间）；LLM 流量走 Higress AI 网关按身份隔离凭证；产物存 MinIO【官方文档】
- **最大亮点**：**Human 是一等资源（Human CRD）**——人与 Agent 同处一个 Matrix 房间，全程可见可干预；Worker 只持消费 token 不接触真实密钥【已验证】
- **对 AgentOS 的价值**：Agent = 声明式资源的思路、网关集中管凭证、Skill = Markdown 文件的分发机制都值得借鉴
- **致命问题（对 AgentOS 而言）**：基础设施过重（Higress + Tuwunel + MinIO + Element + supervisord），即使本地模式也要跑整套容器栈；AgentOS 承诺"Windows 本地可跑、不过度设计"，**不能照搬**

### 2.2 HALF（keting/half）

- **架构**：FastAPI + SQLite 存系统状态，**Git 协作仓库存协同产物**；后端**刻意不主动调用任何 Agent**——人生成 prompt、手工粘贴给 CLI Agent、Agent 写回 `result.json` 原子哨兵、后端轮询识别完成【官方文档】
- **最大亮点**：**"Git 仓库即协作总线"**——CLI Agent 原生会读写 git，零集成成本且自带版本审计；Owner 级隔离 + 公共/私有 Agent 池的权限模型设计细致；任务事件流（TaskEvent）与审计日志分离
- **刻意不做的事**：不做接口逆向、不调 Agent 平台非公开接口——与 AgentOS 安全红线第 8、10 条完全一致【官方文档】
- **致命问题**：纯人工派发，无法自动化闭环；15-30 秒轮询延迟。AgentOS 的自动化执行层必须自研
- **特别注意**：该项目技术栈（FastAPI + SQLAlchemy + SQLite + React + React Flow + Docker Compose）与 AgentOS 拟定栈**几乎完全一致**，证明该栈在此类产品上已被验证可行

### 2.3 Cebus

- 多模型终端群聊工具，LangGraph(JS) 编排，支持 `@昵称` 寻址、Team Leader 分阶段协作（clarify→plan→deliberate→execute→review→synthesize）
- **可直接借用的设计**：角色定义 = `*.agent.md`（YAML frontmatter + Markdown）；prompt 外置为 `.cebus/prompts/*.md` 运行时可编辑；模型成本分级（premium/middle/budget/local）+ 上下文溢出自动降级
- **风险**：约 8 个月无提交，维护存疑；本质是群聊客户端，正是 AgentOS 立项文档明确反对的"看起来很热闹"形态

---

## 3. 四个工作流框架的核心差异

| 维度 | LangGraph | CrewAI | MS Agent Framework | openai-agents-python |
|------|-----------|--------|--------------------|-----------------------|
| 抽象层级 | 低层（图原语） | 高层（角色扮演） | 中层（Agent + Workflow 二元） | 中层（声明式 Agent） |
| 协作模型 | 自建（supervisor/handoff 模式） | Sequential + Hierarchical | 图式 workflow（sequential/concurrent/handoff/group chat） | Handoffs + agents-as-tools |
| HITL | **`interrupt()` + checkpoint + resume 三件套**，语义最干净 | `human_input=True` 任务级 | workflow 内置 HITL + 工具审批 | 内置 HITL + Guardrails |
| 持久化 | **checkpointer 一等公民**，thread_id 即游标 | checkpointing（细节少） | checkpoint + time-travel | Sessions（内存/SQLAlchemy/Redis） |
| 权限 | 无（框架层） | 无（企业能力在商业版） | 中间件管道挂点 | Guardrails + 沙箱 |
| 语言 | Python + JS | Python | Python + .NET（Go preview） | Python |
| 生态耦合 | LangSmith（商业）可选 | CrewAI AMP（商业）可选 | **深度绑定 Azure/Foundry** | OpenAI tracing 平台 |
| Python 要求 | 未找到下限 | >=3.10,<3.14 | 3.11–3.14 | 3.10+ |

**关键洞察**：
1. **没有任何一个框架提供 AgentOS 需要的权限/审批/审计/组织模型**——这部分必然要自研，框架只是执行内核
2. LangGraph 的 `interrupt()` 三件套是唯一把"暂停-持久化-恢复传值"做成语义级原语的方案，与 AgentOS "人工审批中心 + 任务状态机" 的需求契合度最高
3. CrewAI 的 role/goal/backstory 与 Hierarchical manager 模式可直接映射 AgentOS 的"员工/CEO"概念，但其审批/权限为零，且遥测默认开启
4. MS Agent Framework 的中间件管道是权限拦截的最佳挂点设计，但 Azure 耦合与 AgentOS"模型供应商可替换"原则冲突
5. openai-agents-python 的 Guardrails 思想和 Sessions 抽象值得借鉴，但不接受外部 PR 是生态风险

---

## 4. 模型网关与 CLI 工具的结论

### LiteLLM（C 类，唯一候选）

- 统一 OpenAI 格式 API，`<prefix>/<model>` 寻址，**100+ 供应商**（含 DeepSeek、通义、火山、智谱等国内厂商）【官方文档，已验证供应商列表页】
- **费用追踪是杀手锏**：模型价格表 + `completion_cost()`，按 key/user/team 统计 USD 花费，`max_budget`/`tpm`/`rpm` 限额——正好覆盖 AgentOS "成本与绩效中心"的需求
- 两种用法：Python SDK（库）或 Proxy（独立网关服务，需 Postgres）
- **AgentOS 决策**：M0 阶段用 **Python SDK 形态**（轻量、本地模式无额外依赖）；云端模式再评估是否上 Proxy

### CLI 工具接入可行性（D 类）

| 工具 | 官方程序化接入 | 结构化输出 | 审批机制 | 认证 |
|------|---------------|-----------|---------|------|
| Codex | `codex exec` headless + `--json` JSONL 事件流 + 官方 TS/Python SDK（本质是 spawn 子进程） | `--output-schema` 强制 JSON Schema | 沙箱三档 + 审批策略矩阵（exec 模式不能交互审批） | ChatGPT 账号 / API key |
| Copilot SDK | 六语言 SDK 经 JSON-RPC 驱动 CLI server mode | elicitation schema | **每次工具调用都经宿主 permission handler** | GitHub OAuth / 环境变量 / BYOK |

**关键结论**：
1. 两者都提供**官方允许的程序化接入**，满足 AgentOS "不得逆向、不得绕过认证" 的红线
2. Codex 的 `codex exec --json` 是 CLI 接入的黄金范式：stderr 进度 + stdout 结果 + JSONL 事件流 + token usage
3. Copilot SDK 的 **permission handler 回调**模式与 AgentOS 统一审批中心天然契合
4. 两者能力差异很大（Codex 有会话 resume，Copilot 有 BYOK）——证实 AgentOS 必须做**能力声明机制**，不能假设 CLI 能力一致

### 协议（E 类）

- **MCP = agent↔工具**：host-client-server 三层，stdio + Streamable HTTP 双传输，已是事实标准（Codex/Copilot/LiteLLM/openai-agents 均支持）。AgentOS 应**作为 MCP host 兼容**，不自造工具协议
- **A2A = agent↔agent**：Agent Card 能力发现 + Task 长时生命周期（含断线 Resubscribe）+ "不透明协作"原则。Agent Card 可直接启发 AgentOS 内部 Agent 注册表设计；完整 A2A 支持放到 M6

---

## 5. 借鉴 / 不照搬 / 自研 总结

### 直接借鉴（进入 AgentOS 设计）

| 设计 | 来源 | 用在哪 |
|------|------|--------|
| `interrupt()` + checkpoint + `Command(resume)` 审批语义 | LangGraph | 人工审批中心、任务暂停恢复 |
| role/goal/backstory 角色三要素 | CrewAI | AI 员工定义 |
| `*.agent.md`（YAML frontmatter + Markdown）员工定义文件 | Cebus | 员工配置导入导出 |
| prompt 外置、运行时可编辑 | Cebus | 员工提示词管理 |
| `<prefix>/<model>` 统一寻址 + 价格表费用核算 | LiteLLM | 多模型接入中心、成本中心 |
| `codex exec --json` JSONL 事件流范式 | Codex | CLI Runtime 事件协议 |
| permission handler 回调（每次工具调用经宿主审批） | Copilot SDK | 人工审批中心与 CLI 的接口 |
| 沙箱三档（read-only / workspace-write / danger-full-access） | Codex | CLI 执行权限分级 |
| Human 作为一等资源 | AgentTeams | 用户在组织架构中的位置 |
| Git 仓库即协作产物总线 + `result.json` 原子哨兵 | HALF | 共享工作空间（代码类任务） |
| TaskEvent 事件流与审计日志分离 | HALF | 运行记录持久化 |
| 中间件管道作为权限/审计统一挂点 | MS Agent Framework | Agent 执行拦截层 |
| Agent Card 能力自描述 | A2A | Agent 能力声明机制 |
| MCP host-client-server 权责划分 | MCP | 工具接入安全模型 |
| 虚拟密钥 + 预算 + tpm/rpm 限额 | LiteLLM | 云端模式的多租户成本控制 |
| Team Leader 分阶段流程（clarify→plan→deliberate→execute→review→synthesize） | Cebus | CEO Agent 的任务编排 prompt 流程 |

### 明确不照搬

- AgentTeams 的整套容器基础设施（Higress/Matrix/MinIO）——违背"Windows 本地轻量可跑"
- HALF 的纯人工派发——AgentOS 要自动化闭环
- Cebus 的群聊中心主义——立项文档明确反对"无限循环群聊"
- CrewAI 的默认遥测、重复工具调用 5 次硬终止不可配置
- MS Agent Framework 的 Azure 凭证体系、双语言工程
- LiteLLM 的完整 Proxy + Admin UI（M0 只用 SDK 形态）
- 任何"fork 改名"——12 个项目无一覆盖 AgentOS 的组织/权限/审批/监督模型，自研部分才是产品本体

### 必须自研（无现成方案）

1. **公司/部门/岗位/上下级组织模型**（12 个项目中无任何一个有）
2. **任务状态机 + 独立审查 + 自动返工的监督闭环**（LangGraph 只给原语）
3. **统一审批中心**（跨 API Agent 与 CLI Agent 的审批路由）
4. **Agent Adapter 统一接口 + 能力声明**（API/CLI 双接入的抽象层）
5. **员工-模型解耦的多模型切换**（同一员工主备模型、同一模型多员工）
6. **成本与绩效的按员工归因**（LiteLLM 按 key 统计 → 映射到员工）
7. **AgentOS Connector 本地-云端协同**
8. **会议室的受控召开/结束/成果转化**（调度系统驱动，非无限群聊）

---

## 6. 调研可信度声明

- 12 个项目全部可访问，无"无法访问"项
- Cebus 的 raw README 抓取 404，改用页面抓取补齐，已在笔记注明
- developers.openai.com（Codex 文档站）本环境 403，相关内容经 WebSearch + 仓库内文档交叉补齐，已注明
- 除特别标注外，Star 数未在抓取内容中显示的项目一律写"未找到"，未做任何估算
