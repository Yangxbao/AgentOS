# AgentOS M3 交接与进度（Master Handoff）

> 版本：**v1.1**｜日期：2026-11-05｜状态：**M3-A 工具执行层已完成并通过验收；M3-E/B/C/D/F 未开始**
> 设计基线：`M3_MASTER_PLAN.md`（架构/权限/数据/API/阶段验收）。
> 本文是 M3 唯一进度记录：实际完成什么、证据在哪、还有什么没做。
> 所有数字均来自本机真实执行；证据见 `docs/testing/m3a_final_regression.txt`、`docs/testing/m3_browser_acceptance.txt`、`docs/testing/m3_browser/`。

---

## 1. 当前结论

| 项 | 结果 |
|---|---|
| 代码基线 | 代码提交 `1b0198d`（M3-A）；上一阶段 `4733bdd`（M3 规划 + M3-0） |
| 数据库 | 真实库 21 表，revision **`m3_a_tools`**；`task/task_run/agent_run/usage_record` 各 4 条历史数据未动 |
| 自动化测试 | **297 passed / 3 skipped**（M2 基线 129 + M3-A 新增 171） |
| ruff | 全绿（apps/packages/scripts/tests/migrations） |
| 前端 | `tsc -b && vite build` 通过（488.48 kB，gzip 149.43） |
| 浏览器验收 | **29/29 通过**（M2 原 16 项 + M3-A 13 项），0 条未捕获 JS 异常 |
| 真实模型调用 | **本轮 0 次**（全部 Mock，不产生费用）；M2 历史累计 4 次 / 353 tokens / ≈$0.00006285 |
| 未完成 | M3-E 预算熔断、M3-B 递归、M3-C 记忆、M3-D 多 Worker、M3-F 业务验收 |

### 1.1 M3-A 完成度（对照任务书 27 条完成标准）

| # | 标准 | 状态 |
|---|---|---|
| 1 | 工作区与员工授权可用 | ✅ 创建/改名/归档/授权/撤权，撤权立即生效 |
| 2 | 工具注册中心可用 | ✅ 7 个工具，含参数 Schema/风险/超时/输出上限 |
| 3 | 五层权限判断可用 | ✅ 公司→岗位/员工→工具白名单→工作区，逐层拒绝码 |
| 4 | `safe_resolve` 安全测试通过 | ✅ 60 个路径用例（含 junction 逃逸） |
| 5 | 读文件/列目录/stat/创建文件 | ✅ |
| 6 | 覆盖写入与删除审批 | ✅ `gate=tool_call` 挂起 → 批准/驳回 |
| 7 | HTTP Stub 调用可用 | ✅ 本机 stub，未访问真实外网 |
| 8 | SSRF 与重定向防护测试 | ✅ 回环/私网/链路本地/元数据/跨域重定向 |
| 9 | Shell 完全没有执行路径 | ✅ AST 扫描 + 调用即 `SHELL_DISABLED` |
| 10 | `tool_call` 与 `audit_log` 完整 | ✅ 成功/失败/拒绝/超时/挂起都落库 |
| 11 | 模型工具调用循环可用 | ✅ Mock 确定性工具调用 + 真实 LiteLLM `tools` 参数适配 |
| 12 | 工具循环次数上限生效 | ✅ 默认 8 次，`TOOL_LOOP_EXCEEDED` |
| 13 | 工具审批可挂起与恢复 | ✅ 保存 messages/pending/call_index |
| 14 | 恢复不重复调用模型 | ✅ 复用同一 `tool_call`，批准后从该调用继续 |
| 15 | 后端 API 全部实现 | ✅ M3-01..10（14 个 route-method 对） |
| 16 | 前端工作区管理页 | ✅ |
| 17 | 前端工具策略页 | ✅ |
| 18 | 前端任务工具调用面板 | ✅ |
| 19 | 浏览器真实验收完成 | ✅ 29/29 |
| 20 | 全量 pytest 通过 | ✅ 297 |
| 21 | Ruff 通过 | ✅ |
| 22 | 前端 TypeScript 检查 | ✅ `tsc -b` |
| 23 | 前端构建通过 | ✅ |
| 24 | M2 回归测试通过 | ✅ 129 个原用例全绿 |
| 25 | 数据库历史数据完整 | ✅ 4 条任务/run/agent_run/usage 原样 |
| 26 | Git 提交完整、工作区干净 | ✅ 见 §8 |
| 27 | 本文档更新完整 | ✅ |

