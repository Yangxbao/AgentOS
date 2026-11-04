# AgentOS 开发路线图

> v0.1｜2026-11-05｜未经用户批准不得跳过里程碑

## M0 技术调研与最小技术验证（当前）
- ✅ 12 个 GitHub 竞品调研、技术栈对比、选型决策
- ✅ PRD / 功能矩阵 / 六份架构文档 / Monorepo 骨架
- 🧪 验证：LiteLLM+DeepSeek、AgentAdapter、双 Agent 顺序协作、LangGraph interrupt、持久化重启保留
- ⚠️ Codex CLI（待用户授权安装）；CrewAI 对照（可选）
- 出口标准：M0_TEST_REPORT 全部真实结果 + M0_FINAL_HANDOFF 14 项汇报

## M1 AI 员工与组织管理（计划已细化，待批准）
- 详细计划：[M1_PLAN.md](M1_PLAN.md)｜PRD：[M1_PRD.md](../product/M1_PRD.md)｜数据：[M1_DATA_MODEL.md](../architecture/M1_DATA_MODEL.md)
- 接口：[M1_API_DESIGN.md](../architecture/M1_API_DESIGN.md)｜前端：[M1_UX_DESIGN.md](../product/M1_UX_DESIGN.md)
- 解耦与派工：[M1_DECOUPLING_AND_ROUTING.md](../architecture/M1_DECOUPLING_AND_ROUTING.md)｜安全：[M1_SECURITY.md](../architecture/M1_SECURITY.md)
- 分批：B1 地基 → B2 组织域 → B3 员工+模型 → B4 提示词/导入导出 → B5 权限+派工预览 → B6 E2E 验收
- 出口：全量 pytest ≥50 通过、三个 E2E 场景真实跑通、M1_TEST_REPORT + M1_HANDOFF

## M2 任务调度与多 Agent 协作
- CEO Agent（澄清→拆解→派工→汇总，参考 Team Leader 分阶段流程）
- 任务状态机完整落地 + 任务 DAG + 依赖调度
- 顺序/并行执行、暂停/恢复/取消/重试、人工接管
- 审批中心（9 类高危动作、风险分级、审批台 UI）
- 项目工作空间（目录授权、ACL）
- MCP host 接入（官方 Python SDK）

## M3 AI 监督系统
- 独立 QA Agent、跨模型交叉审查、结构化审查报告（6 要素）
- 自动打回/返工/返工上限、测试证据、最终验收
- 成本与绩效中心（10 项指标按员工归因、预算护栏）

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
