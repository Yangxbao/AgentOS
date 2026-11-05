# AgentOS M3 批次主交接文档（唯一交接入口，随开发持续更新）

> 本文档是 M3 批次（M3-A/E 已完成，M3-B/C/D/F 进行中）的唯一交接与验收文档。
> 所有进度、决策、证据、未决事项集中在这里，不另设碎片文档。
> 更新约定：每完成一个模块/一次提交立即更新本文对应章节；若会话中断，"当前执行位置"章节保证可直接续做。
> 状态图例：✅已实现且测试通过｜🟡已实现未充分验证｜♻️已有机制本次回归确认｜⬜未实现｜🚫因授权限制未执行

## 0. 当前执行位置（实时）

- 已完成：M0/M1/M2/M3-A/M3-E/M3-B；M3-E 提交 `29d9d2d`；M3-B 提交（见 §8）
- 测试基线：315 passed / 3 skipped（306+9 M3-B）
- 正在进行：M3-C 长期记忆
- 迁移：`m3b_memory_workers`（0009）已在真实库升级，4 条 M0 历史任务完好

## 3. M3-B 递归任务拆分与动态计划（✅ 已实现且测试通过）

**实现位置：**
- 迁移：`migrations/versions/0009_m3b_memory_workers.py`（task 新列 + task_plan_revision + memory_item/memory_fts）
- 计划：`packages/tasks/plan.py`（TASK_DEPTH_EXCEEDED、任务级 max_depth 1–4、自动分配）
- 服务：`packages/tasks/service.py`（set_plan 递归/树步数上限/replan/plan_revisions_of/_tree_step_total）
- 执行：`packages/execution/executor.py`（_run_step 调度器 + _run_nested_step + _enqueue_nested_run）
- 预算：`packages/execution/budget.py`（树聚合 limits_for/spent_for_tree/tree_tool_calls，上限 100 次）
- API：`POST /tasks/{id}/replan`、`GET /tasks/{id}/plan-revisions`；`PUT /tasks/{id}/plan` 扩展到 pending 子任务
- 测试：`tests/test_m3b_recursion.py`（9 个）

**关键设计（与 M3_MASTER_PLAN §7 对齐）：**
- 子任务计划保存在 child.plan（含 step_id 关联标记 + steps），nested run（trigger=nested）驱动子计划波次，检查点在子 run 上，断点续跑
- 子计划内工具审批 → RunSuspended 沿异常上传 → 父任务同步 awaiting_approval；批准后子任务经审批 run 独立完成，父任务用 resume 推进
- 预算：限额取祖先链最紧预算，消耗按整树聚合（usage 挂 nested run，root_task_id 聚合），递归无法逃避
- 失败传播：孙步骤失败 → 子任务 failed → 父任务 failed；已完成上游保留在子检查点，重试只补下游

**行为变更（原 M2 测试已按新语义更新，见 test_task_center）：** pending 子任务现在可以设置计划（M3_MASTER_PLAN §7.2 明确要求移除 M2 禁止）。

**已知限制（诚实记录）：**
- mock 模式下执行器把 cost 强制写 0（M3-E 诚实性规则），单次调用路径无 pending 消耗机制 → 成本熔断在单步内不可触发（下一个步骤开始前触发）；工具循环路径有 pending 检查。测试用 Token 预算验证嵌套熔断
- replan 超限按 TASK_REPLAN_LIMIT 409 拒绝（主计划的"转 awaiting_approval"与状态机冲突，未采纳）

## 1. 批次总任务书要点（执行依据）

- 连续自主完成 M3-B → M3-C → M3-D → M3-F，模块间不停等批准
- 红线：无 Shell、无付费 API/真实外网、不 Push、不降低 M3-A/E 权限标准、子任务/Worker/记忆不绕过权限
- 最终统一测试：全量 pytest / ruff / tsc+build / 迁移（空库+旧库）/ M2 E2E / 浏览器验收 / 各模块专项
- Git：M3-E 单独提交（已完成），后续各模块独立提交，不 Push

## 2. M3-E（已完成部分，详见 docs/acceptance/2026-11-06_M3-E_验收文档.md）

- ✅ 预算熔断（budget.py，成本+Token，暂停不是失败）
- ✅ 连续拒绝熔断（denied_count，≥3 → paused）
- ✅ 全局 kill switch（进程级 + 审计）
- ✅ 监控统计（工具/拒绝 Top N/预算使用率）
- ♻️ 单步 8 次上限、输出截断（M3-A 既有，回归确认）
- 修复：审批恢复后 tool_state 残留（M3-A 隐性 bug）

## 3. M3-B 递归任务拆分与动态计划

（实现中，本节随开发填写）

## 4. M3-C 长期记忆

（待开始）

## 5. M3-D 多 Worker

（待开始）

## 6. M3-F 端到端业务验收

（待开始）

## 7. 测试与证据汇总

（随开发填写）

## 8. Git 提交记录

| 提交 | 内容 | 测试基线 |
|---|---|---|
| `29d9d2d` | feat(m3-e): 执行监管闸门 | 306 passed/3 skipped, ruff/build/浏览器 29 项全过 |

## 9. 已知缺陷 / 未完成 / 未授权事项

（随开发填写）

## 10. 下一步启动命令

```bat
cd /d E:\AgentOS
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m pytest tests/ -q
```
