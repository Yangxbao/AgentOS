# LangGraph 调研笔记

- 仓库：<https://github.com/langchain-ai/langgraph>
- 调研时间：2026-11-05
- 抓取来源：GitHub 仓库主页、官方文档 overview 页、interrupts（HITL）页

## 1. 基本信息

- 仓库地址：<https://github.com/langchain-ai/langgraph>【已验证-页面抓取】
- 可访问性：可访问【已验证-页面抓取】
- Star 数：未找到（抓取内容未包含）
- License：MIT（README 徽章指向 opensource.org/licenses/MIT）【已验证-页面抓取】
- 最近维护迹象：最近提交 2026-11-04（`feat(sdk-py): add select to threads.get_state...`），总提交 7,268 次【已验证-页面抓取】——高度活跃
- 技术栈：Python（`libs/` 下含 langgraph、checkpoint、sdk-py 等）+ JS/TS（LangGraph.js、sdk-js、cli）【已验证-页面抓取】

## 2. 核心架构与目录结构

- 定位：**低层级编排框架 + 运行时**，用"共享状态 + 节点 + 边"的图定义工作流，确定性步骤与 LLM 步骤可混排在同一图；不规定 prompt 与 Agent 架构【官方文档结论】。
- 受 Google Pregel / Apache Beam 启发，接口借鉴 NetworkX【已验证-页面抓取】。

顶层目录【已验证-页面抓取】：

```
.github/  docs/  examples/  libs/   # libs 下为核心库（langgraph、checkpoint、sdk-py、sdk-js、cli）
.gitignore  AGENTS.md  LICENSE  Makefile  README.md
```

## 3. Agent 管理方式

- **无"角色"概念**：Agent 即图（StateGraph）。状态用 `MessagesState`/自定义 TypedDict 定义，节点是普通函数（可为 LLM 调用），边定义控制流，`compile()` 后可 invoke/stream【官方文档结论】。
- 更高层抽象交给生态包：Deep Agents（规划、子 Agent、文件系统）、LangChain agents【官方文档结论】。

## 4. 模型接入方式

- **模型无关**：框架本身不含模型列表，通常经 LangChain 的 model 集成接入（OpenAI/Anthropic/…），但"LangGraph does not require LangChain"【官方文档结论】。

## 5. CLI 接入方式

- `libs/` 下含 `cli` 包（LangGraph CLI，用于本地开发/部署到 LangSmith Deployment）【已验证-页面抓取】；细节未深入抓取【未找到】。

## 6. 多 Agent 协作方式

- **图编排**：显式定义节点/边/条件边，可组合子图；多 Agent 模式（supervisor、handoff 等）由用户在图上自建【官方文档结论】。
- 支持并行分支；多 interrupt 并行暂停时用 interrupt ID → resume 值的字典恢复【官方文档结论】。

## 7. 人工审批 / HITL

核心机制是 **`interrupt()`**【官方文档结论，interrupts 文档页】：
- 节点内任意位置调用 `interrupt(payload)`，动态挂起执行；payload 经 checkpointer 持久化后返回给调用方；外部以 `Command(resume=...)` + 相同 thread_id 恢复，resume 值成为 `interrupt()` 返回值。
- 三个前提：配置 checkpointer、指定 thread_id、payload 必须 JSON 可序列化。
- 支持 `response_schema`（Pydantic/TypedDict，需 langgraph>=1.2.12）校验审批表单。
- 典型模式：审批/拒绝后路由、审查并编辑状态、工具内中断（resume 值可覆盖工具参数）、校验人类输入（用条件边循环而非 while True）。
- **关键限制**：节点恢复时**从头重放**（interrupt 前的代码重跑，副作用必须幂等）；不得 try/except 包裹 interrupt；节点内 interrupt 调用顺序不可变（resume 按索引匹配）；静态断点 `interrupt_before/after` 仅建议调试用。

## 8. 权限控制机制

- 框架层**无权限模型**【未找到】。生产部署的鉴权在 LangSmith Deployment 平台侧（未深入抓取）。

## 9. 运行记录 / 持久化

- **Checkpointing 是一等公民**：持久化图状态、断点精确恢复、thread_id 即持久化游标；生产建议用数据库/SqliteSaver 等持久化 checkpointer【官方文档结论】。
- 记忆分两层：thread 内短期状态 + 跨会话长期记忆（Store）【官方文档结论】。
- 可观测性：LangSmith 可视化执行路径、状态转换、运行时指标【已验证-页面抓取】。

## 10. 部署方式

- 作为 Python/JS 库嵌入任意应用；生产部署走 **LangSmith Deployment**（有状态长时工作流托管）【已验证-页面抓取】。

## 11. 实际运行条件

- `pip install -U langgraph`；HITL 需配 checkpointer；`response_schema` 需 langgraph>=1.2.12【官方文档结论】。具体 Python 版本下限：未找到。

## 12. 已知限制

- 低层级：不提供角色/prompt/审批 UI 等上层抽象，一切要自己搭【官方文档结论】。
- interrupt 的重放语义是常见踩坑点（幂等要求、索引匹配、禁 while True 循环）【官方文档结论】。
- 部署/团队协作强绑定 LangSmith（商业平台）；自托管生产服务能力有限【推断】。

## 13. 对 AgentOS 的借鉴价值

**值得借鉴（具体）：**
- **checkpoint + thread_id + interrupt/Command(resume)** 的 HITL 三件套：暂停即持久化、恢复即传值，语义干净，是人工审批机制的最佳参考实现。
- **图模型混合确定性步骤与 LLM 步骤**：编排层不碰 prompt 的分层原则。
- **短期 thread 状态 + 长期 Store** 的记忆分层。
- 节点重放语义（副作用幂等）的文档化规则，值得在设计审批节点时直接沿用。

**不适合照搬：**
- 纯图 API 对业务用户过于低层；AgentOS 需要在其上封装"角色/任务/审批"的概念层（类似其 Deep Agents 的定位）。
- 与 LangSmith 商业平台的耦合部分。

**需自研：**
- 角色/权限/审批 UI、多租户、CLI agent 管理——LangGraph 都只提供原语。

## 14. 分类建议

- **B Agent 工作流框架**（明确）：官方自述即 "low-level orchestration framework and runtime for long-running, stateful agents"【官方文档结论】。
