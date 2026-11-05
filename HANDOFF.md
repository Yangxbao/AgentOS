# AgentOS 项目交接文档（唯一入口）

> **给接手者**：读完这一份就能接手，不需要读其他文档。
> 本文覆盖 **M0 → M3-A** 的完整现状：环境、代码、数据、权限、命令、坑、下一步。
> 版本：2026-11-05｜当前 HEAD 以 `git log -1` 为准｜M3-A 代码提交：`1b0198d`｜数据库 revision：`m3_a_tools`

---

## 0. 30 秒了解

AgentOS 是一个**本地运行的 AI 数字员工协作操作系统**：用户建公司 → 建部门/岗位 → 建 AI 员工（绑定模型、提示词、权限）→ 建任务并派工 → AI 员工真实执行（可多 Agent 协作、可人工审批）→ 全过程可追溯、可计成本。

**当前能做什么**（已实现并验收）：

- 组织/员工/模型连接/提示词版本/权限/派工/审计（M1）
- 任务中心 + 后台执行引擎 + 多 Agent 协作 + 人工审批暂停恢复 + 监控与成本（M2）
- **工具执行层**（M3-A）：工作区授权、文件读写、HTTP 白名单、五层权限、工具调用审计、高风险工具人工审批、断点恢复（M3-A）

**当前不能做什么**（未实现，别以为是 bug）：

- Shell 执行（永久禁用，无代码路径）
- 递归多层任务拆分、长期记忆/RAG、多 Worker、预算熔断（M3-B/C/D/E/F）
- 真实外部网络访问（未授权，HTTP 只测本机 stub）
- 账号体系（本地单用户 `owner_id="local"`）

**代码规模**：Python 约 1.4 万行（packages + apps + scripts），React 前端 13 个页面（14 条路由，含 `/` 重定向），21 张表，80 个 `/api/v1` route-method 对。

---

## 1. 这台机器与项目位置

| 项 | 值 |
|---|---|
| 项目根目录 | **`E:\AgentOS`**（所有命令都在这里执行） |
| 操作系统 | Windows（本地单用户；路径大小写不敏感） |
| Python 解释器 | **`E:\AgentOS\.venv\Scripts\python.exe`**（3.13.14）——**不要用系统 python**，依赖只装在这个 venv 里 |
| 包安装方式 | `pip install -e .`（已装，`agentos.egg-info` 是产物）；从任意目录都能 import `packages.*` / `apps.*` |
| Node / npm | v22.22.2 / 10.9.7；前端依赖在 `E:\AgentOS\apps\web\node_modules`（已装） |
| 数据库 | `E:\AgentOS\data\agentos.db`（SQLite WAL），**21 张表，revision `m3_a_tools`** |
| 后端端口 | **8000**（只监听 127.0.0.1） |
| 前端端口 | **5173**（Vite dev；`scripts/serve_web.py` 也用这个端口） |
| 浏览器验收调试端口 | **9333**（Edge `--remote-debugging-port`） |
| 浏览器 | 本机只有 **Microsoft Edge**（没有 Chrome，也没装 Playwright） |

### 1.1 本机硬约束（重要）

1. **不要安装** Playwright / Docker / CrewAI / Codex CLI / Rust / MSVC 等重组件——任务书明确禁止，且本机也没有。
2. **不要改** Windows Defender、防火墙、注册表、系统环境变量、代理设置。
3. **不要推 GitHub**、不要公网部署（本机代理只放通 `api.github.com`，`github.com` 被拦；如需推代码只能用 GitHub Git Data API）。
4. **不要删除** `data/agentos.db`、`data/backups/`、`E:\AgentOS\data\workspaces`。
5. 真实模型调用**会产生费用**：当前 `E://AgentOS//.env` 已显式设置 `AGENTOS_MODEL_MODE=mock`（不产生外部调用）。注意 `auto` 模式在**该变量为空时会按 real 处理**，改 `.env` 前先想清楚；确需真实调用时同时限制 `AGENTOS_MAX_TOKENS`。
6. 生成文件时注意编码：`alembic.ini` 必须是 **ASCII**（中文注释会触发 cp936 解析失败）；`.ps1/.bat` 里不要写非 ASCII 路径。

### 1.2 数据目录约定

```
E:\AgentOS\data\
  agentos.db              ← 真实库（不要动；改结构只能向前迁移）
  backups\agentos_<时间戳>\ ← 备份（agentos.db + manifest.json + prompts/）
  prompts\employees\<id>\ ← 员工提示词文件（vNNNN.md，不可变，SHA-256 校验）
  workspaces\<slug>\      ← 工作区默认根（Agent 文件工具只能访问这里）
  browser_acceptance.db   ← 浏览器验收临时库（可删，脚本每次重建）
```

`data/` 整个目录在 `.gitignore` 里——**数据库、提示词文件、工作区文件都不入库**，交接/迁移要靠备份或导出包。

---

## 2. 5 分钟跑起来

