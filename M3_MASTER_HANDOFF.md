# AgentOS M3 批次主交接文档（唯一交接入口 · 最终交付版）

> 本文档是 M3 批次（M3-A/E/B/C/D/F）的唯一交接与验收文档，按总任务书要求的 14 个章节组织。
> 状态图例：✅已实现且测试通过｜🟡已实现但未充分验证｜♻️已有机制本次回归确认｜⬜未实现｜🚫因授权限制未执行
> 项目基础信息（环境/红线/坑清单）见 `HANDOFF.md`；M3 设计依据见 `M3_MASTER_PLAN.md`。

---

## 1. 实际完成的功能

### M3-E 执行监管闸门 ✅
- **预算熔断**：按 `usage_record` 真实累计 cost+tokens；步骤开始前、每轮模型响应后、每次工具调用后检查（循环内未落库消耗按 pending 计入）；超限任务转 `paused`（保留检查点可续跑）+ 事件 `task.budget_exceeded`。限额：`task.budget_usd` → 公司 `policy.default_budget_usd`；Token 上限 `policy.default_task_budget_tokens`
- **连续拒绝熔断**：同一 run 内连续 3 次工具被拒（无成功结果间隔）→ `paused` + `task.tool_denied_limit`，提示检查授权；计数存 `run.checkpoint.denied_count`，任何非拒绝终态归零
- **全局 kill switch**：`GET/POST /api/v1/system/tool-execution`；进程级立即生效 + 审计留痕；重启回到 `AGENTOS_TOOL_EXECUTION` 初始值；必需工具+全局关闭 → 任务可读失败（`TOOLS_DISABLED`），不降级假成功
- **监控统计**：`/monitor` 摘要 + 前端页面新增工具统计、拒绝原因 Top N、预算使用率、开关卡片（一键紧急停止/恢复）
- **真实模型链路验证（2026-11-07）**：DeepSeek 真实调用 fs.list_dir/fs.read_file 成功（nonce 防编造通过，$0.0005）；连续拒绝熔断在真实链路首次真实生效。详见 docs/acceptance/2026-11-07_真实模型工具调用验证.md
- ♻️ 单步 8 次上限、工具输出截断（M3-A 既有，回归确认）
- 修复：审批恢复后 `tool_state` 残留 checkpoint 的 M3-A 隐性 bug

### M3-B 递归任务拆分与动态计划 ✅
- 任务树：pending 子任务可设计划（保留 `plan.step_id` 关联标记），父执行器 `_run_nested_step` 用 nested run（trigger=nested）驱动子计划波次；检查点在子 run 上，断点续跑
- **上限后端强制**：深度 ≤4 层（`TASK_DEPTH_EXCEEDED`，任务级 `max_depth` 1–4 可配）、树总步骤 ≤50（`TASK_STEP_BUDGET_EXCEEDED`）、树总工具调用 ≤100（`TOOL_LOOP_EXCEEDED`）
- **动态分配**：步骤省略 `employee_id` → `preview_assignment()` 自动选人并记录 `assignment_decision`
- **replan**：`POST /tasks/{id}/replan`（≤3 次，`TASK_REPLAN_LIMIT`），只重置失败步骤及下游、上游产出保留；计划版本历史 `GET /tasks/{id}/plan-revisions`（`task_plan_revision` 表）
- **父子预算**：限额取祖先链最紧预算、消耗按整树聚合（`budget.limits_for/spent_for_tree`），递归无法逃避预算
- 失败传播：孙步骤失败 → 子任务 failed → 父任务 failed；已完成上游保留，重试只补下游
- 子计划内工具审批 → 父任务同步 `awaiting_approval`，批准后恢复

