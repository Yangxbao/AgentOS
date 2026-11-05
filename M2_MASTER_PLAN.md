# AgentOS M2 总体规划（Master Plan）

> 版本：v1.0｜日期：2026-11-05｜状态：M2-0 完成，进入 M2-A
> 依据：`E:\AgentOS` 真实代码、真实数据库、M1 交接文档 §20–§21。
> 本文是**设计基线**；进度、提交、测试数字、未完成项写在 `M2_MASTER_HANDOFF.md`（单一进度文档）。
> 约定：【已验证】= 有代码/实测证据｜【设计】= 本文提出｜【复用】= 直接用 M0/M1 能力，不重造。

---

## 1. 当前架构盘点（真实核对，非报告转述）

### 1.1 代码规模与分层

| 层 | 位置 | 现状 |
|---|---|---|
| API | `apps/api/` | FastAPI；`routers/` 9 个（公司/部门/岗位/员工/连接/提示词/治理/配置/legacy）；`deps.py` 分页+会话+Actor；`errors.py` 统一错误包络 + request_id；`local_guard.py` 本地防护 |
| 领域 | `packages/organization/` | 公司、部门树、岗位、员工（含汇报链/软删）、模型连接、组织树 |
| 权限 | `packages/permissions/` | 三层有效权限（只收窄）、派工硬过滤+评分、双池审查人 T1–T6、审计（脱敏/只增） |
| 提示词 | `packages/prompts/` | 文件外置、不可变版本、SHA-256、激活指针、原子写、对账 |
| 模型 | `packages/model_gateway/` | LiteLLM 封装、供应商目录、凭据引用、健康缓存 |
| 执行体 | `packages/agent_core/` | `AgentAdapter` 协议、`LiteLLMAdapter`（health/execute/stream）、能力交集 |
| 工作流 | `packages/workflow_engine/` | M0 顺序交接（研究员→审查员）、LangGraph interrupt 审批验证 |
| 持久化 | `packages/persistence/` | SQLAlchemy 2.0 + SQLite(WAL)；16 张表；Alembic 6 个 revision |
| 前端 | `apps/web/src/` | React18+TS+Vite+Tailwind4+TanStack Query；8 个页面 |

### 1.2 已有任务相关实体（【复用】不改名、不推倒）

```
task(id, owner_id, title, objective, state, rework_count, max_rework, created_at, updated_at)
task_run(id, task_id, run_no, trigger, state, error, started_at, ended_at)
agent_run(id, task_run_id, employee_key, employee_id, role, adapter_type, model,
          input_payload, output_payload, state, error, external_ref, created_at)
task_event(id, task_id, task_run_id, ts, type, payload)
usage_record(id, agent_run_id, employee_key, employee_id, model, prompt_tokens,
             completion_tokens, cost_usd, latency_ms, billable, created_at)
```

关键既有约束（继续遵守）：
- `task.state` 是状态唯一权威字段，AI 自称完成不改变它；
- 一次执行一条 `task_run`，历史不覆盖；
- `agent_run.model` / `usage_record.model` 是**执行时快照**，员工换模型不改写历史；
- `usage_record.cost_usd` 允许 NULL（计价失败不编造），`billable=false` 用于 Mock；
- `employee_key` 为 M0 遗留字符串，M2 起以 `employee_id` 为主并保留双写。

### 1.3 已有可复用能力（禁止重复造轮子）

| 能力 | 复用方式 |
|---|---|
| 模型调用 | `LiteLLMAdapter.execute/stream_events` + `model_gateway.chat`（已支持连接级 api_key/base_url/timeout/max_retries） |
| 员工身份 | `employee` + `prompt_revision`（`load_active_prompt`）+ `employee_position` + `Position.responsibilities` |
| 模型解析 | `employee.primary_model_id → fallback_model_id`，`credentials.resolve_ref` |
| 权限 | `compute_effective_permissions`（max_risk_level/file_ops/budget）、`employee.tools_allowed` |
| 审查人 | `assignment._reviewer_pool`（T1–T6、跨模型/跨供应商、`can_review`） |
| 派工 | `preview_assignment`（硬过滤 8 条 + 评分 + 决策留痕） |
| 审计 | `write_audit`（脱敏、只增、request_id） |
| 事件 | `task_event`（与审计分离，执行过程用） |
| 前端 | `api/client.ts`、TanStack Query、现有页面样式 |

### 1.4 真实基线（2026-11-05 实测）

