# openai/codex 调研笔记（重点：程序化接入 / headless / 认证方式）

> 调研时间：2026-11-05。

## 1. 基本信息

- 仓库地址：https://github.com/openai/codex 【已验证-页面抓取】
- 可访问性：GitHub 主页、README raw、SDK README 均抓取成功；官方文档站 developers.openai.com 抓取返回 **403 Forbidden**（反爬拦截），其内容通过 WebSearch 结果与仓库内文档补齐【已验证-页面抓取】
- License：**Apache-2.0**【已验证-页面抓取：GitHub 主页 + README】
- 最近维护迹象：非常活跃——最近 commit `48524f3`（2026-11-04）；13,102 commits、1,528 tags、4,712 分支；**133.2k stars / 21.1k forks**【已验证-页面抓取】
- 技术栈：**Rust 核心**（`codex-rs/`）+ TypeScript（`codex-cli/`、`sdk/`）+ Python SDK（`sdk/python`）；构建用 Bazel/pnpm/just；内嵌 V8（rusty_v8）支持 code-mode【已验证-页面抓取】
- 文档站：https://developers.openai.com/codex（本环境抓取被 403 拦截，浏览器可访问）

## 2. 核心架构与目录结构

【已验证-页面抓取：GitHub 主页提取】

- `codex-cli`：终端 CLI 主程序（TUI）
- `codex-rs`：Rust 核心（沙箱、压缩、会话管理）
- `sdk/`：TypeScript SDK；`sdk/python`：Python SDK
- `codex-exec-server`：独立执行器（standalone executor），随发布包分发，支持沙箱强制执行
- 安装器：shell/PowerShell 脚本，默认从 releases.openai.com 下载、回退 GitHub Releases
- 衍生形态：IDE 扩展（VS Code/Cursor/Windsurf）、`codex app` 桌面应用、Codex Web（云端 agent，chatgpt.com/codex）【官方文档结论：README】

## 3. Agent 管理方式

【官方文档结论】单 agent 编码代理；以 **thread（会话线程）** 为单位管理：SDK 中 `startThread()`/`resumeThread(id)`，CLI 中 `codex exec resume [SESSION_ID]` / `codex fork [SESSION_ID]`。thread 持久化于 `~/.codex/sessions`【官方文档结论：TS SDK README】。支持 AGENTS.md 项目指令文件【已验证-页面抓取：docs/agents_md.md】。

## 4. 模型接入方式

- 默认使用 ChatGPT 套餐内模型或 OpenAI API【官方文档结论：README】
- `-m/--model` 覆盖模型；`--oss` 走本地开源 provider（需运行中的 Ollama）；`--local-provider` 选 lmstudio/ollama【已验证-页面抓取：WebSearch 引用的 CLI reference】
- SDK 可设 `baseUrl`（传为 `--config openai_base_url=...`）【官方文档结论：TS SDK README】

## 5. CLI 接入方式（重点：程序化接入能力边界）

### 5.1 `codex exec` 非交互模式（headless）

【官方文档结论：WebSearch 命中的 developers.openai.com/codex/noninteractive 文档】

- 用法：`codex exec "任务提示"`；进度流输出到 stderr，**最终 agent 消息输出到 stdout**，可直接管道（`codex exec "..." | tee notes.md`）
- **结构化输出**：
  - `--json`（即 `--experimental-json`）：stdout 变为 **JSONL 事件流**，事件类型含 `thread.started`、`turn.started`、`turn.completed`、`turn.failed`、`item.*`、`error`；item 类型含 agent 消息、推理、命令执行、文件变更、MCP 工具调用、web 搜索、计划更新
  - `-o/--output-last-message <文件>`：把最终消息写文件
  - `--output-schema <schema.json>`：强制最终响应符合 JSON Schema（供下游自动化稳定解析）
- **会话控制**：`--ephemeral` 不落盘 session 文件；`codex exec resume [SESSION_ID] [--last] [--all]` 续跑
- **自动化辅助**：`-C/--cd` 设工作根；`--skip-git-repo-check`（默认要求 git 仓库）；`--ignore-user-config`（不加载 `$CODEX_HOME/config.toml`）；`--ignore-rules`（跳过 execpolicy .rules）；`-c key=value` 内联配置覆盖；`-i/--image` 附图；stdin 管道内容作为附加上下文
- **行为边界**：exec 模式**无法交互询问**——approval policy 为 on-request/untrusted 时需要批准的动作会失败并回给模型；自动化场景应靠沙箱模式与显式开关授权【官方文档结论：WebSearch 命中 CLI reference】

### 5.2 官方 SDK（程序化接入）

【官方文档结论：sdk/typescript/README.md 与 sdk/python/README.md，均已验证抓取】

- **TypeScript**：`npm install @openai/codex-sdk`，Node 18+。`new Codex()` → `startThread()` → `thread.run("...")` 返回 `finalResponse/items/usage`；`runStreamed()` 异步流式事件（`item.completed`、`turn.completed` 带 token usage）；`outputSchema` 参数做结构化输出（可配合 zod-to-json-schema）；`resumeThread(id)` 恢复会话；`skipGitRepoCheck`、`workingDirectory`、`env`、`config`（对象打平为 `--config key=value`）与 `configOverrides`（原始 TOML）控制 CLI。**SDK 原理：spawn codex CLI 子进程，通过 stdin/stdout 交换 JSONL 事件**
- **Python**：`pip install openai-codex`；`Codex()` 上下文管理器 → `thread_start()` → `thread.run()` 返回 TurnResult（final_response、items、token usage）

### 5.3 认证方式

