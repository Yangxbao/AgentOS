# CrewAI 调研笔记

- 仓库：<https://github.com/crewAIInc/crewAI>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页（README）、官方文档 concepts/agents 页、concepts/processes 页

## 1. 基本信息

- 仓库地址：<https://github.com/crewAIInc/crewAI>【已验证-页面抓取】
- 可访问性：可访问【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含）。README 称 100,000+ 开发者通过其社区课程认证【已验证-页面抓取】
- License：MIT【已验证-页面抓取】
- 最近维护迹象：最近提交 2026-11-01（`chore(deps): drop the nltk advisory ignore... (#8918)`）【已验证-页面抓取】——活跃维护中
- 技术栈：Python（primarily Python-based，可集成任意语言的服务/API）；依赖管理用 uv；文档站 Mintlify【已验证-页面抓取】

## 2. 核心架构与目录结构

- 两大核心抽象：**Crews**（自主角色协作）+ **Flows**（事件驱动精确控制），可互相嵌套（Flow 中编排多个 Crew，`@start/@listen/@router` 装饰器，`or_/and_` 逻辑）【已验证-页面抓取】。
- 仓库顶层目录：抓取内容未包含文件列表【未找到】。
- 脚手架项目结构（`crewai create crew` 生成）【已验证-页面抓取】：

```
my_project/
├── agents/researcher.jsonc   # JSON-first Agent 定义（支持注释、占位符）
├── crew.jsonc                # 团队配置 + inputs 默认值
├── knowledge/  skills/  tools/
├── .env  pyproject.toml  README.md
```

`--classic` 可退回旧的 Python/YAML（`config/agents.yaml` + `@CrewBase`）模式【官方文档结论】。

## 3. Agent 管理方式

- 三要素必填：**role / goal / backstory**（角色、目标、背景故事）【官方文档结论】。
- 三种定义方式：JSONC 配置（推荐）、经典 YAML、代码实例化 `Agent(...)`【官方文档结论】。
- 关键属性：`tools`、`knowledge_sources`、`max_iter`(默认20)、`max_execution_time`、`max_rpm`、`max_retry_limit`(默认2)、`memory`、`respect_context_window`(默认True，超限自动摘要)、`verbose`、`allow_delegation`(默认False)、`reasoning`、`step_callback`、`system_template/prompt_template` 等【官方文档结论】。
- 已废弃：`allow_code_execution`、`CodeInterpreterTool` 移除，官方建议用 E2B/Modal 沙箱【官方文档结论】。

## 4. 模型接入方式

- `llm` 属性：字符串（如 `"openai/gpt-4o"`）或 `LLM` 实例，默认 `OPENAI_MODEL_NAME` 或 "gpt-4"【官方文档结论】。
- `function_calling_llm`：工具调用可单独指定更便宜模型，成本优化手段【官方文档结论】。
- 默认 OpenAI；支持本地模型（Ollama、LM Studio）与自定义微调模型；底层统一走 LiteLLM 风格的 provider 前缀约定【官方文档结论 + 推断（统一层实现细节未直接验证）】。

## 5. CLI 接入方式

- 官方 CLI：`uv tool install crewai`；`crewai create crew <name>` / `crewai install` / `crewai run`【已验证-页面抓取】。

## 6. 多 Agent 协作方式

两种 Process（Enum 类型安全）【官方文档结论，processes 文档页】：
- **Sequential**：任务按预定义顺序执行，前一任务输出作为后一任务上下文（可用 `context` 参数定制）。
- **Hierarchical**：模拟企业层级，必须指定 `manager_llm` 或 `manager_agent`；manager 负责规划、委派、评审输出、判断完成；任务不预分配，由 manager 按 agent 能力动态分配。
- Agent 级委派由 `allow_delegation=True` 开启【官方文档结论】。
- Flows 提供事件驱动的确定性编排，与 Crews 互补【已验证-页面抓取】。

## 7. 人工审批 / HITL

- README 明确"完全支持人在回路工作流"；执行中人工输入（human input on execution）与任务人工审查（human review）【已验证-页面抓取】。
- Task 层面通过 `human_input=True` 配置（agents 文档页提示，未深入 task 页验证）【官方文档结论】。
- 旁路手段：`step_callback` 每步监控；`respect_context_window=False` 时超限直接 `SystemExit`，宁可失败等人工处理【官方文档结论】。

## 8. 权限控制机制

- 框架层**无权限/RBAC 模型**【未找到】。
- 遥测默认开启（匿名使用数据，不收集 prompt/响应），`OTEL_SDK_DISABLED=true` 关闭【已验证-页面抓取】。
- 企业安全合规则属商业产品 CrewAI AMP Suite 范畴【已验证-页面抓取】。

## 9. 运行记录 / 持久化

- Agent 能力含记忆（memory）、知识库、**checkpointing**、异步执行【已验证-页面抓取】。
- `cache`（工具结果缓存，默认开）【官方文档结论】。
- 追踪与可观测性完整能力在 AMP Suite（商业）【已验证-页面抓取】。

## 10. 部署方式

- 开源框架为 Python 库，本地/自托管运行；商业控制平面 **CrewAI AMP Suite** 支持云端与 On-premise，提供追踪、统一控制平面、企业集成【已验证-页面抓取】。

## 11. 实际运行条件

- **Python >=3.10 且 <3.14**；用 uv 管理依赖；`.env` 配模型 API key（可选 SERPER_API_KEY）【已验证-页面抓取】。

## 12. 已知限制

- 编排模型只有 sequential / hierarchical 两种，复杂流程需靠 Flows 自己写事件逻辑【官方文档结论】。
- 重复工具调用保护不可配置：同参同结果达 5 次即 `ToolExecutionFailedError` 终止且不可禁用【官方文档结论】。
- 代码执行内置能力已移除，须外接沙箱服务【官方文档结论】。
- 框架本身无权限/审计/多租户，企业能力绑定商业套件【推断】。
- 默认遥测开启（可关）【已验证-页面抓取】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **role/goal/backstory 三要素**：最简且有效的角色定义范式，已被广泛验证。
- **JSON-first 脚手架 + CLI 一条龙**（create/install/run）：新项目 onboarding 体验好；JSONC 支持占位符与默认值的做法值得抄。
- **Sequential + Hierarchical 双模式**：覆盖"流水线"与"监督者动态分配"两大主流编排，manager_llm/manager_agent 的设计简单清晰。
- **function_calling_llm 分离**：主模型推理 + 便宜模型做工具调用的成本分层。
- **Crews（自主）+ Flows（确定）双层架构**：让"灵活协作"与"精确控制"各归其位、可组合，这是与 LangGraph 纯图模型不同的高层取舍。

**不适合照搬：**
- 角色扮演式 prompt 工程在严肃企业场景的可控性有限；审批/权限几乎为零。
- 遥测默认开启需评估合规。

**需自研：**
- 权限、审批工作流、审计、运行记录的持久化展示——CrewAI 开源版均不提供。

## 14. 分类建议

- **B Agent 工作流框架**（明确）：官方定位即编排角色扮演式自主 Agent 的框架；CLI 只是脚手架工具，不构成独立 CLI 执行工具分类【已验证-页面抓取】。