- `pytest tests/ -q` → **91 passed**；`ruff` → All checks passed
- 真实库 16 张表：`task` 4（failed 2 / review_passed 2）、`task_run` 4（failed 2 / succeeded 2）、`agent_run` 4、`usage_record` 4；其余 M1 业务表 0 行
- Alembic head：`m1_b5_assignment_audit`
- `.env` 存在 35 位 DeepSeek Key（**未在报告中输出**）；`DEEPSEEK_API_KEY` 运行时由 `load_dotenv` 注入
- 未安装 Playwright / Docker / CrewAI；未推 GitHub

### 1.5 现有缺口（M2 要补的）

1. 任务只有 `title/objective/state`，没有公司、部门、执行人、审核人、优先级、截止、交付标准；
2. 没有“入队 → 后台执行”，只有 M0 脚本式同步执行；
3. 没有暂停/恢复/取消/重试/审批的任何持久化；
4. 没有子任务、依赖、交接、并行；
5. 没有按任务/员工的成本与时间线查询；
6. 执行入口没有强制权限校验（M0 直接调 adapter）。

---

## 2. 目标架构

### 2.1 分层与依赖方向

```
apps/api/routers/tasks.py ─┐
apps/api/routers/monitor.py├─→ packages/tasks/        （任务领域：状态机、CRUD、计划校验）
                           │        │
                           │        ├─→ packages/permissions/guard.py  （执行前权限闸门）
                           │        └─→ packages/prompts/service.py    （系统提示词）
                           │
apps/api/routers/approvals.py ─→ packages/tasks/approvals.py（审批决策）
                           │
packages/execution/runner.py ──→ packages/execution/executor.py ──→ packages/agent_core（Adapter）
        │                              │                                  ↑
        │                              └─→ packages/model_gateway（解析连接/凭据）
        └─→ packages/persistence（task/run/agent_run/event/usage/handoff/approval）
```

依赖规则：
- `packages/tasks` 不 import `apps/api`；
- `packages/execution` 可依赖 `tasks`、`permissions`、`prompts`、`agent_core`，**不反向**；
- API 层只做参数校验、事务边界、审计；业务规则在 packages；
- 执行引擎与业务 API 的边界：**API 只入队/发信号，绝不 await 模型调用**；Runner 独占执行。

### 2.2 新增模块

| 模块 | 职责 |
|---|---|
| `packages/tasks/state.py` | 状态机（合法迁移表 + 终态 + 遗留状态映射） |
| `packages/tasks/service.py` | 任务 CRUD、分配校验、列表/详情、计划设置 |
| `packages/tasks/plan.py` | 计划校验（员工归属/能力/依赖/深度/环/数量） |
| `packages/tasks/approvals.py` | 审批创建/决策/驳回回退点 |
| `packages/execution/adapter_factory.py` | 真实 / Mock Adapter 选择（显式模式，不静默降级） |
| `packages/execution/mock_adapter.py` | 确定性 Mock（含可配置延迟，供并发/暂停测试） |
| `packages/execution/prompting.py` | 系统提示词组装（版本提示词 + 岗位职责 + 交付标准） |
| `packages/execution/guard.py` | 执行前权限/能力/预算校验（失败即拒，不调模型） |
| `packages/execution/executor.py` | 单次 run 执行：拓扑波次、步骤、交接、检查点、计量 |
| `packages/execution/runner.py` | 后台 worker：认领、心跳、恢复、停止 |
| `packages/execution/observability.py` | 时间线合并、成本聚合、脱敏 |

---

## 3. 数据库设计（迁移 `0007_m2_task_center`）

> 全部为**增量列 + 新表**；历史 4 条 task 的 `company_id` 为 NULL，不回填、不改写状态。
> 迁移前自动备份真实库（`scripts/backup_db.py`）。

### 3.1 `task` 新增列

