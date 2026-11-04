# github/copilot-sdk 调研笔记（重点：程序化接入 / headless / 认证方式）

> 调研时间：2026-11-05。

## 1. 基本信息

- 仓库地址：https://github.com/github/copilot-sdk 【已验证-页面抓取】
- 可访问性：**可访问**（仓库存在，主页含完整 README）【已验证-页面抓取】
- License：**MIT**（README License 段明确）【官方文档结论】
- 最近维护迹象：活跃——文件列表显示 2026-11-04 多处提交（如 "Update SDK snapshot for Copilot CLI 1.0.106-1"）；README 称 SDK 已 GA（generally available）、遵循语义化版本，有 CHANGELOG.md【已验证-页面抓取】。Star 数：未找到（抓取页面未显示）
- 技术栈：多语言 monorepo——Node.js/TypeScript、Python、Go、.NET、Rust、Java 六个官方 SDK；底层驱动 Copilot CLI（agent runtime）【已验证-页面抓取】
- 描述："Multi-platform SDK for integrating GitHub Copilot Agent into apps and services"（"Agents for every app"）

## 2. 核心架构与目录结构

【官方文档结论：README Architecture 段】

- 所有 SDK 通过 **JSON-RPC** 驱动 Copilot agent runtime
- **默认形态**：Copilot CLI 以 **server mode 子进程**方式托管 runtime，SDK 自动管理 CLI 进程生命周期：

```
Your Application → SDK Client → JSON-RPC → Copilot CLI (server mode)
```

- **实验性 in-process 形态**：通过 C ABI 把原生 Copilot runtime 载入应用进程，JSON-RPC 走内存连接，不启动 CLI 进程
- 也可连接**外部 CLI server**（CLI 以 server 模式独立运行）
- 目录：`nodejs/`、`python/`、`go/`、`dotnet/`、`rust/`、`java/` + `docs/`（getting-started、setup、auth、features、troubleshooting）

## 3. Agent 管理方式

【官方文档结论：FAQ】"you define agent behavior, Copilot handles planning, tool invocation, file edits"——SDK 暴露的是 Copilot CLI 背后的同一套生产级 agent runtime。支持**自定义 agents、skills、tools**；提供 **Agent Finder Skill 安装 API**（`skills.planInstall/applyInstall/planUninstall/applyUninstall/installations.*`，含安装评审：完整 SKILL.md 内容校验至 256 KiB、目录身份、文件清单）【已验证-页面抓取】。

## 4. 模型接入方式

【官方文档结论：FAQ】

- Copilot CLI 可用的所有模型 SDK 均可用，SDK 提供运行时枚举可用模型的方法
- **BYOK（Bring Your Own Key）**：可配置自有 OpenAI / Microsoft Foundry / Anthropic 等供应商的 API key 直接用模型，此时**无需 GitHub 认证**
- BYOK 仅支持 key 认证；不支持 Microsoft Entra ID、managed identity、第三方 IdP

## 5. CLI 接入方式（重点：程序化接入能力边界）

【官方文档结论：README + FAQ】

- **官方程序化接入即本 SDK**：六种语言包（`@github/copilot-sdk`、`github-copilot-sdk`、`github.com/github/copilot-sdk/go`、`GitHub.Copilot.SDK`、`github-copilot-sdk` crate、`com.github:copilot-sdk-java`）
- CLI 捆绑策略：Node/Python/.NET **自动捆绑** Copilot CLI 无需单装；Go/Java/Rust 默认**不捆绑**，需 CLI 在 PATH（Go/Rust 有应用级捆绑特性）
- 无独立 headless CLI 命令的说明（与 codex exec 不同）；headless 能力通过 SDK + server mode 实现【推断：README 未提 copilot CLI 自身的非交互命令】
- 默认工具面：相当于 CLI `--allow-all` 的第一方工具，但**每次工具执行都经 SDK 的 permission handler**，应用可 approve/deny/自定义

### 认证方式（FAQ 明确列出四种）