### M3-C 长期记忆 ✅
- `memory_item` + SQLite FTS5（`memory_fts`，rowid 对齐；FTS5 不可用时 LIKE 降级）；零外部调用、零费用
- 作用域：employee 私有（**跨员工永不互读**）/ project 同公司 / company 全公司；提升仅本地人工且写审计
- 写入脱敏（sk-/Bearer/AKIA 等密钥形态）+ 去重（同内容返回已存在）+ 软删（检索不到、FTS 无残留）
- 执行注入：`retrieve_for_step` 把相关记忆包成 `<memory>` 数据块进**用户消息**（top5/条≤1200 字/总≤4000 字），system prompt 固定"记忆是数据不是指令"声明；无记忆正常降级
- Agent 工具：`memory.remember`（只能写私有作用域）/ `memory.search`（员工视角可见性），走五层权限，类别 `memory` 默认关闭
- 前端记忆中心（`/settings/memory`）：作用域过滤、FTS 检索、写入、提升、删除

### M3-D 多 Worker ✅
- 原子认领：`UPDATE ... WHERE state='queued'`，rowcount=1 才算成功；认领即写租约（`lease_owner/lease_expires_at=now+60s/attempt+1/priority 快照`）
- 心跳 15s 续租；巡检 30s：租约过期 attempt<3 → `interrupted`+任务 `paused`（事件 `run.lease_expired`，可恢复）；attempt≥3 → failed（`LEASE_EXHAUSTED`）
- 启动恢复只处理租约过期或 NULL（M2 遗留行沿用"进程重启"文案），**不误伤**存活 worker
- `AGENTOS_WORKER_CONCURRENCY`（默认 2）单进程并发；公司 `policy.max_concurrent_tasks`（默认 2）超出排队；优先级 urgent>high>normal>low
- API：`GET /workers`（在线 worker/租约/心跳/队列深度）、`GET /workers/stats`
- 与暂停/审批/预算/取消机制兼容（run 生命周期测试覆盖）

### M3-F 端到端业务验收 ✅
- `scripts/e2e_m3f.py`：GitHub 教程场景——研究（HTTP 工具**真实访问本地 GitHub stub**，白名单/SSRF 校验生效）→ 分析 → 写作（**真实写入**工作区 `tutorial.md`，含来源链接）→ 审查（can_review 且≠执行人，**真实读取**）→ after_run 人工审批 → 交付；时间线/成本/工具调用审计可查
- 失败场景：域名不在白名单（`TOOL_NETWORK_DENIED`）、路径越界（`TOOL_PATH_DENIED`，工作区外无文件）、覆盖审批驳回（`TOOL_APPROVAL_REJECTED`，原文未覆盖）
- **诚实边界**：模型为 Mock；GitHub 数据来自本地 HTTP stub（`127.0.0.1:18099`，内容明示为固定数据）；无真实外网、无真实费用

### 状态分类汇总
- ✅ 已实现且测试通过：上述全部功能（332 pytest + 13 M2 E2E + 16 M3-F E2E + 29 浏览器验收）
- 🟡 已实现但未充分验证：**真实模型链路**（2026-11-07 单员工只读文件工具已真实验证 ✅ 并修复三层缺陷；多步协作/递归/审批挂起恢复/HTTP 与记忆工具的真实模型行为仍未验证）；FTS5 的 bm25 排序质量（只验证了命中/隔离/上限，未验证排序相关性）
- ♻️ 已有机制本次回归确认：路径安全、敏感文件拒绝、SSRF/重定向校验、五层权限拒绝码、Shell 禁用、8 次上限、输出截断（M3-A 全部安全测试通过未改动）
- ⬜ 未实现：M4 及以后（账号体系等）；记忆的 embedding 向量检索（按设计默认关闭，未实现）
- 🚫 因授权限制未执行：真实模型调用、真实 GitHub/外网访问、Git Push（见 §12）

---

## 2. 各模块实现位置