### 2.1 最短路径（后端 + 前端 dev）

```bat
cd /d E:\AgentOS

REM 1) 确认数据库是最新结构（幂等，已最新则无输出）
.venv\Scripts\python.exe -m alembic upgrade head

REM 2) 起后端（只监听 127.0.0.1:8000）
.venv\Scripts\python.exe scripts\run_api.py --port 8000

REM 3) 另开一个终端起前端
cd /d E:\AgentOS\apps\web
npm run dev
```

打开 `http://127.0.0.1:5173`，右上角应显示 **“后端已连接 · v0.3.0-m3a”**。

健康检查：

```bat
curl --noproxy "*" http://127.0.0.1:8000/api/health
→ {"status":"ok","mode":"local","version":"0.3.0-m3a"}
```

> 本机有系统代理，`curl`/Python 访问 127.0.0.1 必须绕过代理（`--noproxy "*"` 或 `ProxyHandler({})`），否则会被拦。

### 2.2 用构建产物预览（更像生产，浏览器验收用这个）

```bat
cd /d E:\AgentOS\apps\web
npm run build                       REM 产物在 apps/web/dist
cd /d E:\AgentOS
.venv\Scripts\python.exe scripts\serve_web.py --port 5173
```

### 2.3 首次从零安装（换机器时）

```bat
cd /d E:\AgentOS
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env              REM 然后填 DEEPSEEK_API_KEY（只在 real 模式用）
.venv\Scripts\python.exe -m alembic upgrade head
cd apps\web && npm install
```

---

## 3. 环境变量全表

`.env` 在 **`E:\AgentOS\.env`**（已 gitignore；`apps/api/main.py` 启动时 `load_dotenv(ROOT/".env")`）。
**密钥永远只写引用**：数据库里存 `env:VAR_NAME`，代码运行时才解析成真实值；日志/审计/导出包都会被脱敏。

| 变量 | 默认 | 作用 | 读取位置 |
|---|---|---|---|
| `AGENTOS_DB_URL` | `sqlite:///E:/AgentOS/data/agentos.db`（绝对路径） | 数据库连接串；测试用它指向临时库 | `packages/persistence/db.py` |
| `AGENTOS_MODEL_MODE` | 空 → 视为 **real** | `mock` 时不调用任何外部模型、cost=0、`billable=false`；`real` 才真调 | `packages/tasks/service.py::resolve_mode` |
| `AGENTOS_MOCK_DELAY_MS` | `0` | Mock 每步人为延迟（测试暂停/取消用） | `packages/execution/adapter_factory.py` |
| `AGENTOS_MAX_TOKENS` | `1024` | 真实调用单次输出上限（成本护栏） | 同上 |
| `AGENTOS_PROMPTS_ROOT` | `data/prompts` | 提示词文件根目录（测试必须隔离，否则对账脚本报孤儿） | `packages/prompts/service.py` |
| `AGENTOS_RUNNER_DISABLED` | 未设 | `1` 时不启动后台执行 worker（仅供单测/调试） | `packages/execution/runner.py` |
| **`AGENTOS_TOOL_EXECUTION`** | **`off`** | **全局工具开关**。`on` 才可能执行工具；仍需公司策略+员工白名单+工作区授权 | `packages/tools/policy.py` |
| `AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK` | `0` | 仅测试用：允许 `http.request` 访问白名单内的回环地址 | `packages/tools/http.py` |
| `AGENTOS_TRUSTED_ORIGINS` | 空 | 额外可信 Origin，逗号分隔（默认已含 5173 两个） | `apps/api/security/local_guard.py` |
| `AGENTOS_LOCAL_TOKEN` | 空 | 设置后写请求必须带 `X-AgentOS-Token`（脚本/CLI 用） | 同上 |
| `AGENTOS_ALLOW_EXTERNAL` | `0` | `1` 才允许 `--host 0.0.0.0`（默认拒绝启动） | `scripts/run_api.py` |
| `AGENTOS_MODE` | `local` | 只回显在 `/api/health`，无功能含义 | `apps/api/routers/legacy.py` |
| `DEEPSEEK_API_KEY` | 空 | 真实调用凭据（`.env` 里已有）；**不要打印、不要写进任何文件** | litellm 原生机制 |

> 两个最容易踩的：**① `AGENTOS_TOOL_EXECUTION` 默认 off**，所以“工具不执行”通常是正常配置，不是 bug；**② `AGENTOS_MODEL_MODE` 为空时 `auto` 会走 real**——本机 `.env` 已设为 `mock`，`tests/conftest.py` 也已 autouse 设为 mock，但你自己起服务时不要把它删掉。

---

## 4. 目录地图