---

## 2. M3-A 交付明细

### 2.1 新增模块

| 文件 | 作用 |
|---|---|
| `packages/tools/registry.py` | `ToolSpec` + 7 个工具注册；`model_schemas()` 只暴露已授权工具 |
| `packages/tools/schema.py` | 极简 JSON Schema 校验（未知字段拒绝，与下发模型的 schema 同源） |
| `packages/tools/paths.py` | **`safe_resolve`**：绝对路径/盘符/UNC/ADS/NUL/`..`/保留设备名/reparse point/大小写/敏感名单 |
| `packages/tools/workspaces.py` | 工作区 CRUD、授权、撤权、默认根、系统目录拒绝 |
| `packages/tools/fs.py` | `fs.list_dir` / `fs.read_file` / `fs.stat` / `fs.write_file` / `fs.delete_file` |
| `packages/tools/http.py` | `http.request`：域名白名单 + DNS 后 IP 检查 + 逐跳重定向校验 + 大小/超时 |
| `packages/tools/shell.py` | `shell.run` 只抛 `SHELL_DISABLED`，无任何执行代码 |
| `packages/tools/policy.py` | 五层权限 `decide()`、`visible_tools()`、公司策略校验 |
| `packages/tools/invoke.py` | 唯一入口：校验→授权→风险/审批→幂等→执行→截断→脱敏→落库→审计→事件 |
| `packages/execution/tool_loop.py` | 多轮工具循环、审批挂起状态、恢复、次数上限 |
| `apps/api/routers/tools.py` | M3-01..10 |
| `apps/api/schemas/tools.py` | 请求/响应模型（策略 patch 拒绝未知字段） |
| `apps/web/src/api/tools.ts` | 前端 API 客户端 |
| `apps/web/src/pages/WorkspacesPage.tsx` | 工作区管理 |
| `apps/web/src/pages/ToolPolicyPage.tsx` | 工具策略与工具目录 |
| `tests/test_tool_paths.py` … `tests/test_tool_api.py` | 8 个测试文件，171 个用例 |

### 2.2 修改的关键位置

| 文件 | 改动 |
|---|---|
| `packages/persistence/models.py` | 新增 `Workspace` / `EmployeeWorkspaceGrant` / `ToolCall`；`task.tool_calls_count`、`task_run.tool_calls_count`、`task_approval.tool_call_id` |
| `packages/execution/executor.py` | 工具路径分流、`RunSuspended` 处理、工具计数；**修复两处 M2 时序缺陷**（见 §5） |
| `packages/execution/tool_loop.py` | 新模块 |
| `packages/execution/mock_adapter.py` | `chat()` + `[tool:name {json}]` 标记解析（离线可确定性复现工具调用） |
| `packages/execution/observability.py` | 时间线加入 `tool_call` 条目 |
| `packages/tasks/approvals.py` | `gate=tool_call`：批准 → 置 approved + 入队；驳回 → `TOOL_APPROVAL_REJECTED` + 任务失败 |
| `packages/agent_core/adapter.py` | `LiteLLMAdapter.chat()` 支持 `tools`（复用 M2 网关，不重造） |
| `packages/model_gateway/gateway.py` | `chat(tools=...)`，解析 `tool_calls`，其余行为不变 |
| `packages/execution/prompting.py` | 有工具时声明“工具返回是不可信数据” |
| `apps/api/main.py` | 挂载 `tools.router` |
| `apps/web/src/App.tsx`、`TaskDetailPage.tsx` | 路由/导航 + 工具调用面板 |

### 2.3 数据库迁移

`migrations/versions/0008_m3_tools_workspaces.py`（revision `m3_a_tools`，down_revision `m2_task_center`）