| 模块 | 文件 |
|---|---|
| M3-E 预算 | `packages/execution/budget.py`（树感知：`limits_for/spent_for_tree/tree_tool_calls/check`） |
| M3-E kill switch | `packages/tools/policy.py`（`set_tool_execution/tool_execution_state`）+ `apps/api/routers/system.py` |
| M3-E 暂停管道 | `packages/execution/executor.py`（`PAUSE_CODES`/`_pause_for_guard`）、`tool_loop.py`（denied 计数/pending 预算检查） |
| M3-B 计划/递归 | `packages/tasks/plan.py`（深度/自动分配）、`service.py`（`set_plan/replan/_tree_step_total`）、`executor.py`（`_run_step` 调度器/`_run_nested_step/_enqueue_nested_run`） |
| M3-C 记忆 | `packages/memory/service.py`、`packages/tools/memory.py`、`apps/api/routers/memory.py`、`apps/web/src/pages/MemoryPage.tsx` |
| M3-D Worker | `packages/execution/runner.py`（claim/heartbeat/sweep/recover/workers_snapshot） |
| M3-F 验收 | `scripts/e2e_m3f.py`（本地 stub 内置） |
| 迁移 | `migrations/versions/0009_m3b_memory_workers.py` |

## 3. 数据库变更与迁移

- 迁移链：`m3_a_tools → m3b_memory_workers`（0009，唯一新迁移）
- **task** 新列：`plan_revision/replan_count/max_depth/max_total_steps`（默认 1/0/3/50）
- **task_run** 新列：`lease_owner/lease_expires_at/attempt/priority` + 索引 `ix_task_run_lease`
- 新表：`task_plan_revision`、`memory_item`（含去重索引）；FTS5 虚拟表 `memory_fts`（不可用时跳过，应用降级）
- `batch_alter_table` 用于 SQLite 加列；**只向前迁移**，downgrade 未实现（项目铁律）
- 真实库已升级并备份（升级前 `agentos_20261105_232728`、升级后 `agentos_20261106_003820`）；`tests/test_migrations.py` 双路径验证（空库升级 + 旧库副本升级 schema 一致、历史数据保留）

## 4. API 清单（M3 批次新增，前缀 `/api/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/system/tool-execution` | kill switch（M3-E，审计留痕） |
| POST | `/tasks/{id}/replan` | 重规划（M3-B，≤3 次） |
| GET | `/tasks/{id}/plan-revisions` | 计划版本历史 |
| POST/GET | `/companies/{cid}/memories` | 写入/列表（M3-C） |
| GET/PATCH/DELETE | `/memories/{id}` | 详情/更新/软删 |
| POST | `/memories/{id}/promote` | 提升作用域（仅本地人工） |
| GET | `/memories/search?q=` | FTS 检索 |
| GET | `/workers`、`/workers/stats` | Worker 视图/统计（M3-D） |
| PUT | `/tasks/{id}/plan` | **扩展**：pending 子任务可设计划 |
| GET | `/monitor/summary` | **扩展**：`tool_execution/tools/budgets` 字段 |

新增错误码：`TASK_DEPTH_EXCEEDED`、`TASK_STEP_BUDGET_EXCEEDED`、`TASK_REPLAN_LIMIT`、`BUDGET_EXCEEDED`、`TOOL_DENIED_LIMIT`、`MEMORY_SCOPE_DENIED`、`LEASE_EXHAUSTED`（及既有 M3-A 全部拒绝码）。

## 5. 前端页面与实际交互

