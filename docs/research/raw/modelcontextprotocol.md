# modelcontextprotocol（MCP 官方组织）调研笔记（重点：协议定位、传输方式、与 Agent 框架的关系）

> 调研时间：2026-11-05。调研对象：GitHub 组织主页 + specification 文档 + servers 仓库。

## 1. 基本信息

- 组织地址：https://github.com/modelcontextprotocol 【已验证-页面抓取】
- 可访问性：组织主页、servers 仓库、modelcontextprotocol.io 规范架构页均抓取成功【已验证-页面抓取】
- License：servers 仓库——新贡献 Apache-2.0，既有代码 MIT（见其 LICENSE）【官方文档结论：servers README】；规范仓库 license 未逐一核实，未找到
- 最近维护迹象：servers 仓库 2026-10 有多次提交（"chore: version packages" Oct 2026 等）；规范最新版本 URL 为 `specification/2026-07-28`【已验证-页面抓取】
- Star：置顶仓库中 specification 仓库（modelcontextprotocol/modelcontextprotocol）9.6k stars / 1.9k forks；servers 仓库 91.8k stars / 11.9k forks【已验证-页面抓取】
- 治理：开源项目托管于 **The Linux Foundation**（组织 README 原文"hosted by The Linux Foundation"）；servers README 注明"Managed by Anthropic, built together with the community"【官方文档结论】
- 技术栈：规范为文本协议（基于 JSON-RPC）；官方 SDK 覆盖 TypeScript、Python、Java、Kotlin、C#、Go、PHP、Ruby、Rust、Swift 共 10 种语言【已验证-页面抓取】

## 2. 核心架构与目录结构

【官方文档结论：规范架构页】MCP 采用 **client-host-server** 三层架构：

- **Host（宿主）**：容器与协调者——创建管理多个 client 实例、控制连接权限与生命周期、执行安全策略与用户授权、协调 AI/LLM 集成与 sampling、聚合跨 client 上下文
- **Client**：每个 client 与**恰好一个** server 1:1 通信；每个请求自带协议版本与能力声明；双向路由消息；维护 server 间安全边界
- **Server**：通过 MCP primitives 暴露 **resources、tools、prompts**；职责单一、独立运行；可通过 `InputRequiredResult` 反向请求 client 输入（sampling、elicitation、roots）；可以是本地进程或远程服务

协议特性【官方文档结论】：

- 基于 **JSON-RPC**，**无状态**（每个请求自包含，携带协议版本与能力）
- **能力协商**：client 在每请求的 `_meta` 中携带 capabilities；server 通过 `server/discover` 广告能力
- 设计原则：server 极易构建、可组合；**server 看不到完整会话、也看不到其他 server**（会话历史留在 host）；能力渐进式扩展

主要仓库【已验证-页面抓取：组织主页】：

- `modelcontextprotocol`（规范与文档，TS，9.6k stars）
- `servers`（官方参考 server 集合，91.8k stars）
- 10 个语言 SDK 仓库、`ext-auth`（授权扩展）、`inspector`（调试工具）

## 3. Agent 管理方式

不适用（协议层，不管 Agent 生命周期）。MCP 管的是"工具/数据接入"，Agent 由宿主框架（如 Claude Desktop、openai-agents-python）管理【推断+官方文档结论：协议定位】。

## 4. 模型接入方式

不直接接模型。Host 负责 LLM 集成与 sampling 协调；server 可通过 sampling 原语反向请求 host 侧 LLM 补全【官方文档结论：架构页】。

## 5. CLI 接入方式

【官方文档结论：servers README】参考 server 以命令行方式启动：

- TypeScript server：`npx -y @modelcontextprotocol/server-memory`
- Python server：`uvx mcp-server-git`
- Windows 下 npx 需包 `cmd /c`
- 调试工具 MCP Inspector：`npx @modelcontextprotocol/inspector <命令或URL>`

## 6. 多 Agent 协作方式

不适用（MCP 是应用↔工具协议，非 agent↔agent 协议；该定位由 A2A 承担——A2A README 明确"A2A complements MCP"【官方文档结论】）。

## 7. 人工审批/人在回路机制

【官方文档结论：架构页】Host 负责"用户授权决策"（Handles user authorization decisions）与"同意要求"（consent requirements）；server 可通过 elicitation 原语向用户请求输入。即 HITL 由 host 实现，协议提供 elicitation 通道。

## 8. 权限控制机制

【官方文档结论：架构页】安全边界由 host 强制执行：控制 client 连接权限与生命周期、执行安全策略；server 间互相隔离、只能获得必要上下文；server 必须遵守安全约束。另有 `ext-auth` 仓库提供授权扩展【已验证-页面抓取】。servers 仓库明确警告：参考实现**非生产就绪**，开发者需按自身威胁模型实现安全防护【官方文档结论】。

## 9. 运行记录/持久化能力

协议本身不规定持久化【推断】；参考 server 中有 Memory（知识图谱持久记忆）等示例【官方文档结论：servers README】。

## 10. 部署方式

【官方文档结论：servers README】两种标准传输决定部署形态（见下节）；server 以 npm/uv 包分发，由 client 按配置拉起（stdio）或独立部署为 HTTP 服务（Streamable HTTP）。生产 server 目录由官方 **MCP Registry**（registry.modelcontextprotocol.io）承载，servers 仓库仅保留少量参考实现。

## 11. 实际运行条件

- stdio 模式：client 以子进程拉起 server，不开端口【官方文档结论】
- Streamable HTTP 模式：server 独立 HTTP 服务（如 `http://localhost:3001/mcp`），可服务多 client【官方文档结论】
- servers 仓库中所有 server 都支持 stdio，仅 Everything 同时支持 Streamable HTTP【官方文档结论】

## 12. 已知限制

- 参考 server 明确为教学示例、非生产就绪【官方文档结论】
- 大量早期官方 server（GitHub、Slack、Postgres、Puppeteer 等）已归档移交社区（servers-archived）【已验证-页面抓取】
- 协议无状态设计下，长会话状态需 server 自行管理【推断】

## 13. 对 AgentOS 的借鉴价值（重点：传输方式与框架关系）

- **值得借鉴**：
  - **传输双轨制**：stdio（本地子进程、零端口、client 托管生命周期）+ Streamable HTTP（远程、多客户端）——AgentOS 接入本地/远程工具可直接复用这两种模式【官方文档结论】
  - host-client-server 权责划分（host 管权限与同意，server 只看必要上下文）是天然的多租户安全模型
  - 能力协商机制（每请求携带 capabilities）
  - 与 Agent 框架的关系已验证：openai-agents-python 致谢依赖 MCP Python SDK；LiteLLM 提供 MCP 网关；codex/copilot-sdk 均支持 MCP——**MCP 已是事实标准的工具接入协议**【已验证-页面抓取：各项目 README】
- **不适合照搬**：MCP 不解决 agent 间协作（那是 A2A 的领域）；其 Registry/治理体系对 AgentOS 无直接参考价值。
- **需自研**：server 的审核/上架策略（参考实现自身都声明非生产就绪）、企业侧权限细化。

## 14. 分类建议

**E（Agent 互联协议）**——更准确说是"应用↔工具/数据源"互联协议【官方文档结论】。AgentOS 应**作为 MCP host/client 直接兼容**该协议，而非自造工具协议【推断】。
