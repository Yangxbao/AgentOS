# a2aproject/A2A 调研笔记（重点：协议定位、传输方式、与 Agent 框架的关系）

> 调研时间：2026-11-05。

## 1. 基本信息

- 仓库地址：https://github.com/a2aproject/A2A 【已验证-页面抓取】
- 可访问性：GitHub 主页与 README raw（main）均抓取成功【已验证-页面抓取】
- License：**Apache License 2.0**（README About 段与徽章明确）【官方文档结论】
- 最近维护迹象：仓库文件列表显示 2026 年内多次提交（Oct 2026 多处）；有一个大型规范重构 commit（`b078419`，将规范重构为"传输无关的应用协议 + 各传输映射"，作为 v1.0 Release Candidate 基线，Release-As: 1.0）【已验证-页面抓取】。Star 数：未找到（抓取页面未显示数字）
- 治理：Linux Foundation 旗下开源项目，由 Google 贡献【官方文档结论：README About】
- 技术栈：协议规范以 **protobuf（a2a.proto）为数据模型的唯一权威源**，`a2a.json` 由其生成【已验证-页面抓取：重构 commit 说明】；官方 SDK：Python（`a2a-sdk`）、Go、JS（`@a2a-js/sdk`）、Java、.NET（`A2A` NuGet）、Rust（`a2a-lf`）
- 文档站：https://a2a-protocol.org

## 2. 核心架构与目录结构

【官方文档结论：README】协议定位——**让不同框架、不同公司、不同服务器上的"不透明"（opaque）agent 应用以 agent 身份（而非工具身份）互相通信协作**。核心能力：

- 互相发现能力（Agent Cards）
- 协商交互模态（text、forms、media）
- 安全协作长时任务
- 不暴露内部状态、记忆、工具

规范结构（v1.0 RC 重构后）【已验证-页面抓取：commit 说明】：

- **A2A Operations**：与传输无关的操作定义
- **Protocol Data Model**：以 protobuf 为权威源，其余序列化格式由其派生
- **Protocol Bindings（原 transports）**：JSON-RPC / gRPC / HTTP+JSON(REST) 三种绑定各自独立成章
- 新增：Requirements Language、Capability Validation、错误处理、Extensions、Versioning、Agent Card Signing、IANA Considerations、Security Considerations 等章节

## 3. Agent 管理方式

【官方文档结论】协议层只规定 agent 如何被发现与被调用，不管理 agent 生命周期：

- **Agent Card**：描述能力与连接信息的发现文档
- 规划中的增强：`QuerySkill()` 动态技能查询、AgentCard 内携带授权方案与可选凭据【官方文档结论：README "What's next"】

## 4. 模型接入方式

不适用（agent 间协议，不涉及模型接入）【推断】。

## 5. CLI 接入方式

未找到（协议项目，无 CLI 产品；接入通过各语言 SDK）【已验证-页面抓取】。

## 6. 多 Agent 协作方式（重点）

【官方文档结论：README】这是 A2A 的核心使命：

- **协作模式**：支持同步请求/响应、**SSE 流式**、**异步推送通知（push notifications）**三种交互
- **数据交换**：文本、文件、结构化 JSON（富数据交换）
- **编排样例**：官方课程展示顺序/层级工作流编排、跨框架（Google ADK、LangGraph、BeeAI）多 agent 系统
- **不透明性（Preserve Opacity）**：agent 协作无需共享内部记忆、专有逻辑或工具实现——这是与"agent 当工具用"的本质区别【官方文档结论】

## 7. 人工审批/人在回路机制

【推断+官方文档结论】协议支持"协商交互模态（text, forms, media）"，forms 模态可用于人工表单确认；规划中有"任务内动态 UX 协商"。无独立的审批原语被明确描述，未找到更多细节。

## 8. 权限控制机制

【官方文档结论】设计时考虑企业级安全：authentication、observability；v1.0 RC 引入 **Agent Card Signing** 与 Security Considerations 章节【已验证-页面抓取】。授权方案放入 AgentCard 是"下一步规划"而非现状【官方文档结论：What's next】。

## 9. 运行记录/持久化能力

【官方文档结论：commit 说明】协议定义 **Task 生命周期**（长时任务、Cancel Task、Resubscribe to Task 等操作），支持断线重订阅；持久化实现交由各 SDK/服务端，协议只规定语义。

## 10. 部署方式

【官方文档结论】agent 作为 HTTP(S) 服务部署并暴露 Agent Card；客户端经 SDK 连接。标准化通信：**JSON-RPC 2.0 over HTTP(S)**；v1.0 起另有 gRPC 与 HTTP/JSON/REST 绑定【已验证-页面抓取】。

## 11. 实际运行条件

- 服务端：任一官方 SDK（Python/Go/JS/Java/.NET/Rust）实现 A2A server
- 客户端：SDK 或手写 JSON-RPC 客户端
- 样例见 a2aproject/a2a-samples【官方文档结论】

## 12. 已知限制

- 规范处于 v1.0 RC 前夜的大重构期，文档与 SDK 可能滞后【已验证-页面抓取：commit 说明"pending feature requests…v1.0 release 前不加新特性"】
- 流式可靠性与推送通知机制自认有待改进【官方文档结论：What's next】
- Agent 发现/授权的规范化仍在路上【官方文档结论】

## 13. 对 AgentOS 的借鉴价值（重点：协议定位、传输方式、与 Agent 框架的关系）

- **协议定位**：MCP = agent↔工具，A2A = agent↔agent，两者互补（README 原文"A2A complements MCP"）【官方文档结论】。AgentOS 若要做跨系统 agent 互联，A2A 是应兼容的标准而非自造协议【推断】。
- **值得借鉴**：Agent Card 发现机制（能力+连接信息的自描述文档，可直接启发 AgentOS 的 agent 注册表条目设计）；Task 生命周期与 Resubscribe 语义（长时任务断线续传）；三种传输绑定 + protobuf 权威数据模型的规范组织方式；"不透明协作"原则（保护各 agent 内部实现）。
- **不适合照搬**：其跨组织/跨公司互操作的安全治理复杂度，超出 AgentOS 内部协作所需【推断】。
- **需自研**：AgentOS 内部的 agent 注册/发现可借鉴 Agent Card 但需结合自有多租户体系；A2A server 适配层（把 AgentOS 内部 agent 暴露为 A2A 端点）。

## 14. 分类建议

**E（Agent 互联协议）**——定位即"agentic applications 之间的开放通信与互操作协议"【官方文档结论】。与 MCP（E 中的工具侧）正交互补。