- **监控页 `/monitor`**（增强）：新增"工具执行（全局）"卡片——显示状态 + **一键紧急停止/恢复按钮**（调 kill switch API，带审计）；"拒绝原因 Top N"；"预算使用率"表格（进行中任务、超 90% 红色预警）
- **记忆中心 `/settings/memory`**（新增）：作用域过滤、FTS 检索框、写入表单（项目/公司作用域）、提升（employee→project/company）、删除；说明 Agent 私有记忆需提升才共享
- **监控页 Worker 面板修复（2026-11-09）**：monitor/summary 此前未返回 workers 字段（上轮面板永远空白）——已与 /workers 同源补齐
- **员工详情记忆区块（2026-11-09）**：列出/写入/删除该员工私有记忆（employee 作用域），方便逐员工测试记忆功能
- **前端全局 ErrorBoundary（2026-11-09）**：页面子树崩溃显示可读错误+重试，不再白屏
- **config_io 扩展（2026-11-09）**：导出/导入包含工作区+授权+记忆（root 非法跳过记 warning，不放宽安全；旧包向后兼容）
- **FTS 召回混合（2026-11-09）**：FTS 命中不足 top_k 时自动补 LIKE 检索
- **岗位编辑 UI（2026-11-09）**：员工详情基本信息表单内多选岗位+主岗位（PATCH positions 全量替换）
- **浏览器验收 B17/B17b（2026-11-09）**：员工配置中心三区块渲染 + 工具勾选保存 Toast 回显（真实 UI 交互断言）
- **审批中心"要求修改"按钮（2026-11-09）**：三操作与任务详情页对齐
- **任务创建表单补全（2026-11-09）**：新增执行指令 textarea 与预算 USD 输入（创建即可设预算熔断），
  执行模式下拉本就含 real/mock/auto——明天实验创建 real 任务无需动 .env
- **审批上下文展示（2026-11-09）**：审批中心与任务详情审批面板显示 context 摘要
  （tool_call 审批显示"调用工具 X（风险 Y）· 参数"，交付前显示步骤/摘要）——审批人看得见批准的是什么
- **浏览器验收 B5.5（2026-11-09）**：审批中心页断言（聚合显示待审批+任务标题+闸门）；
  SPA 断言改单次原子 eval+轮询重试（React 首次提交存在只有 header 的中间态，单次 eval 会撞上）
- **任务详情页重规划区块（2026-11-08）**：失败/待返工任务显示步骤编辑 + 失败步骤标记 + 提交重规划（≤3 次），上游产出保留
- **监控页 Worker 面板（2026-11-08）**：在线 worker/租约存活/心跳/队列深度
- **审批中心 `/approvals`（2026-11-08）**：全公司待审批聚合（任务标题/闸门类型/状态），批准/驳回带备注写审计；状态筛选 + 4 秒轮询；监控页之外的第二处审批入口
- 导航新增"记忆中心"入口；构建 496.68 kB（gzip 150.95 kB），tsc 类型检查通过
- **工具执行开关反馈修复（2026-11-07，POST 200 但状态不变）**：根因是运行进程 env_enabled=false
  （.env 未配置 AGENTOS_TOOL_EXECUTION），POST {enabled:true} 是静默 no-op（kill 本来就 false）。
  修复：① 后端 env off 时请求开启返回 **409 TOOL_EXECUTION_BLOCKED_BY_ENV**（含修复指引，审计不留痕），
  停止请求永远可用；② 前端 mutation 补 onError + 成功/失败 Toast + 返回状态一致性校验（此前错误静默）。
  运维语义：env off 时 kill 一旦打开只能重启后端复位（API 409 拒绝清除，功能上无差异——两种状态工具都关）。
- **开发态同源代理修复（2026-11-06，UNTRUSTED_REQUEST 403）**：此前前端 `client.ts` 默认直连
  `http://127.0.0.1:8000`，从 `localhost:5173` 页面发起的写请求被浏览器标记 `Sec-Fetch-Site: cross-site`
  （localhost 与 127.0.0.1 是不同 site，**与端口无关**），被 LocalGuard 正确拒绝（403）；
  `127.0.0.1:5173` 页面因 IP 相同属 same-site 所以浏览器验收一直能过。
  修复：`vite.config.ts` 新增 `/api` 代理（target 127.0.0.1:8000，changeOrigin: true——Host 校验只看主机名，
  true/false 都能过，403 与它无关）+ 新增 `apps/web/.env.development`（`VITE_API_BASE=` 置空 → 同源相对路径，
  仅 dev 生效；生产构建仍默认绝对基址，serve_web 预览经 127.0.0.1 访问属 same-site 不受影响）。
  验收：经代理创建公司 201、列表/PATCH 正常、恶意 cross-site 依旧 403（防护未削弱）、全量 332 测试过