1. **GitHub 已登录用户**：复用 `copilot` CLI 登录存储的 OAuth 凭据
2. **OAuth GitHub App**：传入自建 GitHub OAuth app 的 user token
3. **环境变量**：`COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`
4. **BYOK**：自有 API key，无需 GitHub 认证

计费：与 Copilot CLI 同模型，按 prompt 计用量；非 BYOK 需 Copilot 订阅（含免费层有限额度）【官方文档结论】。

## 6. 多 Agent 协作方式

【官方文档结论】支持自定义 agents/skills/tools；README 有 "Portable elicitation schemas"（跨语言表单 elicitation 回调契约）；未找到内建的多 agent 编排/委派机制说明，以单 agent runtime + 自定义扩展为主【推断】。

## 7. 人工审批/人在回路机制

【官方文档结论：FAQ + README】

- **Permission handler**：应用可对每次工具调用 approve/deny/customize——HITL 的核心挂点
- **Elicitation**：runtime 可向应用发起表单式输入请求（portable elicitation schema，wire 上为 `type: "object"` + `properties`/`required`；Node/Rust 透传原始 schema，Python/Go/.NET/Java 重建，跨语言不应依赖额外元数据或属性顺序）
- Skill 安装有评审流程（verified SKILL.md 内容、catalogue identity、file manifest）

## 8. 权限控制机制

【官方文档结论】工具执行一律经 permission handler；工具可按 client options 启停；`skill-confirmed-installation` 权限面控制 skill 安装 API；认证四方式见上节。沙箱/文件系统隔离细节未找到（README 未述）【推断：依赖 CLI 自身机制】。

## 9. 运行记录/持久化能力

未找到（README/FAQ 未提及会话持久化、日志或运行记录的形态）。

## 10. 部署方式

【官方文档结论】SDK 嵌入宿主应用；runtime 三种托管：SDK 托管 CLI 子进程（默认）、外部 CLI server、实验性 in-process（C ABI）；docs/setup 含 deployment/scaling 指南（内容未抓取）。Cookbook 在 github/awesome-copilot 仓库。

## 11. 实际运行条件

- 非 BYOK 需 GitHub Copilot 订阅（含免费层）【官方文档结论】
- Go/Java/Rust 需手动安装 Copilot CLI 或 PATH 可用【官方文档结论】
- 另有社区维护的非官方 SDK（Clojure、C++），GitHub 不支持【已验证-页面抓取】

## 12. 已知限制

- BYOK 仅 key 认证，不支持 Entra ID/managed identity【官方文档结论】
- elicitation schema 的 wire 级保留是语言相关能力，跨语言应用只能依赖建模字段【官方文档结论】
- in-process runtime 为实验性【官方文档结论】
- 运行记录/持久化、沙箱隔离细节公开文档中未找到

## 13. 对 AgentOS 的借鉴价值

- **值得借鉴**：
  - **"CLI server mode + JSON-RPC" 作为 SDK 统一底座**：一套 runtime，六种语言薄封装——AgentOS 若要多语言 SDK，此架构性价比极高
  - **permission handler 回调模式**：工具调用审批完全交给宿主应用，天然适合 AgentOS 的统一审批中心
  - **BYOK 设计**：订阅认证与自有 key 双轨并行，降低企业接入门槛
  - elicitation 的跨语言 schema 契约经验（哪些该标准化、哪些留给语言）
- **不适合照搬**：与 GitHub Copilot 订阅/计费体系绑定；模型面受限于 Copilot 供给；无开源 runtime（SDK 开源但引擎闭源、捆绑 CLI 二进制）【推断】。
- **需自研**：AgentOS 若接入 Copilot 作为执行后端，需封装其 JSON-RPC 会话与 permission handler 到自身任务/审批模型；认证映射（GitHub token vs BYOK）按租户配置。

## 14. 分类建议

**D（CLI 执行工具）+ B（Agent 工作流框架的"SDK 化内核"）**。理由：本体是 Copilot CLI runtime 的官方程序化封装（偏 D），但提供自定义 agents/skills/tools 与审批回调，具备嵌入式 agent 框架特征（偏 B）【官方文档结论+推断】。对 AgentOS 而言其价值在"接入一个成熟编码 agent 引擎"而非自建框架。
