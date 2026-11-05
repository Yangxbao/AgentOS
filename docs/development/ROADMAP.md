# AgentOS 开发路线图

> v0.1｜2026-11-05｜未经用户批准不得跳过里程碑

## M0 技术调研与最小技术验证（当前）
- ✅ 12 个 GitHub 竞品调研、技术栈对比、选型决策
- ✅ PRD / 功能矩阵 / 六份架构文档 / Monorepo 骨架
- 🧪 验证：LiteLLM+DeepSeek、AgentAdapter、双 Agent 顺序协作、LangGraph interrupt、持久化重启保留
- ⚠️ Codex CLI（待用户授权安装）；CrewAI 对照（可选）
- 出口标准：M0_TEST_REPORT 全部真实结果 + M0_FINAL_HANDOFF 14 项汇报

## M1 AI 员工与组织管理（计划已细化，待批准）
- **全部内容合并为单文档：[../../M1_PLAN_HANDOFF.md](../../M1_PLAN_HANDOFF.md)**
- 分批：B1 地基 → B2 组织域 → B3 员工+模型 → B4 提示词/导入导出 → B5 权限+派工预览 → B6 E2E 验收
- 出口：全量 pytest ≥50 通过、三个 E2E 场景真实跑通、M1 测试报告 + M1 单文档交接
- 约定：交接/计划类文档不再拆分，统一一份

## M2 任务调度与多 Agent 协作（主体完成）
- ✅ 任务状态机 + 任务/子任务统一实体 + 计划 DAG + 依赖调度
- ✅ 顺序/并行执行、暂停/恢复/取消/重试、检查点续跑、重启恢复
- ✅ 人工审批（执行前/交付后双关卡、驳回回退、返工上限）
- ✅ 执行监控与成本归因（时间线、Agent 详情、usage 聚合、monitor）
- ✅ 管理者自动拆分（LLM JSON + 严格校验，不伪造）
- ⏳ 未做：浏览器可视化验收（需授权 Playwright）、真实外部工具执行、多进程 worker、递归拆分
- 设计/证据：[M2_MASTER_PLAN.md](../../M2_MASTER_PLAN.md) · [M2_MASTER_HANDOFF.md](../../M2_MASTER_HANDOFF.md)

## M3 工具化与自主执行（M3-A 已完成）
- ✅ M3-0 浏览器验收 16/16（真实 Edge + CDP，发现并修复 6 个前端/版本缺陷）
- ✅ M3-A 工具执行层：工作区/授权、五层权限、FS/HTTP 安全、工具审批与断点恢复、审计；浏览器验收 29/29（含 M3-A 13 项）；171 个新测试
- ⏳ M3-E 自主与监管：调用/Token/费用上限、风险闸门、异常暂停
- ⏳ M3-B 递归拆分与重规划（≤3 层、总步骤/预算上限）
- ⏳ M3-C 长期记忆（SQLite FTS5，零外部调用）
- ⏳ M3-D 多 Worker（租约/心跳/幂等/公平调度）
- ⏳ M3-F 真实业务验收（GitHub 教程生成，默认本地 stub）
- Shell 执行、向量 RAG、MCP 生态明确暂缓（原因见 M3_MASTER_PLAN §16）
- 设计/交接：[HANDOFF.md](../../HANDOFF.md)（项目总交接）· [M3_MASTER_PLAN.md](../../M3_MASTER_PLAN.md)（M3 设计）

## M4 AI 会议室
- 多 Agent 受控讨论（调度系统控制生命周期）、@成员、召集/主持人
- 会议纪要、结构化决策、决策转任务、异议处理
- 团队模板初版

## M5 本地与云端协作
- 云端账号、设备注册、AgentOS Connector、远程任务调度
- 加密通信（设备证书）、权限同步、断线恢复、文件授权同步
- Docker Compose 部署、PostgreSQL 切换验证

## M6 开放生态
- A2A 协议、自定义 Agent SDK、插件/团队市场、能力评估与智能招聘、高级模型路由