- 浏览器验收含监控页新区块截图（`docs/testing/m3_browser/12_monitor.png`），29 项 0 JS 异常

## 6. 权限、安全和预算设计（本批次新增的边界）

1. **递归不放大权限**：子任务继承公司/员工/工作区五层权限；grandchild 步骤同样过 `check_execution` + `decide()` 五层；工具 schema 只下发该步骤员工已授权集合
2. **递归不逃避预算**：预算限额 = 祖先链最紧值；消耗 = 整树聚合（usage 挂 nested run，按 `root_task_id` 汇总）；树工具调用 ≤100 由后端在循环内强制
3. **记忆不绕过权限**：检索永远带 viewer 员工视角（私有记忆跨员工检索不到）；Agent 写入只能 employee 作用域；提升是人工特权且审计
4. **记忆是数据不是指令**：`<memory>` 块只进用户消息 + system prompt 固定边界声明 + 注入劫持测试（`test_memory_injection_is_untrusted_data`）
5. **kill switch 优先级最高**：`global_tools_enabled()` 先查进程开关再查 env；行为可审计
6. **多 Worker 不破坏原子性**：`uq_task_run_active` 部分唯一索引继续兜底；认领 UPDATE 带状态条件防双领；启动恢复不误伤存活 worker
7. Shell 永久禁用、系统目录/盘符/UNC/ADS 拒绝、密钥不落库等 M3-A 红线**原样保留**（AST 扫描测试通过）

## 7. 自动化测试原始结果（2026-11-06 实测，存档 `docs/testing/m3bdf_final_regression.txt`）

```
pytest tests/ -q            → 355 passed, 3 skipped（3 skipped 为无权限环境 symlink 用例）
ruff check ...              → All checks passed!
npm run build（tsc -b）      → ✓ 110 modules，496.68 kB (gzip 150.95 kB)，built in 205ms
alembic current             → m3b_memory_workers (head)
reconcile_prompts.py        → orphan 0 / missing 0 / mismatch 0
scripts/e2e_m2.py           → M2 E2E 完成：13 项通过，0 项失败
scripts/e2e_m3f.py          → M3-F E2E 完成：16 项通过，0 项失败（1.9s，Mock + 本地 stub）
```

批次新增测试文件与数量：
- `tests/test_m3b_recursion.py`（9）：三层树聚合/第 4 层拒绝/树 50 步拒绝/自动分配+decision/replan 只补下游/replan 上限/失败传播与部分成功/父子预算（Token 触发+成本追溯）/嵌套审批挂起恢复
- `tests/test_m3c_memory.py`（10）：CRUD+去重/私有隔离/项目共享/提升审计/删除 FTS 无残留/top_k/脱敏/注入防劫持/Agent 记忆工具/无记忆降级
- `tests/test_m3d_workers.py`（7）：双 worker 无重复/心跳续租/租约过期恢复/LEASE_EXHAUSTED/公司并发上限/优先级/恢复不误伤
- `tests/test_m3e_guards.py`（9，M3-E）：成本/Token 熔断、连续拒绝、kill switch、监控统计

## 8. 浏览器验收结果（Edge + CDP 真实浏览器）

```
浏览器验收完成：30 项通过，0 项失败（含 B16 无未捕获 JS 异常）
覆盖：任务列表/创建/执行/审批/多 Agent/暂停恢复/组织/监控（含新区块截图 12_monitor.png）/
工作区授权/工具策略/工具面板/待审批/批准恢复/驳回 等
证据：docs/testing/m3_browser_acceptance.txt + m3_browser/*.png
```

## 9. Git 提交记录（未 Push）

| 提交 | 内容 | 测试基线 |
|---|---|---|
| `29d9d2d` | feat(m3-e): 执行监管闸门 | 306 passed/3 skipped |
| `a6f5423` | feat(m3-b): 递归任务拆分与动态计划 | 315 passed/3 skipped |
| `8f8d622` | feat(m3-c): 长期记忆 | 325 passed/3 skipped |
| `4683305` | feat(m3-d): 多 Worker | 332 passed/3 skipped |
| `12341fb` | feat(m3-f): 端到端业务验收 | 332 + E2E 13+16 + 浏览器 29 |