| 列 | 类型 | 说明 |
|---|---|---|
| `company_id` | String(32) NULL, idx | M2 任务归属公司；NULL = M0 遗留任务 |
| `department_id` | String(32) NULL, idx | 执行部门 |
| `parent_task_id` | String(32) NULL, idx | 子任务指向父任务 |
| `root_task_id` | String(32) NULL, idx | 根任务（层级查询） |
| `depth` | Integer default 0 | 0 = 根；最大 3 |
| `assignee_employee_id` | String(32) NULL, idx | 执行员工 |
| `reviewer_employee_id` | String(32) NULL | 审核员工（可空=人工审核） |
| `priority` | String(16) default "normal" | low/normal/high/urgent |
| `due_at` | DateTime NULL | 截止时间 |
| `deliverable` | Text default "" | 交付标准 |
| `instruction` | Text default "" | 本次执行指令（空则用 objective） |
| `context` | JSON default {} | 上游上下文/用户补充 |
| `plan` | JSON default {} | 步骤计划（见 3.4） |
| `result` | JSON default {} | 最终产出摘要 |
| `approval_required` | Boolean default false | 是否需要人工审批 |
| `approval_stage` | String(16) default "before_run" | before_run / after_run |
| `risk_level` | String(16) default "low" | low/medium/high/critical |
| `budget_usd` | Float NULL | 预算上限 |
| `execution_mode` | String(16) default "auto" | auto/real/mock |
| `cancel_requested` | Boolean default false | 取消信号（协作式） |
| `pause_requested` | Boolean default false | 暂停信号（步骤边界生效） |
| `created_by` | String(64) default "local" | 创建者 |
| `started_at` / `ended_at` | DateTime NULL | 执行区间 |
| `version` | Integer default 1 | 乐观锁（替代 updated_at 字符串比较） |

索引：`(company_id, state)`、`(assignee_employee_id, state)`、`(parent_task_id)`。

### 3.2 `task_run` 新增列

| 列 | 类型 | 说明 |
|---|---|---|
| `checkpoint` | JSON default {} | `{completed_steps:[], outputs:{step_id:{...}}, rewind_to:null}` |
| `mode` | String(16) default "real" | 本次实际模式（mock 时 usage.billable=false） |
| `worker_id` | String(64) NULL | 认领者（进程标识） |
| `heartbeat_at` | DateTime NULL | 心跳；启动时用于判定孤儿 |
| `resumed_from_run_id` | String(32) NULL | 恢复来源 |
| `approved_by` | String(64) NULL | 通过审批者 |

**并发唯一约束**：`CREATE UNIQUE INDEX uq_task_run_active ON task_run(task_id) WHERE state IN ('queued','running')`（SQLite/PostgreSQL 部分索引）。这是“防重复执行”的数据库级底线。

### 3.3 新表

**task_approval**（只增）
```
id PK | owner_id | task_id idx | task_run_id NULL | gate(before_run|after_run|step)
status(pending|approved|rejected|changes_requested|cancelled) idx
requested_by | decided_by NULL | comment | rewind_step_id NULL
context JSON | created_at | decided_at NULL
```

**agent_handoff**（只增）
```
id PK | owner_id | task_id idx | task_run_id | from_agent_run_id NULL
to_agent_run_id NULL | step_id | summary TEXT | payload JSON | created_at
```

### 3.4 `plan` JSON 结构

```json
{
  "version": 1,
  "steps": [
    {"id": "s1", "title": "调研", "employee_id": "emp_a",
     "instruction": "输出 3 条要点", "depends_on": [], "deliverable": ""},
    {"id": "s2", "title": "实现", "employee_id": "emp_b",
     "instruction": "基于上游产出实现", "depends_on": ["s1"]}
  ],
  "max_parallel": 4
}
```
校验：步骤 1–20；id 唯一；`depends_on` 必须存在且无环；员工同公司且 active；`depth+1 <= 3`；`max_parallel` 1–8。

---

## 4. 状态机

### 4.1 任务状态

```
                    ┌──────────────────────── cancel ───────────────────────┐
                    │                                                       ▼
draft ──run──> queued ──claim──> running ──ok──> succeeded            cancelled
  │              │  ▲               │  │
  │              │  │               │  └─fail──> failed ──retry──> queued
  │              │  │               ├─pause──> paused ──resume──> queued
  │              │  │               └─gate───> awaiting_approval
  │              │  │                              │      │
  │              │  └──────── approve ─────────────┘      └─reject/request_changes──> rework_required
  │              │                                                                          │
  └─cancel───────┴──────────────────────────── resume/retry ────────────────────────────────┘
```

终态：`succeeded`、`cancelled`。
允许编辑：仅 `draft`（标题/指令/优先级/交付标准/计划）；`queued` 只能取消。
非法迁移统一 `409 TASK_ILLEGAL_TRANSITION`，并返回 `{from, to, allowed[]}`。

遗留状态（M0 历史数据）：`review_passed`、`in_review`、`running` 仅用于展示与取消；
`review_passed` 视为终态，`in_review` 视为可取消的挂起态，不参与新流程。

### 4.2 运行状态（task_run）