```
E:\AgentOS\
├── apps\
│   ├── api\                     FastAPI 入口与路由
│   │   ├── main.py              create_app()：lifespan + 中间件 + 挂载 12 个 v1 router（+ legacy）
│   │   ├── deps.py              get_db / ActorContext / 分页
│   │   ├── errors.py            统一错误包络 + request_id
│   │   ├── audit.py             路由层审计（自动补 request_id）
│   │   ├── security\local_guard.py   Host/Origin/X-AgentOS-Client/Sec-Fetch-Site 防护
│   │   ├── routers\             companies/departments/positions/employees/model_connections/
│   │   │                        prompts/governance/config_io/tasks/approvals/monitor/tools/legacy
│   │   └── schemas\             请求/响应模型
│   └── web\                     React 18 + TS + Vite + Tailwind v4 + TanStack Query + React Flow
│       ├── src\App.tsx          ！全部路由与导航在这里
│       ├── src\api\             每个后端域一个客户端文件（org/people/tasks/tools/prompts/governance/config）
│       └── src\pages\           14 个页面
├── packages\                    领域层（不依赖 FastAPI）
│   ├── organization\            公司/部门/岗位/员工/模型连接/组织树
│   ├── permissions\             effective(三层交集)/policy(审批边界)/audit(脱敏)/assignment(派工)
│   ├── tasks\                   state(状态机)/service(CRUD+入队)/plan/approvals/decompose
│   ├── execution\               executor(执行)/runner(DB队列)/tool_loop/guard/prompting/observability
│   ├── tools\                   registry/schema/paths/workspaces/fs/http/shell/policy/invoke
│   ├── prompts\                 提示词版本（文件+DB 指针+哈希）
│   ├── config_io\               公司配置导入导出（zip）
│   ├── model_gateway\           gateway(LiteLLM)/catalog/credentials/health
│   ├── agent_core\              adapter(LiteLLM Adapter)/capabilities
│   ├── workflow_engine\         M0 的 LangGraph 顺序/审批图（仍保留）
│   ├── persistence\             models(SQLAlchemy)/db(引擎、session)
│   └── shared\                  types / errors
├── migrations\versions\         0001..0008（见 §6.3）
├── scripts\                     run_api/serve_web/backup_db/reconcile_prompts/e2e_m1/e2e_m2/browser_acceptance/m0_verify
├── tests\                       297 passed / 3 skipped（见 §10）
├── docs\                        architecture/decisions/development/product/research/testing
├── data\                        ← gitignore（库/备份/提示词/工作区）
├── HANDOFF.md                   ← 本文（唯一交接入口）
├── M3_MASTER_PLAN.md            M3 设计（B/C/D/F 的架构设计在这里，写后续阶段前读）
├── README.md / CHANGELOG.md
├── alembic.ini / pyproject.toml / requirements*.txt
└── .env                         ← gitignore（密钥在这里）
```

---

## 5. 架构：一次任务是怎么跑完的

### 5.1 分层

```
浏览器 (5173)
   │  fetch + X-AgentOS-Client: web
   ▼
LocalGuard → RequestId → CORS → FastAPI routers (/api/v1)
   │
   ▼
packages/* 领域服务（纯 Python，可用 pytest 直接测）
   │
   ├── organization / permissions / prompts / config_io
   ├── tasks（状态机/入队/审批）
   └── execution（后台 worker + 执行器 + 工具循环）
          │
          ├── model_gateway → LiteLLM → 供应商
          └── tools → 文件 / HTTP（受五层权限约束）
   ▼
SQLite（WAL）
```

### 5.2 任务执行链路（M2）

1. `POST /api/v1/companies/{cid}/tasks` 创建任务（`state=draft`），可带计划（steps）或单步执行。
2. `POST /api/v1/tasks/{id}/run` → `tasks.service.enqueue_run()`：写一条 `task_run(state=queued)`，任务转 `queued`。
3. 后台 `TaskRunner`（`packages/execution/runner.py`，API 启动时通过 lifespan 拉起）每 0.4s 轮询，**原子认领**（`UPDATE ... WHERE state='queued'`）→ `running`。
4. `execute_run()`（`executor.py`）按 `topological_waves(plan)` 分波执行；每波 `asyncio.gather` 并行，每步：
   - 建 Adapter（`adapter_factory.build_adapter`，mock/real 显式）
   - `guard.check_execution`：在职/同公司/风险/工具/预算闸门
   - 拼系统提示词（`prompting.build_system_prompt`，含员工提示词版本）
   - **有工具授权 → `tool_loop.run_tool_loop`；否则 → M2 单次模型调用**
   - 写 `agent_run` + `usage_record` + `agent_handoff` + `task_event`，更新 `task_run.checkpoint`
5. 完成 → `task.succeeded` + `task.result`；失败 → `task.failed`；暂停/取消在**波次边界**生效。
6. 进程重启：`runner.recover()` 把遗留 `running` 标为 `interrupted`，任务转 `paused`，人工恢复后从 `checkpoint` 续跑。

**关键不变量**：
- `task.state` 是唯一权威（`packages/tasks/state.py` 的迁移表），AI 说自己“完成了”不改状态。
- 同一任务同时最多一条活跃 run（部分唯一索引 `uq_task_run_active`）。
- 每步完成即提交，崩溃可续；`checkpoint.completed_steps` 防重复执行。