每个模块独立提交，M3-E 按任务书要求先行独立保存。工作区最终干净（git status 无未提交变更）。

## 10. 数据库与历史数据检查（真实库 `data/agentos.db`）

```
revision: m3b_memory_workers (head)
task 4 / task_run 4 / agent_run 4 / usage_record 4   ← M0 历史任务原样保留（未回填未清空）
memory_item 0 / task_plan_revision 0 / tool_call 0 / workspace 0 / company 0
audit_log 2（本会话 kill switch 端点探活产生的两条记录，内容为开关状态，非测试污染）
```
测试全部使用临时库；浏览器验收自建临时环境；真实库无测试数据混入。

## 11. 已知缺陷和未完成事项（如实陈述）

1. **真实模型链路**（2026-11-07 部分转 ✅）：单员工只读文件工具链路已真实验证（nonce 防编造通过，$0.0005），过程中发现并修复三层真实链路缺陷（litellm mcp 导入缺陷 / DeepSeek 工具名字符集 / 工作区上下文缺失，见 docs/acceptance/2026-11-07_真实模型工具调用验证.md）；litellm `_skip_mcp_handler` 补丁待升级后移除（有回归测试守护）。仍 🟡：多步协作/递归/审批挂起恢复/HTTP 与记忆工具的真实模型行为未验证；M3-F 的成本熔断在 mock 下用 Token 预算验证；单次调用的成本超支已由**调模型前预扣**拦截（2026-11-08：real 模式按目录档位把下一次调用保守预估计入预算检查，mock 预估 0）
2. **kill switch 是进程内存态**：进程重启后回到 `AGENTOS_TOOL_EXECUTION` 初始值（设计取舍，已在 UI/文档/API 三处明示）
3. **replan 超限直接 409**：主计划建议的"转 awaiting_approval"与状态机（failed→awaiting_approval 非法迁移）冲突，未采纳；人工可通过重试/返工路径处理
4. ~~嵌套审批的恢复 UX~~ → ✅ 2026-11-08 已实现自动续跑：子任务审批恢复 run 成功收尾后，父任务若处于 awaiting_approval 且无阻塞（无待审批/无活跃 run/未被请求暂停取消）则自动入队（事件 `task.auto_resumed`，trigger=auto_resume）；子 run 失败时不自动续跑（避免对已知失败步骤立即重试）。人工恢复路径仍可用
5. **denied_count 跨并行步骤计数**：极端并发下可能少计（与既有 `tool_calls_count` 同级别的一致性模型；SQLite 单写者 last-write-wins）
6. **M2 行为变更**：pending 子任务现在允许设置计划（M3_MASTER_PLAN §7.2 明确要求，`test_task_center` 已按新语义更新——非弱化）
7. **FTS5 中文分词**：unicode61 tokenizer 不做中文词切分，检索按连续字串 token 匹配；召回质量够用但非语义检索（排序按 bm25+命中）
8. Windows TOCTOU、本地恶意进程直连 SQLite、审计防篡改依赖应用层等 HANDOFF §8.2 既有边界**原样存在**

## 12. 未经授权而未执行的操作（🚫）

| 事项 | 原因 | 预计成本/影响 | 需要的授权 |
|---|---|---|---|
| ~~真实模型调用（DeepSeek）~~ | ✅ 2026-11-07 用户授权并已完成（文件读取工具验证，$0.0005，见验收文档） | — | — |
| 真实 GitHub/外网访问 | 红线：不真实外网；本机代理仅放行 api.github.com | 网络请求 | 明确允许 + 域名白名单配置 |
| Git Push | 红线 10：不擅自 Push | — | 明确指示推送方式（本机 GitHub API 通道） |
| 安装 Playwright/Redis/向量服务等 | 红线 3：不擅自安装 | — | —（按设计不需要） |

