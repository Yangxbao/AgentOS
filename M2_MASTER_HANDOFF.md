# AgentOS M2 交接与进度（Master Handoff）

> 版本：v1.0｜日期：2026-11-05｜状态：**M2 主体完成（M2-A ~ M2-F），浏览器可视化验收未执行**
> 设计基线：`M2_MASTER_PLAN.md`（含 §12 实施偏差）。本文只记进度、证据、风险与下一步。
> 数字全部来自本机真实执行；命令与原始输出见 `docs/testing/m2_final_regression.txt`、`m2_e2e_mock.txt`、`m2_e2e_real.txt`。

---

## 1. 结论摘要

| 项 | 结果 |
|---|---|
| 任务中心 | 可创建/编辑/取消、分配部门员工、优先级/截止/交付标准、状态机、列表详情、计划与子任务 |
| 执行引擎 | 后台队列真实执行；Mock 与真实模型双通道；权限闸门；超时/失败/重试/取消/暂停/恢复；重启恢复 |
| 多 Agent | 3 员工串行交接 + 依赖波次并行；交接记录可查；自动拆分带严格校验 |
| 人工审批 | before_run / after_run 双关卡；批准 / 驳回 / 要求修改；驳回可指定回退步骤；返工上限 |
| 监控 | 任务时间线、Agent 执行详情、Token/成本聚合、监控摘要；Mock 明确标记不计费 |
| 自动化测试 | **128 passed**（M2 新增 37） |
| E2E | Mock 全流程 **13 项通过**；含真实最小调用 **15 项通过** |
| lint / 构建 | ruff 全绿；前端 `tsc -b && vite build` 通过（467.02 kB，gzip 144.79） |
| 数据库 | 18 张表；真实库已迁移到 `m2_task_center`；历史 4 任务/4 run 未动 |
| 真实模型 | 2 次最小调用（每次 73+5 tokens，$0.00001395），合计 ≈ **$0.0000279** |
| 浏览器验收 | **未执行**（未安装 Playwright，按约束不安装）；已列为未验证项 |

---

## 2. 阶段状态

| 阶段 | 内容 | 状态 | 证据 |
|---|---|---|---|
| M2-0 | 架构盘点、目标架构、数据/API/状态机/时序/风险 | **完成** | `M2_MASTER_PLAN.md` |
| M2-A | 任务中心：CRUD、分配、状态机、计划、列表详情 | **完成** | `tests/test_task_center.py`（8） |
| M2-B | 执行引擎：Adapter 工厂、Mock、权限闸门、Runner、恢复、重试/取消/暂停 | **完成** | `tests/test_execution.py`（10） |
| M2-C | 多 Agent：计划、依赖、并行、交接、自动拆分 | **完成** | `tests/test_collaboration.py`（7） |
| M2-D | 审批：双关卡、批准/驳回/回退、返工上限 | **完成** | `tests/test_approvals.py`（6） |
| M2-E | 监控：时间线、执行详情、成本聚合、摘要 | **完成** | `tests/test_observability.py`（6） |
| M2-F | 端到端、真实调用、构建、文档 | **完成（除浏览器验收）** | `scripts/e2e_m2.py`、`docs/testing/*` |

---

## 3. 数据库与迁移

迁移：`migrations/versions/0007_m2_task_center.py`（revision `m2_task_center`，父 `m1_b5_assignment_audit`）

### 3.1 变更

| 表 | 变更 |
|---|---|
| `task` | +25 列：company/department/parent/root/depth、assignee/reviewer、priority/due_at/deliverable/instruction、context/plan/result、approval_required/stage、risk_level/budget_usd、execution_mode、cancel_requested/pause_requested、created_by、started_at/ended_at、version |
| `task_run` | +checkpoint、mode、worker_id、heartbeat_at、resumed_from_run_id、approved_by |
| `agent_run` | +step_id、prompt_version、model_connection_id、started_at、ended_at |
| `task_approval` | 新表：gate/status/reviewer/decided_by/comment/rewind_step_id/context |
| `agent_handoff` | 新表：from/to agent_run、step_id、summary、payload |
| 索引 | `uq_task_run_active`（部分唯一：同一 task 仅一条 queued/running）、`(company_id,state)`、`(assignee_employee_id,state)` |

