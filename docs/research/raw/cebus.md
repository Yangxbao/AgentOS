# Cebus 调研笔记

- 仓库：<https://github.com/cebus-ai/cebus>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页（README 全文经页面抓取）；raw.githubusercontent 的 main/master README 均返回 404（默认分支为 master，但 raw 抓取失败，原因不明）【已验证-页面抓取】

## 1. 基本信息

- 仓库地址：<https://github.com/cebus-ai/cebus>【已验证-页面抓取】
- 可访问性：可访问【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含）
- License：MIT【已验证-页面抓取】
- 最近维护迹象：最近提交 2026-03-09（`feat: v0.2.0 — monorepo migration with web, server, and VS Code apps`），首次提交 2026-02-13【已验证-页面抓取】。项目极年轻，距调研时间约 8 个月无提交——**维护活跃度存疑**【推断】
- 技术栈：TypeScript / Node.js 全栈（Turbo monorepo + npm workspaces）；编排引擎基于 **LangGraph (JS)**；CLI 用 Ink/React；Web 用 Vite/React/Tailwind；Server 用 tRPC + WebSocket；持久化用 better-sqlite3【已验证-页面抓取】

## 2. 核心架构与目录结构

Turbo monorepo【已验证-页面抓取】：

```
packages/engine/   # @cebus/engine — 核心编排引擎
  src/core/            # 类型、session、消息、mention 解析、模型分级/定价
  src/orchestration/   # LangGraph 状态机、路由策略、workers
    orchestrator/      # sequential / tag-only / free-chat / 动态路由 / team leader
    worker/            # langchain-worker(默认) / copilot-worker / provider-adapter
apps/cli/          # @cebus/cli — 终端 UI (Ink/React)
apps/web/          # @cebus/web — 浏览器 UI
apps/server/       # @cebus/server — tRPC + WebSocket
apps/vscode/       # VS Code 扩展（含 webview）
.cebus/prompts/    # 外置 prompt 文件（运行时可编辑）
.cebus/agents/     # 自定义角色定义 *.agent.md（YAML frontmatter + markdown）
```

## 3. Agent 管理方式

- Agent = **一个模型实例 + 可选角色定义**。角色用 `.cebus/agents/*.agent.md` 文件定义（YAML frontmatter + Markdown 指令），支持内置模板、拖拽排序【已验证-页面抓取】。
- 会话中可动态增删/重命名参与者（Session Management）【已验证-页面抓取】。
- 模型按成本分级：premium / middle / budget / local【已验证-页面抓取】。

## 4. 模型接入方式

六家供应商 + 网关【已验证-页面抓取】：

| 供应商 | 认证 |
|---|---|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google Gemini | `GOOGLE_API_KEY` |
| GitHub Copilot（SDK 原生） | `gh auth` |
| Ollama（本地） | 无需密钥 |
| OpenRouter（多供应商网关，BYOK） | `OPENROUTER_API_KEY` |
| VS Code `vscode.lm` API | VS Code 扩展内 |

统一方式：engine 的 `providers/` 适配层 + 默认 `langchain-worker`（LangChain JS 统一接口）；上下文溢出时自动切换模型【已验证-页面抓取】。

## 5. CLI 接入方式

- 核心形态就是 CLI：`cebus` 交互式引导；`cebus chat -m openai:gpt-4o -m anthropic:claude-sonnet-4-5...`（可自定义昵称）；`cebus --resume <session-id>`；`cebus config`【已验证-页面抓取】。
- 聊天内斜杠命令：`/add /remove /rename /context /list /clear` 等；寻址用 `@昵称`、多 @、自然语言或广播【已验证-页面抓取】。

## 6. 多 Agent 协作方式