## 13. 需要用户最终决定的事项

1. **是否授权一次真实模型最小验证**（建议：允许后先跑 max_tokens=64 的单次工具调用，验证真实计价下预算熔断）
2. **是否推送** 5 个提交到 GitHub（需指定通道）
3. **下一批次方向**：M4 账号体系 / 真实外网业务闭环 / 生产化（PostgreSQL、多进程部署）——本批次完成后 M3 全部收尾，无内部阻塞项

## 14. 下一步启动命令

```bat
cd /d E:\AgentOS
.venv\Scripts\python.exe -m alembic current          REM 期望 m3b_memory_workers (head)
.venv\Scripts\python.exe -m pytest tests/ -q         REM 期望 355 passed, 3 skipped（约 100s，全 Mock）
.venv\Scripts\python.exe -m ruff check apps packages scripts tests migrations
.venv\Scripts\python.exe scripts\e2e_m3f.py          REM 期望 16 项通过
.venv\Scripts\python.exe scripts\browser_acceptance.py   REM 需 8000/5173/9333 空闲；期望 30 项
.venv\Scripts\python.exe scripts\run_api.py --port 8000  REM 起后端；前端 cd apps\web && npm run dev → 127.0.0.1:5173（右上角 v0.3.1，含审批中心导航）
```

---

---

## 附：使用前免费验收（2026-11-07，全部 Mock，真实费用 0）

**真实库只读巡检结论**（SELECT only，未写任何数据）：
- 公司"小宝公司"（fc3efd74）：工具策略已配好（file_read/file_write on，allowed 含 fs.list_dir/fs.read_file/fs.stat/fs.write_file）✅
- 工作区"实验区"：root=E:\AgentOS\experiment_workspace、active、read_write ✅
- 实验文件 test.txt 内容完好（"大肥鱼是诗人"，git 与磁盘一致）✅
- 授权：臧志聪、闵昊已有"实验区" write 授权 ✅；大肥鱼/小肥鱼/龚林未授权
- **唯一缺口：全部 5 名员工 tools_allowed=[]** → 明天在员工详情页勾选 fs.list_dir/fs.read_file 即可（正是配置中心功能）
- 全局 AGENTOS_TOOL_EXECUTION=on（用户已配）✅

**六类 Mock 场景验收映射**（A-F 全部 ✅，对应测试名可复核）：
| 场景 | 结果 | 测试 |
|---|---|---|
| A 单员工读取文件（目录+读取+审计） | ✅ | test_employee_config::test_end_to_end_mock_task_with_configured_employee |
| B 两员工协作+按身份分别校验工具（甲成功/乙被拒/上游传递/拒绝不阻断） | ✅（本轮新增） | test_employee_config::test_scenario_b_two_employees_collaboration_with_per_identity_tools |
| C 人工审批（等待/批准继续/驳回不可执行/记录完整） | ✅ | test_approvals 6 项 + test_m3e_guards（工具审批挂起恢复） |
| D 递归（子任务/深度/步数/子预算受父约束/replan 上限） | ✅ | test_m3b_recursion 9 项 |
| E 记忆（私有隔离/作用域/提升/删除/不可信注入） | ✅ | test_m3c_memory 10 项 |
| F 异常安全（未授权工具/未授权工作区/路径越界/kill/预算/连续拒绝/次数上限） | ✅ | test_m3e_guards 9 + test_system_switch 4 + test_tool_policy 23 + test_tool_paths 60 |

**本轮发现的行为说明（非缺陷）**：计划阶段会拒绝"步骤声明了员工未授权工具"的计划
（TASK_PLAN_INVALID，防护前置）；场景 B 因此改用"乙有无关白名单+指令 marker 调用未授权工具"路径，
与真实模型的未授权尝试语义一致。

**回归数据**：348 passed / 3 skipped（+场景 B）；ruff 全过；前端 build ✓；浏览器验收 29/29（0 JS 异常）；
**真实模型调用次数：0；真实费用：0**。