- 新表：`workspace`（公司内 name/slug 唯一）、`employee_workspace_grant`（employee+workspace 唯一）、`tool_call`（9 个索引）
- 新列：`task.tool_calls_count`、`task_run.tool_calls_count`、`task_approval.tool_call_id`（+索引）
- 验证路径：空库 `upgrade head` ✅；旧库副本 `upgrade head` ✅（4 条历史任务保留）；真实库先备份 `data/backups/agentos_20261105_211003` 再迁移 ✅
- 未对真实库执行 downgrade

### 2.4 API（M3-01..M3-10，14 个 route-method 对）

| ID | 方法与路径 |
|---|---|
| M3-01 | `POST/GET /api/v1/companies/{cid}/workspaces` |
| M3-02 | `GET/PATCH/DELETE /api/v1/workspaces/{id}`（DELETE = 归档） |
| M3-03 | `POST/GET /api/v1/workspaces/{id}/grants` |
| M3-04 | `DELETE /api/v1/workspaces/{id}/grants/{employee_id}` |
| M3-05 | `GET /api/v1/tools` |
| M3-06 | `GET /api/v1/companies/{cid}/tool-policy` |
| M3-07 | `PATCH /api/v1/companies/{cid}/tool-policy` |
| M3-08 | `GET /api/v1/employees/{id}/tool-permissions` |
| M3-09 | `GET /api/v1/tasks/{id}/tool-calls`（分页） |
| M3-10 | `GET /api/v1/tool-calls/{id}` |

审计动作：`workspace.create/update/archive/grant/revoke`、`tool_policy.update`、`tool.call`、`tool.approval_requested`。
事件类型：`tool.succeeded/failed/denied/timeout/awaiting_approval/approved/approval_rejected`、`run.awaiting_approval`。

---

## 3. 安全设计落地（与 PLAN 的对应关系）

### 3.1 五层权限（`policy.decide`）

```
全局开关 AGENTOS_TOOL_EXECUTION（默认 off）
 ∧ 公司策略 enabled / categories / allowed_tools
 ∧ 员工 tools_allowed（精确工具名；空 = 不允许任何工具）
 ∧ 岗位/员工权限层 tools（非空时进一步收窄）
 ∧ 文件工具：工作区 grant（read/write）+ 工作区 mode
 ∧ 风险：> 公司 max_risk_level 拒绝；> 自动执行上限转人工审批
```

**与 PLAN 的偏差（如实记录）**：
1. PLAN 伪代码写 `tool ∈ effective_permissions.tools`。M1 的 `tools` 默认是 `[]`，若按“空即拒绝”会让工具永远不可用。实现为：**非空时作为额外收窄，空表示该层不再加限**；真正的“空 = 禁止”落在 `employee.tools_allowed`。
2. `max_risk_level` 语义分层：**员工有效 `max_risk_level` = 自动执行上限**（超过转审批）；**公司 `tools.max_risk_level` = 绝对上限**（critical 直接拒绝）。这样“覆盖已有文件必须审批”才成立。

### 3.2 路径与文件

- 拒绝：绝对路径、盘符（含 `:`）、UNC、ADS、NUL/控制字符、`.`/`..`、空段、Windows 保留名、以空格/点结尾的段。
- 逐级 `lstat` 检查 symlink/junction（`FILE_ATTRIBUTE_REPARSE_POINT`），再 `resolve()` + `normcase` + `commonpath` 判断包含关系。
- 敏感名单（大小写不敏感）：`.env*`、`*.pem/*.key/*.pfx/*.p12`、`id_rsa*`、`.ssh`/`.aws`/`.gnupg`/`.azure`/`.kube`、`credentials*`、`NTUSER.DAT`、`SAM`、`SYSTEM`、`.git/config`、`.git-credentials`、`.npmrc`、`.pypirc`。
- 读：≤256KB、UTF-8、`\x00` 视为二进制、内容命中密钥特征（`sk-`/`PRIVATE KEY`/`AKIA`/`ghp_`/`Bearer`）整体拒绝。
- 写：`create` 用 `O_CREAT|O_EXCL`；`overwrite` 临时文件 + `fsync` + `os.replace`；`append` 限总大小；≤1MB；不自动建多级目录。
- 删：只删单文件、拒绝目录/链接、返回 sha256 与字节数。