`queued → running → succeeded | failed | cancelled | paused | awaiting_approval | interrupted`
- `interrupted`：进程重启时对 `running` 的兜底标记；任务转 `paused`，可恢复。
- 同一 task 同时最多 1 条 `queued|running`（DB 唯一索引）。
- 每次 run 的 `run_no` 递增；恢复生成新 run，携带 `resumed_from_run_id` 与 checkpoint。

### 4.3 步骤状态（checkpoint）

`pending → running → succeeded | failed | skipped`
- 暂停/取消/崩溃时，已完成步骤留在 `completed_steps`；
- 恢复只执行未完成步骤；驳回可指定 `rewind_step_id`，从该步起重置为 pending（下游一并重置）。

---

## 5. API 设计（`/api/v1`）

### 5.1 任务中心（M2-A）

| ID | 方法 | 路径 | 说明 |
|---|---|---|---|
| M2-01 | POST | `/companies/{cid}/tasks` | 创建（校验员工/部门/审核人归属） |
| M2-02 | GET | `/companies/{cid}/tasks` | 列表：state/assignee/department/parent/q/分页 |
| M2-03 | GET | `/tasks/{id}` | 详情（含计划、子任务、最近 run、待审批、成本摘要） |
| M2-04 | PATCH | `/tasks/{id}` | 编辑（仅 draft；`version` 乐观锁） |
| M2-05 | POST | `/tasks/{id}/cancel` | 取消（排队即取消；运行中置信号） |
| M2-06 | POST | `/tasks/{id}/run` | 入队（防重复：有活跃 run → 409） |
| M2-07 | POST | `/tasks/{id}/pause` | 暂停（步骤边界生效；无运行 → 409） |
| M2-08 | POST | `/tasks/{id}/resume` | 恢复（paused/interrupted） |
| M2-09 | POST | `/tasks/{id}/retry` | 重试（failed/cancelled/rework_required） |
| M2-10 | PUT | `/tasks/{id}/plan` | 设置/替换计划（仅 draft，校验后建子任务） |
| M2-11 | POST | `/tasks/{id}/decompose` | 由管理者模型自动拆分（失败不伪造） |
| M2-12 | GET | `/tasks/{id}/events` | 事件流（ts 升序/分页） |
| M2-13 | GET | `/tasks/{id}/runs` | 运行历史（含 agent runs 与 usage） |
| M2-14 | GET | `/tasks/{id}/usage` | 本任务 token/成本聚合 |

### 5.2 审批（M2-D）

| ID | 方法 | 路径 | 说明 |
|---|---|---|---|
| M2-15 | GET | `/tasks/{id}/approvals` | 审批列表 |
| M2-16 | POST | `/approvals/{id}/decision` | `{decision: approve\|reject\|request_changes, comment, rewind_step_id}` |
| M2-17 | GET | `/approvals?status=pending` | 待办审批 |

### 5.3 监控（M2-E）

| ID | 方法 | 路径 | 说明 |
|---|---|---|---|
| M2-18 | GET | `/tasks/{id}/timeline` | 时间线（事件+agent run+审批+交接，统一排序） |
| M2-19 | GET | `/agent-runs/{id}` | 单次员工执行详情（输入/输出/错误/usage） |
| M2-20 | GET | `/usage` | 按 task/employee/company/时间聚合（含日汇总） |
| M2-21 | GET | `/monitor/summary` | 任务状态分布、进行中、今日成本、失败数 |

错误码（新增）：`TASK_ILLEGAL_TRANSITION`、`TASK_NOT_EDITABLE`、`TASK_ACTIVE_RUN_EXISTS`、
`TASK_PLAN_INVALID`、`TASK_PLAN_CYCLE`、`TASK_PLAN_TOO_DEEP`、`TASK_ASSIGNEE_INVALID`、
`APPROVAL_NOT_PENDING`、`APPROVAL_REVIEWER_INVALID`、`EXECUTION_PERMISSION_DENIED`、
`EXECUTION_MODEL_UNAVAILABLE`、`EXECUTION_BUDGET_EXCEEDED`。

---

## 6. 核心时序

### 6.1 单任务执行（M2-B）