---

## 附：真实模型实验（✅ 2026-11-11 三轮完成——① DeepSeek 单文件读取 PASS $0.00044；② 智谱 GLM-4-Flash（免费）多 Agent 协作；③ OpenRouter Nemotron 550B（:free）三员工协作+报告落盘 PASS 费用 0。免费模型清单会随平台调整，catalog 标注日期需定期刷新。重要教训：真实模型实验指令必须用自然语言，Mock marker 语法对真实模型无效。详见 docs/acceptance/2026-11-11_真实实验报告.md 与 2026-11-11_OpenRouter实验报告.md）

> 以下为当时的实验步骤，保留供复现与扩展实验（多员工协作/审批/记忆/预算熔断）参考。

### 原始步骤

前置（已就绪）：`.env` 已有 `AGENTOS_TOOL_EXECUTION=on`；工作区 `experiment_workspace`（根目录 `E:\AgentOS\experiment_workspace`）与文件 `test.txt`（内容："大肥鱼是诗人"，用户自建）已存在并入库。

**完整操作步骤（12 点）**：
1. **进入页面**：启动后端与前端后，浏览器打开 `http://localhost:5173`；
2. **选择员工**：「AI 员工」页切到"小宝公司"，点员工卡片「编辑配置 →」（建议用已有"实验区"授权的臧志聪或闵昊，可跳过第 4 步）；
3. **配置工具授权**：详情页「工具授权管理」勾选 `fs.list_dir`、`fs.read_file` → 保存（绿色 Toast；也可先清空再勾选验证撤销）；
4. **配置工作区授权**：「工作区授权管理」给"实验区"授权"只读"（臧志聪/闵昊已是读写，可直接用）；
5. **确认五层诊断**：同页"实际可执行"列对这两个工具应为绿色"可执行"；若显示原因（如"未授权工作区"），按原因补配置；
6. **创建任务**：「任务」→ 新建任务：执行员工选该员工，公司自动绑定（创建接口校验归属），执行模式选 **real**，预算填 **0.05**（熔断上限，实际预计 <$0.01）；
7. **任务提示词**：粘贴本章节下方代码块原文；
8. **看哪些日志**：后端控制台的 POST /run 与工具调用日志；任务详情页"执行记录/工具调用/时间线"三个面板；
9. **确认工具真实执行**：任务详情"工具调用"面板应有 fs.list_dir 与 fs.read_file 两条 succeeded（含 sha256/耗时），状态非 denied；
10. **确认没有编造**：模型汇报的文件内容必须与 test.txt 实际内容一致（"大肥鱼是诗人"）；不符即编造，收集证据；
11. **费用与低预算**：任务预算 0.05 美元，超限自动暂停（task.budget_exceeded）；实际预计 <$0.01，完成后在任务详情"成本"区核对 billable=true 的真实金额；
12. **失败时收集**：任务 result.error 的 code/message、时间线里的拒绝事件（error_code）、后端控制台报错、员工详情页"实际可执行"列的原因——四项足够定位是哪一层配置缺失。

**任务提示词（可直接粘贴）**：

```
请在当前分配给你的工作区中找到 test.txt 并读取其完整内容，向我汇报。
要求：先用 fs.list_dir 查看工作区结构，再用 fs.read_file 读取 test.txt；
只读取授权工作区内的文件，不得创建/修改/删除任何文件，不得执行 Shell；
如读取失败请报告真实错误，不要编造内容。汇报中必须包含文件的原文内容。
```

**验收要点**：任务 succeeded；工具调用面板两条 succeeded；模型汇报包含"大肥鱼是诗人"；
usage billable=true（预计 <$0.01）。若某层配置缺失，员工详情页"实际可执行"列的原因
与任务时间线的拒绝事件会直接指出缺哪一层。

*最近更新：2026-11-07｜M3 批次（A/E/B/C/D/F）+ 员工配置中心完成｜执行：ZCode（GLM）*