- **LangGraph 状态机编排**，中心辐射架构；编排模式：sequential、tag-only、free-chat、raw（无编排）、动态编排器、**Team Leader 模式**【已验证-页面抓取】。
- 聊天模式：All at Once / One by One / Mention Only / Role-Based / Raw【已验证-页面抓取】。
- Team Leader：可见的 AI 协调者，分阶段 clarify → plan → deliberate → execute → review → synthesize，带预算护栏【已验证-页面抓取】。
- 可选 AI Orchestrator 中间件分析消息、编排多轮讨论（可用 Ollama 免费跑）【已验证-页面抓取】。

## 7. 人工审批 / HITL

- Copilot SDK 集成自带 **tool approval workflow**（文件编辑/shell 等工具执行前审批）【已验证-页面抓取】。
- Team Leader 模式支持用户中断（stop / skip / restart）并选择协作策略【已验证-页面抓取】。
- 除此之外无独立的通用人工审批框架【推断】。

## 8. 权限控制机制

- 较弱：API key 走环境变量；Copilot 走 `gh auth`；项目上下文有"可配置文件夹访问"限制【已验证-页面抓取】。
- 无多用户/RBAC 机制（Web 端有 useAuth hook，但 README 未描述权限模型）【已验证-页面抓取 + 推断】。

## 9. 运行记录 / 持久化

- Session Persistence：better-sqlite3 保存/恢复历史会话；`--resume` 恢复【已验证-页面抓取】。
- LangGraph checkpointer + 会话压缩（engine 的 `session/` 目录含 checkpointer、compaction）【已验证-页面抓取】。
- 按模型的 token/成本统计，三层定价解析【已验证-页面抓取】。

## 10. 部署方式

- 本地 CLI（`install.sh` / `install.cmd`）；`npm install -g cebus`（发布时——README 注明 "when published"，即尚未发布 npm 包）【已验证-页面抓取】。
- Web 端本地 dev server（Vite 5173）；无云端托管形态【已验证-页面抓取】。

## 11. 实际运行条件

- **Node.js >= 24.0.0**（Bun 不可用——better-sqlite3 原生模块不兼容）；Windows 用 Copilot 需 PowerShell v6+；Copilot 需付费订阅；API key 用户需自行配置 MCP 才有工具能力【已验证-页面抓取】。

## 12. 已知限制

- 项目极新（2026-02 创建），近 8 个月无提交，成熟度与持续维护存疑【推断】。
- 无通用人工审批/权限框架，偏"多模型群聊"工具【推断】。
- npm 包尚未发布，安装依赖 git clone + 脚本【已验证-页面抓取】。
- 仅 en/he 两种界面语言【已验证-页面抓取】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **角色定义 = `*.agent.md`（YAML frontmatter + Markdown）**：人类可读、可版本管理的 Agent 定义格式，简单有效。
- **prompt 外置到 `.cebus/prompts/*.md` 且运行时可编辑**：调 prompt 不用改代码。
- **模型成本分级（premium/middle/budget/local）+ 上下文溢出自动切模型**：务实的成本护栏设计。
- **多种轻量编排模式**（tag-only/free-chat/mention）覆盖"多模型群聊"场景；Team Leader 分阶段（clarify→plan→deliberate→execute→review→synthesize）是可参考的监督者 prompt 流程。
- 基于 LangGraph checkpointer 的会话恢复。

**不适合照搬：**
- 本质是"多模型群聊客户端"，缺任务/工件/权限模型，离"OS"差距大。
- 无独立审批框架，HITL 依赖 Copilot SDK 内置能力。

**需自研：**
- 权限、审计、任务生命周期管理几乎全部需自研；其角色文件格式与模型分级可直接借用。

## 14. 分类建议

- **D CLI 执行工具**（主）：以终端多模型会话为核心形态。
- **B Agent 工作流框架**（次）：engine 基于 LangGraph 有多种编排模式，但以应用形式打包而非库。
- 理由：核心价值是多模型对话与轻量编排的终端体验，不是可嵌入的框架，也无网关/协议属性【推断】。
