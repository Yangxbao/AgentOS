# AgentTeams 调研笔记

- 仓库：<https://github.com/agentscope-ai/AgentTeams>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页、`docs/design/architecture.md`（raw 抓取）

## 1. 基本信息

- 仓库地址：<https://github.com/agentscope-ai/AgentTeams>【已验证-页面抓取】
- 可访问性：可访问，页面正常【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含 Star 数）
- License：Apache License 2.0【已验证-页面抓取】
- 最近维护迹象：最近提交 2026-11-04（`feat(project-management): create-project.sh --team invites the whole Team (#1429)`）；最新 Release v1.2.5（2026-10-16）【已验证-页面抓取】——活跃维护中
- 技术栈：多语言——controller 为 Go（K8s operator 模式）；Manager/Worker 运行时分 Node.js（OpenClaw）与 Python（QwenPaw / Hermes / CoPaw）；基础设施含 Higress AI 网关、Tuwunel（Matrix homeserver）、MinIO、Element Web；部署脚本为 Shell/PowerShell/Helm【已验证-页面抓取】

## 2. 核心架构与目录结构

**架构**【官方文档结论，docs/design/architecture.md】：
- v1.1.0 起采用**多容器架构**：基础设施（Higress、Tuwunel、MinIO、Element Web）集中在 `agentteams-controller`（本地为 embedded 单容器，K8s 为独立 workload）；Manager/Worker 为轻量容器，按需创建。
- 三层通信：人/Manager/Worker 之间用 **Matrix 协议**（房间即协作空间）；Agent→LLM/MCP 走 **Higress 网关**（key-auth 按身份隔离凭证）；共享文件存 **MinIO**（Worker 无状态，可替换）。
- 声明式资源：K8s CRD（`agentteams.io/v1beta1`）定义 Worker / Manager / Team / Human，由 Go controller reconcile。

顶层目录【已验证-页面抓取】：

```
agentteams-controller/  manager/  worker/  helm/agentteams/  install/
openclaw-base/  qwenpaw/  hermes/  deepseek-harness/  openhuman/
plugins/  shared/  scripts/  docs/  blog/  changelog/  test/e2e/  tests/
```

## 3. Agent 管理方式

- Agent = 容器。Worker 按 CR 声明（`spec.runtime`、model、image、skills、MCP servers、channelPolicy、state）；Manager 同理【官方文档结论】。
- 支持 5 种 Worker 运行时：openclaw（默认，Node）、copaw（Python，兼容保留）、qwenpaw（Python）、hermes（Python）、deepseek-harness（实验，Node）【官方文档结论】。
- 技能系统：Skill = `SKILL.md` + 可选 `scripts/`、`references/`。Manager 内置 16 个技能（任务管理、团队管理、模型切换、MCP 管理等），Worker/Team Leader 各有内置技能集，可按需分发【官方文档结论】。

## 4. 模型接入方式

- **统一走 Higress AI 网关**：LLM 流量为 OpenAI 兼容路由，按 per-identity consumer key-auth 隔离；Worker 只持消费 token，不接触真实密钥【官方文档结论】。
- 具体支持哪些模型供应商：抓取内容未列出供应商清单（网关为 OpenAI 兼容协议，理论上任何兼容端点可用）【推断】。

## 5. CLI 接入方式

- 内置 **`agt` CLI**（由 controller 构建，打入 Manager/Worker/embedded 镜像），对 controller REST API（:8090）操作 CR 资源，如 `agt get managers default`【官方文档结论】。

## 6. 多 Agent 协作方式

- **Manager-Workers 编排**：Manager 协调多个 Worker；可选 **Team（Leader + Workers）** 结构，Team Leader 是可见的 AI 协调者【官方文档结论】。
- 协作载体是 Matrix 房间：任务分配、进度、干预共享同一时间线；MinIO 共享文件系统降低多 Agent 协作的 token 消耗【已验证-页面抓取】。

## 7. 人工审批 / HITL