【官方文档结论：README + Python SDK README】

- **ChatGPT 账号登录**：`codex` 内选 "Sign in with ChatGPT"（Plus/Pro/Business/Edu/Enterprise 套餐）；Python SDK 有 `login_chatgpt()`（浏览器）与 `login_chatgpt_device_code()`（设备码）
- **API key**：`login_api_key("sk-...")`；TS SDK 注入 `CODEX_API_KEY` 环境变量
- SDK 自动复用已有 Codex 认证

## 6. 多 Agent 协作方式

未找到内建多 agent 编排（单 agent + 工具/MCP 模式）【推断：README 与 SDK 文档均未提及】。支持 MCP server 接入（`codex mcp list/add/remove`；依赖 `@modelcontextprotocol/sdk`）【已验证-页面抓取】。

## 7. 人工审批/人在回路机制

【官方文档结论：WebSearch 命中的 developers.openai.com/codex/sandbox】

- 审批策略：`--ask-for-approval never|on-request|untrusted`（`on-failure` 已废弃）；配置项 `approval_policy`
- **Auto-review 模式**：`approvals_reviewer = "auto_review"`——符合条件的审批请求由自动评审代替用户确认（workspace-write 沙箱下）
- 细粒度审批：`approval_policy = { granular = { sandbox_approval, rules, mcp_elicitations, request_permissions, skill_approval } }`
- exec 非交互模式不能弹审批，需用 `-a never` + 沙箱授权

## 8. 权限控制机制

【官方文档结论：sandbox 文档】

- **沙箱三档**：`read-only`（exec 默认）/ `workspace-write` / `danger-full-access`；`--dangerously-bypass-approvals-and-sandbox`（`--yolo`）仅限隔离环境
- OS 级实现：macOS Seatbelt（sandbox-exec）；Linux bwrap + seccomp；Windows 原生沙箱（`[windows] sandbox = "unelevated"|"elevated"`）或 WSL2 继承 Linux 语义；WSL1 自 0.115 起不再支持
- workspace-write 可写根：`-C` 根、`/tmp`、`$TMPDIR`、`--add-dir`；网络默认关闭，用 `sandbox_workspace_write.network_access = true` 开启
- **execpolicy**：用户/项目级 `.rules` 文件定义命令执行策略；企业可用 `allow_managed_hooks_only` 强制只跑受管 hooks【已验证-页面抓取：docs/config.md commit 说明】
- 沙箱自检：`codex sandbox -- true` / `codex doctor`

## 9. 运行记录/持久化能力

【官方文档结论】session rollout 文件持久化于 `~/.codex/sessions`（`--ephemeral` 可关闭）；exec 的 JSONL 事件流本身即完整运行记录；`turn.completed` 事件带 token usage（input/cached/output/reasoning tokens）【官方文档结论：noninteractive 文档】。

## 10. 部署方式

- 本地安装：install.sh/install.ps1、npm `-g @openai/codex`、Homebrew cask、GitHub Releases 平台二进制（macOS arm64/x64、Linux musl x64/arm64）【官方文档结论：README】
- CI/CD：exec 非交互模式 + `--json`，官方明确面向 pipeline/CI 场景【官方文档结论】
- 另有 IDE 扩展、桌面 app、云端 Codex Web【官方文档结论】

## 11. 实际运行条件

- ChatGPT 付费套餐账号或 OpenAI API key【官方文档结论】
- TS SDK 需 Node 18+；SDK 依赖本机 codex CLI 二进制（TS SDK 从 `@openai/codex` 包内获取）【官方文档结论】
- 默认要求工作目录为 Git 仓库（可用 skipGitRepoCheck 跳过）【官方文档结论】

## 12. 已知限制

- developers.openai.com 文档站有反爬（本环境 403）【已验证-页面抓取】
- `--full-auto` 已废弃（保留兼容警告），须改用 `--sandbox workspace-write`【官方文档结论】
- exec 模式无法交互审批，授权只能前置设定【官方文档结论】
- 仓库**不接受外部 PR/代码贡献**，只收 issue【已验证-页面抓取：docs/contributing.md commit 说明】
- WSL1 不再支持；沙箱在部分容器/PRoot 环境无法强制执行【官方文档结论：WebSearch 命中文档】

## 13. 对 AgentOS 的借鉴价值

- **值得借鉴**：
  - **headless 设计范式**：stderr 进度 + stdout 结果 + `--json` JSONL 事件流 + `--output-schema` 结构化输出——AgentOS 的 CLI 执行工具接入层可直接对标
  - **SDK = CLI 子进程 + JSONL 协议**：轻量且天然版本对齐的 SDK 实现方式
  - **沙箱三档 + 审批策略矩阵**（含 granular、auto_review）是工程化权限设计的优秀范本
  - thread 持久化 + resume 语义
- **不适合照搬**：认证强绑 ChatGPT/OpenAI 账号体系；模型面窄（仅 OpenAI 系 + 本地 OSS）；无多 agent 编排。
- **需自研**：把 codex 作为 AgentOS 的"执行型 agent 运行时"之一接入（spawn CLI、消费 JSONL、映射为 AgentOS 任务记录），并用自己的模型网关替代其认证体系——注意 SDK 会强制注入其所需变量（如 CODEX_API_KEY），接入层要做环境隔离【推断+官方文档结论】。

## 14. 分类建议

**D（CLI 执行工具）**——核心形态是终端编码 agent + headless exec + 薄 SDK 封装【官方文档结论】。兼具 B 的萌芽（thread/会话/MCP），但无多 agent 编排，不足以归 B。