### 3.2 迁移安全

- 迁移前备份：`data/backups/agentos_20261105_195213/`
- 空库与旧库副本各验证一次，再对真实库执行向前迁移
- 真实库结果：18 表；`task` 4、`task_run` 4、`agent_run` 4、`usage_record` 4 全部保留；
  `company/employee/task_approval/agent_handoff` 均为 0；revision=`m2_task_center`
- **未执行 downgrade**；回滚依赖备份副本，不在真实库跑降级

---

## 4. API（M2-01..21，全部实现）

| ID | 方法 | 路径 |
|---|---|---|
| 01 | POST | `/api/v1/companies/{cid}/tasks` |
| 02 | GET | `/api/v1/companies/{cid}/tasks` |
| 03 | GET | `/api/v1/tasks/{id}` |
| 04 | PATCH | `/api/v1/tasks/{id}` |
| 05 | POST | `/api/v1/tasks/{id}/cancel` |
| 06 | POST | `/api/v1/tasks/{id}/run` |
| 07 | POST | `/api/v1/tasks/{id}/pause` |
| 08 | POST | `/api/v1/tasks/{id}/resume` |
| 09 | POST | `/api/v1/tasks/{id}/retry` |
| 10 | PUT | `/api/v1/tasks/{id}/plan` |
| 11 | POST | `/api/v1/tasks/{id}/decompose` |
| 12 | GET | `/api/v1/tasks/{id}/approvals` |
| 13 | GET | `/api/v1/approvals?status_filter=&company_id=` |
| 14 | POST | `/api/v1/approvals/{id}/decision` |
| 15 | GET | `/api/v1/tasks/{id}/timeline` |
| 16 | GET | `/api/v1/tasks/{id}/runs` |
| 17 | GET | `/api/v1/tasks/{id}/usage` |
| 18 | GET | `/api/v1/agent-runs/{id}` |
| 19 | GET | `/api/v1/usage?company_id=&task_id=&employee_id=&date_from=&date_to=` |
| 20 | GET | `/api/v1/monitor/summary?company_id=` |
| 21 | GET | `/api/v1/approvals/{id}` |

新增错误码：`TASK_ILLEGAL_TRANSITION`、`TASK_NOT_EDITABLE`、`TASK_ACTIVE_RUN_EXISTS`、
`TASK_PLAN_INVALID`、`TASK_PLAN_CYCLE`、`TASK_PLAN_TOO_DEEP`、`TASK_ASSIGNEE_INVALID`、
`APPROVAL_NOT_PENDING`、`APPROVAL_REVIEWER_INVALID`、`EXECUTION_PERMISSION_DENIED`、
`EXECUTION_MODEL_UNAVAILABLE`、`EXECUTION_BUDGET_EXCEEDED`、`EXECUTION_FAILED`、
`DECOMPOSE_PARSE_FAILED`、`DECOMPOSE_FAILED`、`TASK_REWORK_LIMIT`。

---

## 5. 执行语义（实现事实）

1. **入队即返回**：`POST /run` 只写 `task_run(queued)` 并返回 202，不 await 模型。
2. **防重复**：`_active_run` 检查 + `uq_task_run_active` 部分唯一索引 + 原子认领（`UPDATE ... WHERE state='queued'`）。
3. **权限闸门**：员工在职/同公司、模型可用、风险 ≤ 有效 `max_risk_level`、步骤工具 ⊆ `tools_allowed`、预算估算。
   任一项失败 → `failed` + `run.failed` 事件，**不产生 AgentRun/Usage**。