```
POST /tasks/{id}/run
  → 校验状态(draft|paused|failed|rework_required)
  → 建 task_run(queued, run_no+1)  [唯一索引挡重复]
  → task.state=queued, event=task.queued
  → 返回 202 {run_id}

Runner loop（1s 轮询 + kick 事件）
  → UPDATE task_run SET state='running', worker_id, heartbeat WHERE state='queued'（rowcount=1）
  → task.state=running, started_at
  → guard.check()：员工 active / 模型可用 / 风险 ≤ 权限 / 工具 ⊆ 授权 / 预算
        └─ 失败：run=failed, task=failed, event=execution.blocked（不调模型）
  → 需要审批且无 approved → task=awaiting_approval, approval(pending), run=awaiting_approval（释放 worker）
  → 执行步骤（拓扑波次）：
        组装 system prompt（激活版本 + 岗位职责 + 交付标准）
        adapter.execute/stream → content + usage
        AgentRun(step_id, employee_id, model 快照, prompt_version)
        UsageRecord(billable = mode=='real')
        子任务状态、TaskEvent(agent.completed)
        交接：AgentHandoff(prev→cur, summary)
        checkpoint 落库（每个步骤提交一次）
  → 全部完成：task.result、task=succeeded、run=succeeded
```

### 6.2 暂停 / 恢复

```
POST /pause → task.pause_requested=true（运行中）或 409
Runner 在步骤边界检查：
  → run.state=paused, task.state=paused, checkpoint 保留, event=run.paused
POST /resume → 新 run（resumed_from_run_id），checkpoint.completed_steps 跳过
```

### 6.3 审批 / 驳回

```
before_run:
  run 开始 → 无 approved → awaiting_approval + approval(pending)
POST /approvals/{id}/decision approve
  → approval.status=approved, task.state=queued, 入队新 run
reject/request_changes（可带 rewind_step_id）
  → approval.status=rejected, task.state=rework_required, rework_count+1
  → checkpoint 从 rewind 步起重置；超过 max_rework → 409 TASK_REWORK_LIMIT
POST /resume → 新 run 从回退点重新执行（已完成的上游步骤不重复）
```

### 6.4 重启恢复

```
lifespan 启动 → runner.recover()
  → 所有 state='running' 的 run → 'interrupted', ended_at, event=run.interrupted
  → 对应 task：若有未完成步骤 → paused；否则 succeeded/failed 按 checkpoint 判定
  → 不自动重跑（避免重复扣费），由用户 resume/retry
```

---

## 7. 权限与安全（延续 M1）

| 闸门 | 位置 | 规则 |
|---|---|---|
| API 管理权限 | 路由 | M1 本地用户；公司归属校验；任务必须属于该 owner/company |
| 执行入口 | `execution/guard.py` | 员工 active、未删除、同公司；模型 enabled 且有凭据；risk ≤ 有效 `max_risk_level`；`required_tools ⊆ tools_allowed`；预算 ≥ 估算 |
| 工具调用 | M2 不实际调用外部工具 | 仍校验并记录 `authorized_tools`；工具调用记录字段预留 |
| 审批人 | `tasks/approvals.py` | 人工用户可直接审批；若指定员工审批，必须 `can_review` 且 ≠ 执行人 |
| Agent 侧 | 不存在 `/agent-api` | M2 仍不开放 Agent 写接口 |
| 脱敏 | `observability` / `audit` | 输出/事件/成本查询统一 `redact`；密钥永不入库 |

---

## 8. 前端规划

| 路由 | 页面 | 要点 |
|---|---|---|
| `/tasks` | 任务中心 | 状态筛选、创建抽屉（公司/部门/员工/优先级/截止/交付标准/是否审批）、列表轮询 |
| `/tasks/:id` | 任务详情 | 状态徽标 + 动作条（运行/暂停/恢复/取消/重试）、计划编辑器、子任务树、审批卡片、执行时间线、Agent 执行明细、成本汇总 |
| `/monitor` | 执行监控 | 状态分布、今日成本、失败任务、最近运行、按员工/时间筛选 |
| 导航 | — | 新增「任务中心」「执行监控」，置顶到组织架构之前 |

轮询策略：运行中任务 2s 刷新，终态停止；时间线 3s；不做 WebSocket（M2 范围外，避免新依赖）。

---

## 9. 开发顺序与验收