- 核心卖点：**Human 是一等资源（Human CRD）**，通过 Matrix 房间与 Manager/Worker 同处一室，全程可见、可干预（"transparent, human-in-the-loop task coordination via Matrix rooms"）【已验证-页面抓取】。
- Human CRD 含 display name、email、`permissionLevel`、可访问的 teams/workers【官方文档结论】。

## 8. 权限控制机制

- Higress consumer key-auth：按 Manager/Worker 身份隔离 LLM、存储、MCP 路由【官方文档结论】。
- CRD 层面：Worker `accessEntries`（云凭证范围）、`channelPolicy`；Human `permissionLevel`【官方文档结论】。
- 密钥由 operator/installer 生成或注入；云部署可用 credential-provider sidecar（STS 范围化）【官方文档结论】。

## 9. 运行记录 / 持久化

- Worker 无状态，durable state（工作区 `agents/<name>/`、共享任务树 `shared/tasks/`、Manager 路径）存 MinIO 对象存储【官方文档结论】。
- Matrix 房间时间线本身即审计记录【推断，基于"一切可见"的设计】。
- 集成 AgentLoop 提供可观测性、评估、资产管理【已验证-页面抓取】。

## 10. 部署方式

- 本地单机：`install/agentteams-install.sh`（curl | bash），embedded controller 容器 + Docker/Podman API 创建 Manager/Worker 容器【官方文档结论】。
- Kubernetes：Helm chart（`helm/agentteams`），要求 K8s 1.24+；各组件独立 Pod，CR 驱动创建 Manager/Worker【已验证-页面抓取】。

## 11. 实际运行条件

- Docker 或 Podman（本地）；Kubernetes 1.24+（Helm 部署）【已验证-页面抓取】。
- openclaw-base 镜像：Ubuntu 24.04 + Node.js 24【官方文档结论】。
- Python 运行时（qwenpaw/hermes）具体版本要求：未找到。

## 12. 已知限制

- 部署重：即使本地模式也需要 embedded controller（Higress + Tuwunel + MinIO + Element + supervisord），组件多【推断】。
- OpenHuman 后端在 controller/Helm 中已有配置，但 CRD 尚不接受 `spec.runtime: openhuman`；chart 无 `worker.defaultImage.qwenpaw`，需显式指定 `spec.image`【官方文档结论】。
- 依赖 Matrix 生态（Tuwunel 为 conduwuit 家族 homeserver），社区成熟度有限【推断】。
- deepseek-harness 为实验性运行时，pinned 到 DSH release candidate【官方文档结论】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **Agent = 容器 + CRD 声明式管理**：Worker/Manager/Team/Human 四类 CR + controller reconcile，生命周期（Running/Sleeping/Stopped）标准化——AgentOS 若走云原生路线可直接参考其 CRD 设计。
- **AI 网关集中管凭证**：Worker 只持消费 token、不接触真实密钥，按身份路由 LLM/MCP——权限与成本控制的干净方案。
- **Matrix 房间作为 HITL 与审计的统一载体**：人、Manager、Worker 同一时间线，天然透明可干预。
- **共享对象存储承载 Agent 产物**，Worker 无状态可替换。
- **Skill = Markdown 文件**的技能分发机制（SKILL.md + scripts），轻量且对 Agent 友好。

**不适合照搬：**
- 整套基础设施（Higress/Tuwunel/MinIO/Element）对中小团队过重；Matrix 协议栈学习成本高。
- 多运行时并存（5 种 Worker runtime）带来大量兼容代码。

**需自研：**
- 若 AgentOS 面向单机/轻量场景，需自研精简的控制平面与本地审批通道，而非引入 Matrix。

## 14. 分类建议

- **A 完整产品**（主）：自带 UI（Element Web）、IM、网关、存储、Helm 部署，是开箱即用的多 Agent 协作平台。
- **B Agent 工作流框架**（次）：Manager-Workers/Team 编排模型可作为框架使用，但其重心在"平台"而非"库"。
- 理由：它不实现 Agent 逻辑本身而是编排 Agent 容器，且捆绑了完整的基础设施与前端，整体形态是产品级运行时平台【推断】。
