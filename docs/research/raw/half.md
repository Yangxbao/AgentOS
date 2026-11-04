# HALF 调研笔记

- 仓库：<https://github.com/keting/half>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页（README）、`docs/architecture.md`（raw 抓取，对应 v0.2.1）

## 1. 基本信息

- 仓库地址：<https://github.com/keting/half>【已验证-页面抓取】
- 可访问性：可访问【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含）
- License：Apache License 2.0【已验证-页面抓取】
- 最近维护迹象：README 带 CI badge；架构文档对应 v0.2.1；页面未显示最近提交日期【已验证-页面抓取】。项目有 ROADMAP.md，处于早期迭代【推断】
- 技术栈：后端 Python 3.12 + FastAPI + SQLAlchemy + SQLite；前端 React 18 + TypeScript + Vite + React Flow；认证 JWT(HS256) + bcrypt；部署 Docker Compose【官方文档结论】

## 2. 核心架构与目录结构

**架构（三层）**【官方文档结论，docs/architecture.md】：
- 前端 SPA：React 页面（项目/计划/任务执行/模版/Agent 管理），JWT Bearer 调 REST API。
- 后端 FastAPI：鉴权、Prompt 生成、DAG 解析与校验、**Git 轮询 Worker**。后端**不主动调用任何 agent**。
- 存储双层：**SQLite 存系统状态**（项目/计划/任务/用户/审计日志），**Git 协作仓库存协同产物**（`plan-<id>.json`、`<task_code>/result.json`、`usage.json`），通过轮询桥接。

顶层目录【已验证-页面抓取】：`src/`（backend + frontend）、`docs/`、`ROADMAP.md`、`SECURITY.md`、`LICENSE`。

## 3. Agent 管理方式

- Agent 是**外部 CLI 工具的登记条目**（Claude Code、Codex、Copilot、GLM、Kimi 等），不含执行逻辑。实体字段含多模型配置（`models_json`）、订阅到期时间、短期/长期重置时间【官方文档结论】。
- "公共池 + 私有资源"模型：管理员创建的是公共 Agent（所有用户可用），普通用户创建的是私有 Agent（仅自己可见）【官方文档结论】。
- Agent 可用性是派生状态：`available / short_reset_pending / long_reset_pending / unavailable`（后者按订阅到期实时推导）【官方文档结论】。

## 4. 模型接入方式

- **不直接接入模型**。系统只生成 prompt，由人手工粘贴给各 agent CLI；模型配置仅作为 Agent 登记信息（`AgentTypeConfig` + `ModelDefinition`，管理员维护）【官方文档结论】。

## 5. CLI 接入方式

- 面向的是"管理 CLI agent"而非自身提供 CLI：被管理的 Claude Code / Codex 等以本地 CLI 运行，读写 Git 协作仓库；HALF 通过 git CLI clone/fetch/pull 轮询【官方文档结论】。

## 6. 多 Agent 协作方式

- **人工派发 + Git 哨兵轮询**：项目负责人复制系统生成的 prompt → 手工粘贴给 agent → agent 改代码并把产物写回协作仓库 → 最后原子提交 `result.json` 作为完成哨兵 → HALF 轮询识别完成、回写 SQLite 状态【官方文档结论】。
- 任务编排为 **DAG**（React Flow 可视化），支持流程模版（抽象槽位 `agent-N` 应用时替换为真实 Agent）【官方文档结论】。
- 刻意不做接口逆向、不调 agent 平台非公开接口【官方文档结论】。

## 7. 人工审批 / HITL

- **全人工在环（Human-AI Loop 即产品名）**：MVP 所有任务分发均由负责人手工完成，HALF 不自动发送任何 prompt【官方文档结论】。
- 任务状态含 `needs_attention`，执行汇总页有"人工介入记录"【官方文档结论】。
- 前端为剪贴板 user-activation 约束做了"预取 prompt + 同步写剪贴板"的细致编排【官方文档结论】。

## 8. 权限控制机制

- 账号两级：admin / user；JWT(HS256, 24h) + bcrypt；冻结用户 token 直接 403【官方文档结论】。
- Owner 级业务隔离：Project/Plan/Task 按 `created_by` 强制过滤，跨用户访问返回资源不存在【官方文档结论】。
- 系统强制至少保留一个激活管理员；超级管理员（username=admin）不可降级；公共 Agent 只能被创建它的管理员维护【官方文档结论】。
- 部署层信任模型：单租户自托管，默认管理员被完全信任（SECURITY.md 明确说明）【官方文档结论】。
- Git 地址校验防 SSRF：拒绝内嵌凭据、私有/本地 IP、危险协议等【官方文档结论】。

## 9. 运行记录 / 持久化

- SQLite：任务状态主记录、`TaskEvent`（dispatched/completed/timeout/manual_complete/abandoned 等事件流）、`AuditLog`（密码/角色/状态变更审计）【官方文档结论】。
- Git 仓库历史本身作为协同产物的版本化审计【官方文档结论】。
- 可选 `usage.json` 记录 token 用量；Codex 额度快照只存后端进程内存不落库【官方文档结论】。

## 10. 部署方式

- Docker Compose（前后端各一容器，后端挂载 SQLite 目录与 Git 仓库副本目录）；自托管定位【官方文档结论】。

## 11. 实际运行条件

- Python 3.12 + uv（后端测试 `uv run pytest`）；Node（前端，`npm test && npm run build`）；git CLI【已验证-页面抓取】。
- 生产部署默认关闭注册（`HALF_ALLOW_REGISTER=false`）【官方文档结论】。

## 12. 已知限制

- **纯人工派发**：agent 执行完全靠人复制粘贴，无法自动化闭环【官方文档结论】。
- 轮询而非事件驱动（合规约束下的妥协），有 15-30 秒级延迟【官方文档结论】。
- Agent 相关时间用"北京时间无时区" datetime 存储，与 UTC 业务时间双轨并行，是已知的别扭设计【官方文档结论】。
- 无统一分页抽象，列表接口多数直接返回全量【官方文档结论】。
- 单租户假设，管理员可绕过应用层访问所有数据【官方文档结论】。
- UI 主要为简体中文，英文 i18n 待贡献【已验证-页面抓取】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **"Git 仓库即协作总线"**：agent CLI 原生会读写 git，以 git 承载任务产物零集成成本，且自带版本审计——非常适合 CLI agent 编排场景。
- **`result.json` 原子哨兵契约**：固定目录 + 最后原子提交哨兵文件，解决轮询误判问题；比自然语言路径匹配可靠得多。
- **Owner 级隔离 + 公共/私有 Agent 池**的多租户权限模型，粒度设计细致（含降级迁移、引用检查等边界）。
- **轮询配置快照**（创建项目时快照全局默认值，不追溯）——避免全局变更影响进行中项目的务实做法。
- 任务事件流（TaskEvent）+ 审计日志分离的持久化设计。

**不适合照搬：**
- 纯手工派发模式：AgentOS 若要自动化执行，必须自己实现 agent 调用层。
- SQLite 单库 + 单租户假设，不适合多租户 SaaS。

**需自研：**
- agent 的自动化 invoke/回传通道（HALF 刻意不做）；agent 执行的沙箱与凭证管理。

## 14. 分类建议

- **A 完整产品**（主）：有完整前端、用户体系、部署形态，是面向"管理多个 coding CLI agent"的任务管理平台。
- **B Agent 工作流框架**（弱）：DAG + 流程模版有编排能力，但无程序化 API 供二次开发为主的使用方式。
- 理由：它是自托管的任务编排 Web 应用，核心价值在流程与人机协同治理，而非可嵌入的库【推断】。