| 阶段 | 范围 | 验收（必须真实执行） |
|---|---|---|
| **M2-A** | 迁移、状态机、任务 CRUD/分配/列表/详情、计划校验 | 创建→刷新仍在；非法迁移 409；跨公司/不存在员工 422/404；乐观锁 409 |
| **M2-B** | Adapter 工厂、Mock、guard、Runner、执行、重试/取消/暂停、重启恢复 | Mock 单员工任务成功；真实模式无凭据时明确失败；重复 run 409；重启标记 interrupted → resume 可续 |
| **M2-C** | 计划、子任务、依赖波次、并行、交接、深度/环限制 | 3 员工串行依赖任务产出统一结果；并行波次真实并发；交接记录可查；超深/成环被拒 |
| **M2-D** | 审批、暂停/恢复、驳回回退 | 暂停→恢复不重复已完成步骤；审批→恢复成功；驳回→回到指定员工→重提成功 |
| **M2-E** | 时间线、agent run 详情、usage 聚合、monitor summary、前端页面 | 单任务可追踪完整过程；成本合计 = usage 之和；密钥不出现 |
| **M2-F** | E2E 脚本（Mock 全流程 + 一次真实最小调用）、构建、文档 | 10 项验收逐条有证据；真实调用记录模型/tokens/成本；浏览器构建通过 |

每阶段：跑全量 pytest + ruff + 前端构建；更新 `M2_MASTER_HANDOFF.md`；独立 commit。

---

## 10. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| SQLite 并发写 | 并行步骤 `database is locked` | WAL + `timeout=30` + 写段 `asyncio.Lock`；并行仅用于模型调用 |
| 后台任务吞异常 | 任务卡在 running | 全链路 try/except → failed + event；启动时 `recover()` 兜底 |
| 重复执行/重复扣费 | 成本与结果错乱 | 部分唯一索引 + 原子认领 + 幂等检查 |
| Mock 被误当真实 | 验收失真 | `usage.billable=false`、`task_run.mode=mock`、UI 明示、报告分列 |
| 真实调用费用 | 少量 token | 仅 M2-F 一次，`max_tokens<=64`，记录实际成本 |
| 迁移破坏历史 | 数据丢失 | 迁移前 `backup_db.py`；只加列/新表；不 downgrade 真实库 |
| 状态机与 M0 遗留冲突 | 历史任务打不开 | 遗留状态只读映射，不迁移状态值 |
| 审批绕过 | 权限风险 | 审批必须 pending + 决策人校验 + 审计 |
| 前端轮询压力 | 本地资源 | 仅运行中轮询，终态停止 |

**回滚方案**：每个阶段独立 commit；迁移只向前；如需回退代码，保留数据库向后兼容（新表/新列可闲置）。真实库回滚使用 `data/backups/pre_m2_*.db` 副本，不在真实库执行 downgrade。

---

## 11. 明确不做（M2 范围外）

- 真实外部工具执行（文件/Shell/网络）——只做权限校验与记录，执行留 M3；
- WebSocket/SSE 实时推送（用轮询）；
- 多进程/分布式 worker、Redis 队列；
- Agent 自主无限循环、自动招聘、自动改权限；
- 浏览器自动化验收（未安装 Playwright，需授权）；
- GitHub 推送、公网部署。

---

## 12. 实施偏差记录（M2 实现后回填）

| # | 计划 | 实际 | 原因 |
|---|---|---|---|
| 1 | 支持 depth ≤3 的递归拆分 | **只支持一层**：父任务 → 步骤子任务；`depth` 上限仅作防御性校验 | 递归执行会让检查点、审查链、成本归属复杂度翻倍；M2-C 验收只要求一层多 Agent 协作。递归拆分留 M3，并在测试中明确子任务不可再设计划 |
| 2 | 用 `updated_at` 乐观锁 | 新增 `task.version` 整数乐观锁 | `updated_at` 精度受 SQLite 影响，整数版本更可靠；其他 M1 资源不变 |
| 3 | 状态机未列 `pending/skipped` | 增加 `pending`（子任务待调度）与 `skipped`（终态预留） | 子任务需要区别于 draft/queued 的语义 |
| 4 | 审批人必须符合 M1 审核规则 | 人工用户可直接审批；若指定员工审批，创建时校验 `can_review` 且 ≠ 执行人 | 本地单用户场景下“人工审批”主体是用户本人；员工审查资格用于指定审查人 |
| 5 | before_run 审批每次执行都要过 | 首次必过；已被人工决策过的返工/重试不再重复拦 | 驳回本身已是人工介入，避免同一任务每次重跑都重复审批；after_run 仍每次交付都签收 |
| 6 | 真实调用留待人工 | M2-F 共执行 4 次最小真实调用（两次单步 + 一次两步协作），合计 353 tokens、$0.00006285 | 用户任务书第 9 项要求真实模型全流程；使用已有 Key、`max_tokens=96`、不新增付费服务 |
| 7 | 浏览器验收 | **未执行**（约束禁止安装 Playwright） | 已在 HANDOFF 标记为未验证项，不伪造 |