4. **检查点**：每个步骤成功即提交 `checkpoint.completed_steps/outputs`；恢复只跑未完成步骤。
5. **暂停/取消**：在步骤边界生效；正在进行的 LLM 调用不可中断（Adapter 能力如实声明）。
6. **重启**：lifespan `runner.recover()` 把遗留 `running` 标记 `interrupted`，任务转 `paused`；用户 resume 后从检查点续跑。
7. **审批**：before_run 首次必过（已有驳回/批准决策的返工不再重复拦）；after_run 每次交付都签收。
8. **驳回回退**：`rewind_step_id` 指定步骤及其下游重置，上游产出保留；`rework_count` 超限返回 409。
9. **真实/Mock 分离**：`task.execution_mode`（auto/real/mock）+ `AGENTOS_MODEL_MODE`；Mock 的 `usage_record.billable=false`、`cost=0`、模型 `mock/echo`。
10. **规划调用也记账**：自动拆分作为 `task_run.trigger=plan` + `agent_run.step_id=decompose` 记录，成本进入 usage。

---

## 6. 测试与证据

### 6.1 自动化测试（`docs/testing/m2_final_regression.txt`）

```
pytest tests/ -q                                  → 128 passed in 33.26s
ruff check apps packages scripts tests migrations  → All checks passed!
cd apps/web && npm run build                      → 467.02 kB (gzip 144.79), 813ms
alembic current                                   → m2_task_center (head)
reconcile_prompts.py                              → 0 orphan / 0 missing / 0 mismatch
```

M2 新增 37 个：
- `test_task_center.py` 8：持久化、筛选、分配/审核校验、乐观锁、非法迁移、防重复、计划校验、404
- `test_execution.py` 10：Mock 成功、工具越权、风险超限、真实模式缺凭据、停用后重试、注入失败、暂停恢复不重复、运行中取消、重启恢复、提示词版本
- `test_collaboration.py` 7：3 员工串行交接、并行波次（started_at 重叠）、重复/空步骤、自动拆分成功/坏 JSON 不伪造/非管理者/成环
- `test_approvals.py` 6：before_run、after_run 不重跑、驳回回退、返工上限、待审批取消、待办列表
- `test_observability.py` 6：时间线、成本一致、Agent 详情、监控摘要、时间过滤、无密钥泄露

### 6.2 E2E

| 轮次 | 证据 | 结果 |
|---|---|---|
| Mock | `docs/testing/m2_e2e_mock.txt` | 13 项全过（S1 单 Agent / S2 三员工 / S3 审批 / S4 驳回 / S5 失败与取消 / S6 重启 / S7 权限） |
| 含真实调用 | `docs/testing/m2_e2e_real.txt` | 15 项全过（+S8 真实模型、真实计费） |

---

## 7. Mock 与真实模型（严格区分）

| 项 | Mock | 真实 |
|---|---|---|
| 触发 | `execution_mode=mock` 或 `AGENTOS_MODEL_MODE=mock` | `execution_mode=real` 或 auto 且未设 mock |
| 模型标识 | `mock/echo`（adapter_type=`mock`） | 连接里的 `provider/model` |
| 计费 | `usage_record.billable=false`，cost=0 | `billable=true`，`litellm.completion_cost`，失败为 NULL |
| 外部请求 | 无 | 有 |
| 本轮实际调用 | 测试与 E2E 中所有执行步骤（未逐次统计总数，均为本地 Mock，无外部请求） | **2 次**，DeepSeek，每次 73+5 tokens，$0.00001395，合计 ≈ $0.0000279 |

> 真实调用只用 `.env` 已有 Key，`AGENTOS_MAX_TOKENS=96`，未新增任何付费服务。

---

## 8. 未完成 / 未验证（如实列出）

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | **浏览器真实操作验收** | **未执行** | 约束禁止安装 Playwright；只做了 `npm run build` 与 API 合同验证。手工验收步骤见 §9 |
| 2 | 递归拆分（depth>1） | 未做 | M2 只支持一层父→子；`TASK_PLAN_TOO_DEEP` 为防御性校验（见 PLAN §12） |
| 3 | 工具实际执行（文件/Shell/网络） | 未做 | 只做授权校验与记录，M3 |
| 4 | SSE/WebSocket 实时推送 | 未做 | 前端 1.5–3s 轮询 |
| 5 | 多进程/分布式 worker | 未做 | 单进程假设；启动时会回收本进程外的 running |
| 6 | Agent 侧 `/agent-api` | 未做 | 按 BR-12 不开放 |
| 7 | 真实多供应商 | 未验证 | 只有 DeepSeek 一个可用配置 |
| 8 | 自动拆分的真实模型质量 | 未验证 | 真实模式可跑，但本轮只用 stub 验证解析与校验 |