### 5.3 工具循环与工具审批（M3-A）

```
模型 → 只带"已授权工具"的 schema
  → 模型返回 tool_calls
  → packages/tools/invoke.invoke_tool（唯一入口）
       参数校验 → policy.decide（五层）→ 幂等键 → 执行/挂起
  → 结果包成 <untrusted_tool_result> 回灌模型
  → 没有 tool_calls 时返回最终文本
```

- 次数上限：`company.policy.tools.max_tool_calls_per_step`（默认 8）→ `TOOL_LOOP_EXCEEDED`。
- 需要审批时：`tool_call(status=awaiting_approval)` + `task_approval(gate=tool_call, tool_call_id=...)`，`task_run.checkpoint.tool_state` 保存 `messages / pending / call_index`，任务 `awaiting_approval`。
- 批准：`approvals.decide` 把 `tool_call` 置 `approved` → 入队新 run → 工具循环**直接执行 pending 调用**（不重新调模型生成同一个 tool_call）→ 继续循环。
- 驳回：`tool_call → denied`、`error_code=TOOL_APPROVAL_REJECTED`，任务 `failed`（可重试）。

### 5.4 五层权限（写工具相关代码前必须看懂）

```
1 全局开关   AGENTOS_TOOL_EXECUTION=on
2 公司策略   company.policy.tools.{enabled, categories, allowed_tools, network_domains,
             allow_http_write, max_risk_level(绝对上限), auto_execute_max_risk}
3 员工白名单 employee.tools_allowed（精确工具名；空 = 不允许任何工具）
4 岗位/员工  permission_profile.tools（非空时进一步收窄）
5 工作区     employee_workspace_grant.access(read|write) + workspace.mode(read_only|read_write)
```

风险规则：
- `risk > 公司 max_risk_level`（默认 high）→ **直接拒绝** `RISK_EXCEEDED`；
- `risk > min(员工 max_risk_level, 公司 auto_execute_max_risk)`（默认 medium）→ **转人工审批**；
- `shell` 类别无条件 `SHELL_DISABLED`。

---

## 6. 数据模型（21 张表）

### 6.1 分组

| 组 | 表 | 说明 |
|---|---|---|
| 组织 | `company` `department` `position` `employee` `employee_position` `model_connection` `model_switch_log` | 公司策略在 `company.policy`（JSON）；岗位默认权限在 `position.default_permissions` |
| 提示词 | `prompt_revision` | 只存文件路径 + SHA-256 + 激活指针；正文在 `data/prompts/` |
| 权限/派工 | `employee_workspace_grant` `assignment_decision` `audit_log` | 审计只增不改 |
| 任务 | `task` `task_run` `agent_run` `agent_handoff` `task_event` `task_approval` | `task` 同时表示父任务与子任务（`parent_task_id`） |
| 工具 | `workspace` `tool_call` | 每次调用一条记录，含 args_hash / idempotency_key / approval_id |
| 计费 | `usage_record` | `cost_usd` 可为 NULL（计价失败不编造）；`billable=false` 表示 Mock |
| 迁移 | `alembic_version` | 当前 `m3_a_tools` |

### 6.2 真实库现状（不要破坏）

```
task 4 / task_run 4 / agent_run 4 / usage_record 4 / task_event 8   ← M0 历史数据，只读保留
company 0 / employee 0 / workspace 0 / tool_call 0 / audit_log 0
```

M0 历史任务的 `employee_key` 是字符串（如 `m0-researcher`），**不回填**成真实员工；`company_id` 为 NULL，UI 里按“遗留”处理。

### 6.3 迁移链（只能向前）

```
m0_baseline → m1_b1_agent_run_employee_id → m1_b2_org → m1_b3_employee_model
→ m1_b4_prompt → m1_b5_assignment_audit → m2_task_center → m3_a_tools
```

命令：

```bat
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic revision --autogenerate -m "描述"   REM 生成后必须人工裁剪
```

**改库铁律**：
1. 先备份：`.venv\Scripts\python.exe scripts\backup_db.py`
2. 先在**空库**和**旧库副本**上验证（`AGENTOS_DB_URL=sqlite:///.../tmp.db alembic upgrade head`）
3. 再对真实库 `upgrade head`
4. **不要对真实库 downgrade**；SQLite 用 `batch_alter_table`
5. 迁移前确认 `data/agentos.db` 里 4 条历史任务还在（`tests/test_migrations.py` 会断言）

---

## 7. API 与前端页面

### 7.1 API

前缀 `/api/v1`（`/api` 保留 M0 的 health/tasks 兼容）。共 **80 个 route-method 对**：