**Windows TOCTOU 明确未消除**：校验与打开之间仍可能被本机进程替换；威胁模型是“本地单用户 + 工作区”，企业级需要 OS 沙箱（M4+）。

### 3.3 网络

- 域名白名单（`host` / `host:port` / `*.suffix`），URL 不允许 userinfo，只允许 http/https。
- DNS 解析后逐 IP 检查：回环、私网、链路本地、保留、组播、未指定、`169.254.169.254`/`100.100.100.200` 全部拒绝。
- 重定向逐跳重新校验（最多 5 跳），跳出白名单即拒绝。
- 请求头只允许 `content-type/accept/user-agent/accept-language`；`Host/Cookie/Authorization/Proxy-Authorization/X-Forwarded-*` 直接拒绝。
- 响应 ≤2MB、超时 1..60s、内联正文 ≤20k 字符、**显式禁用系统代理**。
- 测试专用开关 `AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK=1`（默认 0）：仅在“域名已白名单 + 显式开启”时允许回环，用于本地 stub 测试。

### 3.4 Shell

- 注册但 `enabled=False`；`decide` 对 `category=shell` 一律 `SHELL_DISABLED`，即使公司策略、白名单、员工授权全部“开启”。
- 策略校验拒绝 `categories.shell=true` 与 `allowed_tools=["shell.run"]`。
- `tests/test_shell_disabled.py` 用 **AST** 扫描 `packages/tools/*.py`：无 `subprocess` import、无 `os.system/Popen/exec*/spawn*` 调用。

### 3.5 工具循环与审批恢复

- 只把 `visible_tools(ctx)` 的 schema 发给模型。
- `idempotency_key = sha256(task_id|step_id|call_index|tool|args_hash)`；同 key 已成功 → 直接复用结果，不产生第二次副作用。
- 挂起：`checkpoint.tool_state = {step_id, messages, iteration, call_index, pending{tool_call_id, call_id, name, args}, approval_id}`；run/task → `awaiting_approval`。
- 批准：`task_approval.tool_call_id` 指向同一条 `tool_call` → 置 `approved` → 入队新 run → 工具循环从 `pending` **直接执行该调用**，不重新调模型生成 tool_call。
- 驳回：`tool_call.status=denied` + `error_code=TOOL_APPROVAL_REJECTED`，任务 `failed`（可重试），不进入返工回退。
- 上限：`policy.max_tool_calls_per_step`（默认 8，1..50）→ `TOOL_LOOP_EXCEEDED`。

---

## 4. 测试与证据

### 4.1 自动化测试（真实输出）

```
pytest tests/ -q                                  → 297 passed, 3 skipped in 78.34s
ruff check apps packages scripts tests migrations  → All checks passed!
cd apps/web && npm run build                      → ✓ built，488.48 kB（gzip 149.43）
alembic current                                   → m3_a_tools (head)
python scripts/reconcile_prompts.py               → orphan 0 / missing 0 / mismatch 0
```