---

## 9. 手工验收步骤（浏览器，需要用户操作）

```bash
cd E:\AgentOS
.venv\Scripts\python.exe scripts\run_api.py --port 8000     # 终端 1
cd apps\web && npm run dev                                  # 终端 2（默认 5173）
```

打开 `http://127.0.0.1:5173`：
1. 组织设置 → 建公司/部门/岗位；AI 员工 → 建 3 名员工（至少一名有 `can_review`、一名 `is_managerial`）
2. 模型连接 → 新增连接（`api_key_ref` 用 `env:DEEPSEEK_API_KEY`）→ 点“测试连接”（会产生一次极小真实调用）
3. 任务中心 → 新建任务（勾选执行前审批）→ 详情 → 执行 → 应停在“待审批”
4. 批准 → 自动继续 → 完成后查看时间线/执行记录/成本明细
5. 再建一个“交付后审批”任务 → 执行完 → 驳回并指定回退步骤 → 恢复 → 再次审批通过
6. 执行监控 → 查看状态分布、最近 Agent 执行、今日成本

---

## 10. 风险分级

| 级别 | 项 | 处理 |
|---|---|---|
| P0 | 无 | — |
| P1 | 浏览器验收缺失 | 需授权安装 Playwright 或人工按 §9 验收 |
| P1 | 单进程假设 | 多进程部署会重复认领；M3 若上多进程需加 DB 租约/Redis 队列 |
| P1 | 进行中的模型调用不可中断 | 已在 UI/文档声明；取消在步骤边界生效 |
| P2 | 自动拆分质量依赖模型 | 有严格校验兜底；失败不伪造 |
| P2 | 成本估算为静态档位 | `EXECUTION_BUDGET_EXCEEDED` 是估算非账单；真实成本以 usage 为准 |
| P2 | 子任务不可单独重跑 | 返工走父任务 rewind；M3 可细化 |
| P2 | Task 与 company 的 FK 对 M0 遗留为 NULL | 历史任务不出现在 M2 列表；legacy `/api/tasks` 仍可读 |

---

## 11. Git / 工作区 / 数据库

```
39c064e docs(m2): 规划、交接、测试证据、README/CHANGELOG/ROADMAP
2a5978e feat(m2-web): 任务中心、任务详情、执行监控页面
dcb68f5 feat(m2): 任务中心 + 执行引擎 + 多 Agent 协作 + 审批 + 监控（后端）
```
- 工作区：提交后干净；未推 GitHub；未安装 Playwright/Docker/CrewAI
- 真实库：18 表，revision `m2_task_center`，历史 4 任务/4 run 原样
- 备份：`data/backups/agentos_20261105_195213/`

---

## 12. M3 建议（按优先级）

1. **补齐浏览器验收**（授权后装 Playwright，或用现有浏览器扩展），把 §9 流程自动化。
2. **工具执行层**：文件读写/HTTP 工具，必须复用 `guard.py` 的授权模型，并把每次工具调用写进 `task_event`。
3. **多进程 worker**：DB 租约或 Redis 队列；心跳超时自动回收 `interrupted`。
4. **递归拆分**：让子任务可再设计划，执行器递归执行，检查点按路径（`s1.s2`）组织。
5. **成本预算硬约束**：按实时累计成本熔断，而不是仅按静态档位估算。
6. **Agent 侧 API**：`/agent-api` 独立命名空间，物理隔离管理接口。
7. **前端实时化**：SSE 替代轮询；任务详情增量刷新。