| 域 | 数量 | 代表端点 |
|---|---|---|
| 公司/部门/岗位 | 16 | `/companies`、`/companies/{cid}/org-tree`、`/departments/{id}/move` |
| 员工/模型连接 | 16 | `/companies/{cid}/employees`、`/employees/{id}/model-binding`、`/model-connections/{id}/test` |
| 提示词/导入导出 | 7 | `/employees/{id}/prompts`、`/companies/{cid}/export`、`/config/import?dry_run=true` |
| 治理 | 6 | `/employees/{id}/effective-permissions`、`/assignments/preview`、`/audit` |
| 任务/审批/监控 | 21 | `/companies/{cid}/tasks`、`/tasks/{id}/run`、`/approvals/{id}/decision`、`/tasks/{id}/timeline` |
| **工具（M3-A）** | 14 | `/companies/{cid}/workspaces`、`/workspaces/{id}/grants`、`/tools`、`/companies/{cid}/tool-policy`、`/tasks/{id}/tool-calls` |

约定：
- 错误统一 `{"error": {"code", "message", "detail", "request_id"}}`；HTTP 状态码语义化（403 权限、409 冲突、422 参数、413 过大、504 超时）。
- 列表分页 `?page=1&page_size=20`（≤200）。
- 写请求必须带 `Origin: http://127.0.0.1:5173` 和 `X-AgentOS-Client: web`（否则 403）。
- 诊断接口：`GET /api/v1/employees/{id}/tool-permissions` 会告诉你每个工具为什么不可用。

### 7.2 前端路由（`apps/web/src/App.tsx`）

| 路由 | 页面 | 说明 |
|---|---|---|
| `/tasks`、`/tasks/:id` | 任务中心 / 任务详情 | 详情含状态动作、计划、**工具调用面板**、审批、执行记录、时间线、成本 |
| `/monitor` | 执行监控 | 状态分布、待审批、今日成本、最近 Agent 执行 |
| `/org` | 组织架构图 | React Flow，公司/部门/员工节点 |
| `/employees`、`/employees/:id` | 员工列表 / 详情 | 详情含有效权限、提示词版本、模型绑定 |
| `/assignments` | 派工预览 | 候选打分、审查人推导、`data_quality` 标注 |
| `/settings/workspaces` | 工作区管理 | 创建/改名/归档、员工授权矩阵 |
| `/settings/tools` | 工具策略 | 全局开关状态、类别、白名单、域名、风险上限、工具目录 |
| `/settings/models` | 模型连接 | 创建/测试/删除 |
| `/settings/import-export` | 导入导出 | zip 导出、dry-run 导入 |
| `/settings/audit` | 审计 | 只读列表 |
| `/settings/organization` | 组织设置 | 公司/部门/岗位 CRUD |

前端约定：API 路径**必须**带 `/api/v1` 前缀；`src/api/client.ts` 自动补 `X-AgentOS-Client`；后端地址由 `VITE_API_BASE` 覆盖（默认 `http://127.0.0.1:8000`）。

---

## 8. 权限与安全（改代码前必读）

### 8.1 已实现的硬边界

| 边界 | 实现 |
|---|---|
| 本地管理接口 | 默认只监听 127.0.0.1；Host/Origin/`X-AgentOS-Client`/`Sec-Fetch-Site` 四重校验；可选本地 token；写请求缺头一律 403 |
| 文件访问 | 只能在工作区内；`safe_resolve` 拒绝绝对路径/盘符/UNC/ADS/NUL/`..`/保留设备名，逐级查 symlink/junction，resolve 后做真实路径包含判断 |
| 敏感文件 | `.env*`、`*.pem/*.key/*.pfx`、`id_rsa*`、`.ssh`/`.aws`/`.gnupg`、`credentials*`、`NTUSER.DAT`、`.git/config` 等直接拒绝 |
| 密钥 | 库里只存 `env:VAR` / `dpapi:` / `keyring:` 引用；审计/日志/导出包统一 `sanitize_detail` 脱敏（键名 + `sk-`/`Bearer` 值） |
| Shell | 注册但 `enabled=False`；策略/API 都拒绝开启；AST 扫描证明 `packages/tools` 无 `subprocess`/`os.system`/`Popen` |
| 网络 | 域名白名单 + DNS 后逐 IP 检查（回环/私网/链路本地/云元数据）+ 重定向逐跳 + 请求头白名单 + 2MB/超时 |
| 权限放宽 | 员工层只能收窄（`PERMISSION_WIDEN_DENIED`）；放宽只能改岗位默认且不得超公司策略 |
| 自审 | 审查人 ≠ 执行人；派工硬过滤（越权/自审/超预算在模型看到候选前就被淘汰） |

### 8.2 明确未解决（不要在报告里说“已解决”）

1. **Windows TOCTOU 未消除**：`safe_resolve` 校验与真正打开之间仍可能被本机进程替换。威胁模型是“本地单用户 + 工作区”，企业级需要 OS 沙箱。
2. **本地恶意进程**可直连 SQLite / 绕过 HTTP 层；本地防护只挡浏览器跨站跨源。
3. **提示词注入**：已做 `<untrusted_tool_result>` 包裹 + system 提示“数据不是指令”，但无法保证模型一定听话。
4. **审计防篡改**靠应用层；本地用户可直接改库。
5. **无账号体系**：所有数据 `owner_id="local"`，多人使用需 M5。