新增 171 个用例的分布：

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_tool_paths.py` | 60 | 正常路径、`..`、绝对/盘符/UNC/ADS/NUL/保留名、敏感文件、大小写、junction 逃逸、symlink（2 个 skip：环境不允许创建符号链接） |
| `test_tool_policy.py` | 23 | 全局/公司/类别/白名单/员工/工作区/只读/归档/风险/审批/Shell |
| `test_tool_fs.py` | 22 | 列目录（深度/条数）、读（二进制/大文件/敏感/密钥内容）、stat、create/overwrite/append、删除审批、只读工作区 |
| `test_tool_http.py` | 17 | 白名单、回环/私网/元数据、重定向、Host/Authorization、POST 策略、超时、超大响应、500 |
| `test_tool_invoke.py` | 14 | 落库/审计/事件、拒绝、未注册、参数、幂等、脱敏、超时、截断 |
| `test_tool_loop.py` | 13 | 无工具回归、单/多调用、未授权工具、Shell、未注册、8 次上限、审批批准/驳回、全局关闭、权限诊断 |
| `test_shell_disabled.py` | 9 | 注册态/禁用、AST 无执行路径、策略拒绝、API 拒绝、目录标记 |
| `test_tool_api.py` | 13 | 工作区 CRUD/默认根/禁用根/重名/归档、授权生命周期、跨公司、策略校验、调用列表/详情、审计 |

3 个 skip 全部是“当前 Windows 环境不允许创建符号链接”，不是跳过安全断言：junction 逃逸已用 `mklink /J` 实测拦截。

### 4.2 浏览器验收（Edge headless + CDP，未装 Playwright）

`python scripts/browser_acceptance.py` → **29 项通过 / 0 失败**，13 张新截图。

M3-A 的 13 项：

| # | 检查 |
|---|---|
| M3-1 | 工作区页渲染（含根路径） |
| M3-2 | 浏览器创建新工作区 |
| M3-3 | 浏览器授权员工（读写） |
| M3-4 | 浏览器撤销授权 |
| M3-5 | 工具策略页与工具列表 |
| M3-6 | Shell 永久禁用说明 |
| M3-7 | 工具调用面板显示成功记录（DOM + API 双重断言） |
| M3-8 | 时间线包含 `tool.succeeded` |
| M3-9 | 刷新后工具记录仍存在 |
| M3-10 | 被拒绝的工具调用同样展示 |
| M3-11 | 工具调用进入待审批 |
| M3-12 | 批准后恢复并完成 |
| M3-13 | 驳回工具调用后任务失败 |

截图：`docs/testing/m3_browser/m3_01_workspaces.png` … `m3_08_tool_rejected.png`；已人工检视工作区、工具策略、工具面板、待审批四个页面。

---

## 5. 本轮修复的真实缺陷

| # | 缺陷 | 影响 | 修复 |
|---|---|---|---|
| 1 | **SQLite WAL 读快照**：执行器外层 session 的只读事务不结束 | 其他会话刚提交的 `cancel_requested/pause_requested` 看不到（M2 时序侥幸通过） | 每波开始 `commit + expire_all + 重新读取` |
| 2 | 步骤会话在模型调用期间持有写锁（`child.state=running` 未提交） | `POST /cancel` 被阻塞 0.75s，取消/暂停落后于执行 | 子任务置 running 后立即 commit |
| 3 | 工具路径下 `handle` 未定义 | 工具执行完成后 `UnboundLocalError` → 任务失败 | `handle=None` + 安全取值 |
| 4 | `ctx.tool_call_id` 跨调用复用 | 连续两次工具调用合并成一条 `tool_call` 记录 | 非审批恢复时重置；每次调用独立记录 |
| 5 | 工具面板不刷新 | 执行完成后仍显示“0 次” | 固定 3s 轮询 + 动作后失效缓存 |
| 6 | 工作区删除按钮选择器按员工 ID 匹配到第一张卡片 | 浏览器验收会撤错工作区授权 | testid 增加 workspace id（仅测试选择器） |
| 7 | HTTP 500 被当成执行失败 | 无法把服务端错误作为工具结果返回 | 4xx/5xx 视为正常应答 |

---

## 6. 未完成、已知限制与风险

### 6.1 M3-A 范围内未做（明确不在本轮）

| 项 | 原因 |
|---|---|
| Token/费用预算熔断、连续拒绝自动暂停、kill switch | 属 **M3-E**；A 只留了 `max_tool_calls_per_step` 与风险分级接口 |
| 工具输出注入的模型侧强约束 | 已做 `<untrusted_tool_result>` 包裹 + system 提示；但“模型一定不听注入”无法用工程保证 |
| 递归子任务使用工具 | 属 M3-B；当前工具循环只作用于单层步骤 |
| 多进程 worker 下工具幂等 | 单进程假设仍在；幂等键已按 task/step/call 设计，可平滑升级 |
| 真实外部网络 | 未授权；HTTP 只测本机 stub |
| 真实模型工具调用 | 本轮 0 次真实调用；`LiteLLMAdapter.chat(tools=...)` 已按 OpenAI 兼容格式实现，但**未用真实供应商验证** |

### 6.2 已知安全边界

1. **TOCTOU 未消除**：`safe_resolve` 与真正打开之间仍可能被本机进程替换；本地单用户威胁模型下可接受。
2. **符号链接测试受限**：本机无法创建 symlink（2 个 skip），junction 已实测。
3. **本机恶意进程**可直连 SQLite；本地防护只挡浏览器跨站/跨源（M1 结论不变）。
4. **HTTP 白名单是“域名级”**，同一域名下的不同路径不做区分；写方法还需公司策略 + 逐次审批。
5. **审批人资格**：本地用户可直接决策；指定员工审批时校验 `reviewer != 执行人`，但不会强制 `can_review`（任务创建阶段已校验）。

### 6.3 风险分级

| 级别 | 项 |
|---|---|
| P0 | 无 |
| P1 | ①真实模型工具调用未验证（仅 Mock）；②无预算熔断（M3-E）；③审计与业务非同事务（工具调用自身已同事务，workspace/policy 为追加写） |
| P2 | ①前端工作区改名用 `window.prompt`；②工具策略页不支持拖拽排序域名；③`fs.list_dir` 不返回隐藏文件过滤开关 |

---

## 7. M3-0 浏览器验收（历史，已完成）

方法：本机 Edge `--headless=new` + `--remote-debugging-port`，CDP over WebSocket 执行真实点击；前端 `scripts/serve_web.py`（127.0.0.1:5173），后端 `scripts/run_api.py`（8000，临时库 + Mock）。

M2 的 16 项（B1..B16）全部保留并通过，其中发现并修复 4 个真实缺陷：组织图缺 `company-root` 节点、React Flow 控件白板、时间线不刷新、`/api/health` 版本陈旧。详见截图 `02_tasks.png` … `14_org.png`。

---

## 8. Git 与工作区

| 提交 | 内容 |
|---|---|
| `4733bdd` | M3 规划 + M3-0 浏览器验收（上一轮） |
| `1b0198d` | **M3-A 代码与测试**：迁移 `m3_a_tools`、`packages/tools/*`、`tool_loop`、执行器/审批接入、M3-01..10、三个前端页面、171 个测试 |
| 本轮文档提交 | `M3_MASTER_HANDOFF.md`、`docs/testing/m3a_final_regression.txt`、13 张 M3-A 截图、README/CHANGELOG/ROADMAP |

工作区在提交后应为干净；未推送 GitHub；未安装 Playwright/Docker/CrewAI/Codex CLI；未修改 Windows 安全设置。

---

## 9. 下一阶段：M3-E 启动清单

建议顺序仍是 **E → B → C → D → F**。M3-E 的最小闭环：

1. `packages/execution/budget.py`：按 task 累计 token/cost，读取 `task.budget_usd` 与公司策略；超限 → `task.paused` + `TASK_BUDGET_EXCEEDED` 事件。
2. 连续拒绝/失败计数：同一 task_run 内 `TOOL_DENIED` ≥3 → 暂停并提示检查授权。
3. `AGENTOS_TOOL_EXECUTION=off` 时的失败语义统一（当前：不进入工具循环，正常完成；E 阶段改为“明确暂停并提示”）。
4. 全局 kill switch：`POST /api/v1/system/tool-execution`（仅本地用户），审计留痕。
5. 监控页增加“工具调用统计 / 拒绝原因 Top N / 预算使用率”。

M3-E 之前不建议开 B（递归会放大成本与失控风险）。

---

## 10. 需要确认的事项（不阻塞 M3-A）

1. **真实模型工具调用**是否允许用已有 DeepSeek Key 做一次最小验证（`max_tokens=64`，单次工具调用），预计 < $0.0001。
2. **真实 GitHub 只读访问**是否授权（M3-F 需要；未授权则只用本地 stub 并标注未验证）。
3. 工作区默认根目前是 `data/workspaces/<slug>`；是否需要在 UI 提供“打开目录”按钮（涉及本机文件管理器调用，属于新的系统交互，未擅自实现）。
