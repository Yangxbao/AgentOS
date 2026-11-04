# Microsoft Agent Framework 调研笔记

- 仓库：<https://github.com/microsoft/agent-framework>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页（README）、Microsoft Learn 用户指南概览页

## 1. 基本信息

- 仓库地址：<https://github.com/microsoft/agent-framework>【已验证-页面抓取】
- 可访问性：可访问【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含）
- License：仓库根目录含 LICENSE 文件，但抓取内容未显示许可证类型文本【未找到】（Microsoft 此类项目通常为 MIT，未验证，不采信）
- 最近维护迹象：最近提交集中于 2026-11-04；最新可见 release：Python 1.21.0（2026-10-08 版本号提升提交）【已验证-页面抓取】——高度活跃
- 技术栈：**Python（3.11–3.14，已移除 3.10）+ C#/.NET 双语言**，API 一致；Go 在独立仓库 `microsoft/agent-framework-go`（public preview，需 Go 1.26+）【已验证-页面抓取】【官方文档结论】
- 背景：Semantic Kernel 与 AutoGen 的直接后继，由同一团队合并两者而生【官方文档结论】

## 2. 核心架构与目录结构

四大板块【官方文档结论】：
1. **Agents**：LLM + 工具 + MCP 的单个智能体。
2. **Harness Agent**：batteries-included 的长任务智能体（规划/todo、上下文压缩、文件访问与记忆、工具审批"不再询问"、可观测性）。
3. **Workflows**：函数式 + 图式工作流，显式执行路径连接 agents 与函数。
4. **Integrations**：模型供应商、agent 服务、工具、context provider、中间件、评估、UI 框架。

基础构件：model clients、agent session（状态管理）、context providers（记忆）、middleware（拦截）、MCP clients【官方文档结论】。

顶层目录【已验证-页面抓取】：

```
.devcontainer/  .github/  .vscode/  docs/（含 design、decisions/ADR）
dotnet/  python/（包、示例、DevUI）  go/  declarative-agents/  skills/
README.md  LICENSE  SECURITY.md  CONTRIBUTING.md  AI_CONTRIBUTIONS.md
```

## 3. Agent 管理方式

- **代码定义**：`Agent(client=..., name=..., instructions=...)`（Python）/ `AsAIAgent(model, instructions, name)`（.NET）【官方文档结论】。
- **声明式 YAML**：`declarative-agents/` 目录提供 YAML 定义智能体的示例【已验证-页面抓取】。
- **Agent Skills**：从文件、内联代码、类库构建领域知识库（`skills/` 目录）【已验证-页面抓取】。

## 4. 模型接入方式

- 支持 **Microsoft Foundry、Anthropic、Azure OpenAI、OpenAI、Ollama、GitHub Copilot SDK 等**，按 provider 组织集成目录【官方文档结论】。
- 统一抽象：chat completions / responses 两类 model client；认证示例用 Azure 凭证链（`AzureCliCredential`）【官方文档结论】。

## 5. CLI 接入方式

- 未提供独立的通用 CLI 工具【未找到】；提供 **DevUI**（交互式开发者调试 UI，随 Python 包分发）【已验证-页面抓取】。

## 6. 多 Agent 协作方式

- **基于图的 workflow**：sequential、concurrent、handoff、group chat 等协作模式；含 checkpointing、streaming、human-in-the-loop、time-travel【已验证-页面抓取】。
- 选型指引："任务开放/对话式 → 用 agent；流程步骤明确/需显式控制执行顺序 → 用 workflow"；"能写函数解决就不要用 AI agent"【官方文档结论】。

## 7. 人工审批 / HITL

- workflow 明确支持 **human-in-the-loop**、可重启检查点、time-travel 调试【已验证-页面抓取】。
- Harness Agent 内置**工具审批**能力（含 "don't-ask-again" 记忆审批决定）【官方文档结论】。
- 具体审批 API 细节：未深入抓取 workflow 专页【未找到】。

## 8. 权限控制机制

- 框架层：中间件管道可拦截 agent 动作（请求/响应/异常），是自定义权限/安全逻辑的挂载点【官方文档结论】。
- 内置 OpenTelemetry 追踪用于审计可观测【已验证-页面抓取】。
- 面向企业的合规责任官方明确下放给用户（Transparency FAQ：第三方系统的数据流、权限、审批由使用者负责）【官方文档结论】。

## 9. 运行记录 / 持久化

- **Agent session** 状态管理 + **context providers**（记忆）；chat-history memory provider（语义记忆）【官方文档结论】。
- Workflow **checkpointing**（可重启）+ time-travel【已验证-页面抓取】。
- OpenTelemetry 分布式追踪内置【已验证-页面抓取】。

## 10. 部署方式

- **Foundry Hosted Agents**：+2 行代码把 agent 部署到 Azure Foundry 托管基础设施【已验证-页面抓取】。
- A2A 协议支持与自托管协议助手；Durable Task / Azure Functions 扩展在独立仓库 `agent-framework-durable-extension`【已验证-页面抓取】。
- 亦可作为普通 Python/.NET 库嵌入任意应用【推断】。

## 11. 实际运行条件

- Python：`pip install agent-framework`，Python 3.11–3.14；示例用 `az login` 认证，环境变量 `FOUNDRY_PROJECT_ENDPOINT`、`FOUNDRY_MODEL`【已验证-页面抓取】。
- .NET：`Microsoft.Agents.AI` 等 NuGet 包（含 prerelease）【已验证-页面抓取】。
- 注意：框架**不自动加载 `.env`**，需自行 `load_dotenv()`【官方文档结论】。

## 12. 已知限制

- Go 版为 public preview：声明式 agents、CodeAct、函数式 workflow 未实现【官方文档结论】。
- 深度绑定 Azure/Foundry 生态：托管部署、认证示例均以 Azure 为中心，非 Azure 用户体验打折【推断】。
- 双语言维护导致特性对齐有滞后风险（Python/.NET/Go 能力矩阵不一致）【推断】。
- 项目年轻（2025 年起，LICENSE 提交于 2025-04-28），API 仍在演进（NuGet 含 prerelease 包）【已验证-页面抓取 + 推断】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **Agent / Workflow 二元的选型哲学**：开放任务用 agent、明确流程用 workflow，且官方敢写"能写函数就别用 agent"——分层克制的框架设计观。
- **Harness Agent 的能力清单**：规划/todo、上下文压缩、文件访问与记忆、工具审批（含 don't-ask-again）——是"长任务执行体"的完整参考。
- **中间件管道**：agent 动作的统一拦截点，权限/审计/审批都可挂在上面，比分散在各处好。
- **声明式 YAML + 代码双轨定义** Agent；**DevUI** 调试器；OpenTelemetry 默认内置。
- **checkpointing + time-travel** 的 workflow 调试能力。

**不适合照搬：**
- Azure/Foundry 深度耦合的托管与凭证体系；双语言（Python/.NET）并行的工程成本对中小团队不现实。

**需自研：**
- 与云厂商无关的托管/部署层；面向业务的审批 UI 与多租户权限（框架只给中间件挂点）。

## 14. 分类建议

- **B Agent 工作流框架**（主）：官方定位即构建/编排/部署 agent 与多 agent 工作流的框架。
- **E Agent 互联协议**（弱）：支持 A2A 协议接入，但协议不是其本体。
- 理由：本体是 SDK/库 + 托管扩展，协议支持仅为集成能力之一【推断】。