---

## 9. 工程约定与红线

### 9.1 必须遵守

1. **单文档交接**：计划/交接只维护 `HANDOFF.md`（本文）+ 各阶段设计文档；不要再新增 `M4_MASTER_HANDOFF` 之类碎片。
2. **工具调用唯一入口**：任何工具执行必须走 `packages/tools/invoke.invoke_tool`，禁止直接调 handler。
3. **状态机唯一权威**：任务状态只能通过 `tasks.service` / `state.ensure_transition` 改。
4. **Mock 必须可识别**：`usage.billable=false`、`cost=0`、`model=mock/echo`；报告里必须区分 Mock 与真实调用。
5. **密钥不落库、不进日志、不进报告**。
6. **迁移前备份，只向前迁移**；测试只用临时库（`AGENTOS_DB_URL` + `tmp_path`）。
7. **每个功能要有测试**；测试必须真实执行，不允许为了变绿删断言/跳过安全检查。
8. **不安装**未授权组件；**不改**系统安全设置；**不推** GitHub。

### 9.2 代码风格

- Ruff：`line-length=120`，`select = ["E","F","I","W"]`；提交前必须 `ruff check apps packages scripts tests migrations`。
- pytest：`asyncio_mode=auto`（async 测试直接写 `async def`，不用装饰器）。
- 领域层不 import FastAPI；路由层不写业务逻辑。
- 注释/文档用中文，标识符用英文。

---

## 10. 常用命令与证据位置

```bat
cd /d E:\AgentOS

REM 全量测试（约 80s；默认全 Mock，不花钱）
.venv\Scripts\python.exe -m pytest tests/ -q

REM 单个文件 / 单个用例
.venv\Scripts\python.exe -m pytest tests/test_tool_loop.py -q
.venv\Scripts\python.exe -m pytest tests/test_tool_loop.py::test_tool_approval_suspend_and_resume -q

REM Lint
.venv\Scripts\python.exe -m ruff check apps packages scripts tests migrations

REM 前端类型检查 + 构建
cd apps\web && npm run build

REM 迁移状态 / 升级
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic upgrade head

REM 备份数据库（生成 data/backups/agentos_<时间戳>/）
.venv\Scripts\python.exe scripts\backup_db.py

REM 提示词文件与数据库对账（只读，0/0/0 才算健康）
.venv\Scripts\python.exe scripts\reconcile_prompts.py

REM M2 端到端（13 项，全 Mock）
.venv\Scripts\python.exe scripts\e2e_m2.py

REM 真实浏览器验收（Edge + CDP；会自己起 8000/5173，跑完写证据）
.venv\Scripts\python.exe scripts\browser_acceptance.py
```

### 10.1 当前基线（2026-11-05 实测）

```
pytest tests/ -q                                  → 297 passed, 3 skipped
ruff check ...                                    → All checks passed!
cd apps/web && npm run build                      → ✓ 488 kB (gzip 149 kB)
alembic current                                   → m3_a_tools (head)
reconcile_prompts.py                              → orphan 0 / missing 0 / mismatch 0
scripts/e2e_m2.py                                 → 13 项全过
scripts/browser_acceptance.py                     → 29 项全过（0 失败，0 JS 异常）
```

### 10.2 测试地图（改哪里看哪个文件）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `test_tool_paths.py` | 60 | 路径逃逸/敏感文件/junction（2 个 symlink 用例在无权限环境 skip） |
| `test_tool_policy.py` | 23 | 五层权限每个拒绝码 |
| `test_tool_fs.py` | 22 | 文件工具行为与错误码 |
| `test_tool_http.py` | 17 | 白名单/SSRF/重定向/超时/大响应（本机 stub） |
| `test_tool_invoke.py` | 14 | 落库/审计/脱敏/幂等/超时/截断 |
| `test_tool_loop.py` | 13 | 工具循环、8 次上限、审批挂起与恢复、驳回 |
| `test_shell_disabled.py` | 9 | Shell 多重证明（含 AST 扫描） |
| `test_tool_api.py` | 13 | 工作区/授权/策略/调用列表 API |
| `test_task_center.py` / `test_execution.py` / `test_collaboration.py` / `test_approvals.py` / `test_observability.py` | 8/11/7/6/6 | M2 任务/执行/协作/审批/监控 |
| `test_migrations.py` | 2 | 空库 + 旧库迁移，schema 一致 + 历史数据保留 |
| 其余 | — | M1 组织/员工/权限/提示词/导入导出/审计等 |

### 10.3 证据文件

| 文件 | 内容 |
|---|---|
| `docs/testing/m3a_final_regression.txt` | M3-A 最新一次 pytest/ruff/build/alembic/真实库/对账/浏览器 的真实输出 |
| `docs/testing/m3_browser_acceptance.txt` | 29 项浏览器验收逐项结果 |
| `docs/testing/m3_browser/*.png` | 8 张 M3-A 截图（m3_01..m3_08：工作区/策略/工具面板/审批/驳回）+ M2 的 13 张 |
| `docs/testing/m2_*.txt` | M2 的回归与 E2E 证据 |

---

## 11. 当前状态：已完成 / 未完成 / 风险

### 11.1 里程碑

| 阶段 | 状态 | 关键产出 |
|---|---|---|
| M0 | 完成 | LangGraph 顺序执行、LiteLLM 网关、Adapter 抽象、5 张表 |
| M1 | 完成（P1 已清） | 组织/员工/模型解耦/提示词版本/三层权限/派工/审计；91 测试 |
| M2 | 完成 | 任务中心/执行引擎/多 Agent/审批/监控；129 测试 |
| **M3-A** | **完成** | 工具执行层；新增 171 测试，总 297；浏览器 29/29 |
| M3-E | 未开始 | 预算熔断、连续拒绝暂停、kill switch |
| M3-B | 未开始 | 递归拆分、重规划 |
| M3-C | 未开始 | 长期记忆（计划用 SQLite FTS5，不接 embedding） |
| M3-D | 未开始 | 多 Worker 租约/心跳/幂等 |
| M3-F | 未开始 | 真实业务验收（GitHub 教程生成） |

### 11.2 风险清单

| 级别 | 项 | 建议 |
|---|---|---|
| P0 | 无 | — |
| P1 | 真实模型工具调用**未验证**（本轮 0 次真实调用，只做了 LiteLLM tools 适配 + Mock 全链路） | 允许时用已有 Key 跑一次 `max_tokens=64` 的最小验证 |
| P1 | 无预算熔断 | M3-E 第一件事 |
| P1 | workspace/policy 的审计与业务非同事务（工具调用本身已同事务） | 可接受，极端崩溃会缺一条审计 |
| P2 | 工作区改名用 `window.prompt`；域名白名单无排序；`fs.list_dir` 无隐藏文件开关 | 打磨项 |
| P2 | 前端未做拖拽移动部门 | 后端 `/move` 已有 |

### 11.3 真实模型调用记录（诚实账）

- M2 验收：4 次（两次单步 + 一次两步协作），353 tokens，≈ **$0.00006285**。
- M3-A：**0 次**。
- 所有测试与浏览器验收默认 Mock；`usage_record.billable=false`。

---

## 12. 下一步（M3-E）具体清单

按 `M3_MASTER_PLAN.md` §13 的 M3-E 验收做，建议落点：

1. **预算**：新增 `packages/execution/budget.py`
   - 读 `task.budget_usd` + 公司策略默认预算；按 `usage_record` 累计 cost 与 tokens
   - 超限：`task.state=paused` + `TaskEvent("task.budget_exceeded")` + `task.result.error`
   - 在 `executor._run_step` 调模型前检查，`tool_loop` 每次工具调用后也检查
2. **连续拒绝/失败**：`task_run.checkpoint` 里累计 `denied_count`，≥3 → 暂停并提示“检查授权”
3. **全局 kill switch**：`POST /api/v1/system/tool-execution`（仅本地用户）→ 写公司策略或进程级开关，审计留痕
4. **监控**：`/monitor` 增加工具调用统计、拒绝原因 Top N、预算使用率
5. **验收**：单步 8 次工具 → 终止；超预算 → paused；连续 3 次拒绝 → paused；`AGENTOS_TOOL_EXECUTION=off` → 所有调用拒绝且任务可读地失败

**不要先做 M3-B**：递归会放大成本与失控风险，等 E 的闸门就位。

---

## 13. 已知坑（都踩过，别再踩）

| 坑 | 现象 | 处理 |
|---|---|---|
| `alembic.ini` 含中文 | cp936 解析失败，alembic 起不来 | 保持纯 ASCII |
| SQLite WAL 读快照 | 执行器看不到其他会话提交的 cancel/pause | 每波开始 `session.commit()` 再 `expire_all()` 重读 |
| 步骤会话持写锁 | `POST /cancel` 被阻塞到步骤结束 | 子任务置 `running` 后立即 `commit()` |
| `monkeypatch` 打错位置 | 替换 `adapter_factory.build_adapter` 无效 | 执行器是 `from ... import build_adapter`，要打 `packages.execution.executor.build_adapter` |
| 系统代理 | `curl`/`urllib` 访问 127.0.0.1 超时/被拦 | `curl --noproxy "*"`；Python `build_opener(ProxyHandler({}))`（工具 HTTP 已内置） |
| 测试污染真实提示词目录 | 对账脚本报孤儿 | `AGENTOS_PROMPTS_ROOT` 指向 tmp（conftest 已 autouse 隔离） |
| 测试污染真实工作区 | `data/workspaces/ws-*` 残留 | 测试用 `tmp_path` 作 `root_path` |
| 工具“不执行” | 任务正常完成、0 条 tool_call | 先看 `AGENTOS_TOOL_EXECUTION`（默认 off）→ 公司策略 → 员工 `tools_allowed` → 工作区授权 |
| 浏览器验收端口占用 | 脚本起不来 | 先确认 8000/5173/9333 没被占用 |
| UI 建任务默认 `execution_mode=auto` | 没设 `AGENTOS_MODEL_MODE` 时会真实调用并计费 | 保持 `.env` 里 `AGENTOS_MODEL_MODE=mock`，或建任务时显式选 mock |
| Edge 启动参数 | 用 `--headless=new` + `--remote-debugging-port=9333`；`PUT /json/new` 建 target | 见 `scripts/browser_acceptance.py` |
| 前端 API 前缀 | 404 | 路径必须 `/api/v1/...`（`src/api/client.ts` 只拼 base） |
| 前端刷新后状态旧 | 面板显示 0 次 | TanStack Query 轮询；动作后 `invalidateQueries` |
| `data/` 被 gitignore | 换机器后数据没了 | 用 `scripts/backup_db.py` 或导出包迁移 |

---

## 14. 想改 X 去哪里找

| 想改 | 文件 |
|---|---|
| 任务状态/迁移规则 | `packages/tasks/state.py` |
| 任务 CRUD / 入队 / 暂停恢复 | `packages/tasks/service.py` |
| 执行流程 / 检查点 / 工具分流 | `packages/execution/executor.py` |
| 后台 worker / 认领 / 重启恢复 | `packages/execution/runner.py` |
| 工具循环 / 审批挂起状态 | `packages/execution/tool_loop.py` |
| 工具定义 / 新增工具 | `packages/tools/registry.py`（+ 对应 handler） |
| 路径安全 | `packages/tools/paths.py` |
| 五层权限 | `packages/tools/policy.py` |
| 工具执行/落库/审计 | `packages/tools/invoke.py` |
| 工作区/授权 | `packages/tools/workspaces.py` |
| 审批决策 | `packages/tasks/approvals.py` |
| 三层权限交集 | `packages/permissions/effective.py` |
| 派工/审查人 | `packages/permissions/assignment.py` |
| 审计脱敏 | `packages/permissions/audit.py` |
| 模型调用 | `packages/model_gateway/gateway.py` |
| 系统提示词 | `packages/execution/prompting.py` |
| 表结构 | `packages/persistence/models.py` + `migrations/versions/` |
| 路由 | `apps/api/routers/*.py` |
| 前端路由/导航 | `apps/web/src/App.tsx` |
| 前端 API 客户端 | `apps/web/src/api/*.ts` |

---

## 15. 交接自检清单（新接手者按顺序做）

```bat
cd /d E:\AgentOS
.venv\Scripts\python.exe -m alembic current                  REM 期望 m3_a_tools (head)
.venv\Scripts\python.exe -m pytest tests/ -q                 REM 期望 297 passed, 3 skipped
.venv\Scripts\python.exe -m ruff check apps packages scripts tests migrations
cd apps\web && npm run build && cd ..\..
.venv\Scripts\python.exe scripts\backup_db.py                REM 先备份再动库
.venv\Scripts\python.exe scripts\browser_acceptance.py       REM 期望 29 项通过
git status                                                   REM 期望干净
```

- [ ] 上面 6 条命令全部符合预期
- [ ] 打开 `http://127.0.0.1:5173` 能看到任务中心，右上角显示 v0.3.0-m3a
- [ ] `GET /api/v1/tools` 返回 7 个工具，`shell.run.enabled=false`
- [ ] 明白 `AGENTOS_TOOL_EXECUTION` 默认 off，工具不执行是配置而非 bug
- [ ] 知道真实库有 4 条 M0 历史任务，不能清空/回填
- [ ] 知道不要装 Playwright/Docker，不要推 GitHub

---

## 附：其他文档的定位（不需要读）

| 文档 | 定位 |
|---|---|
| `M3_MASTER_PLAN.md` | M3 的**设计**（B/C/D/F 的架构、权限模型、记忆/Worker 方案）。写后续阶段前读对应章节。 |
| `M2_MASTER_PLAN.md` / `M2_MASTER_HANDOFF.md` | M2 设计与当期交接（历史）。 |
| `M1_PLAN_HANDOFF.md` | M1 单文档（组织/员工/模型/提示词/权限/派工/审计）。 |
| `M0_FINAL_HANDOFF.md` | M0 技术验证。 |
| `docs/architecture/` | 系统架构、数据库设计、Agent Adapter、安全模型。 |
| `docs/decisions/ADR_INDEX.md` | 已接受的架构决策（ADR）。 |
| `docs/development/ROADMAP.md` | 里程碑路线图。 |

**如果只看一份，就是本文。**
