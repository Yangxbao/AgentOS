# AgentOS M1 计划与交接文档（单一文档）

> 版本：v1.0｜日期：2026-11-05｜状态：**待项目所有者确认后开始编码**
> 用途：这份文档自包含，可直接交给另一个 AI 或开发者执行 M1。不需要再读其他文档。
> 文档约定：【已验证】= 有可复核证据｜【设计】= 本文档提出的方案｜【待确认】= 需所有者拍板

---

## 0. 给接手者的执行须知（先读这 6 条）

1. **不要立即大规模编码**。先读第 15 节的 6 个决策点，向所有者确认（或采用文档建议的默认值并声明）。
2. **严格按第 12 节的批次顺序**：B1 → B2 → B3 → B4 → B5 → B6。每批独立可验收，不得跳批。
3. **不要删除或弱化 M0 的 7 个测试**（清单见 §2.4）。它们是在册回归基线。
4. **禁止安装**：Codex CLI、CrewAI、Docker、Playwright 或任何需要系统权限的组件。禁止上传 GitHub。
5. **所有密钥只存引用**（`env:VAR`），禁止明文入库、入日志、入导出包、入 API 响应。
6. **每个功能四件齐才算完成**：领域服务 + 数据库持久化 + API + 测试。前端不允许假数据演示。

---

## 1. 项目是什么

**AgentOS（AI 数字员工协作操作系统）**：用户像经营公司一样创建 AI 公司、招聘 AI 员工、设置组织架构与权限，让多模型、多 Agent 团队在半自主（关键节点人工审批）模式下真实交付任务。

**核心命题（不可妥协）**：
- 不是多 AI 群聊工具，而是具备组织结构、任务管理、协作、监督、执行、交付能力的系统
- 每个 AI 员工有独立身份、岗位、能力、职责、权限
- 开发员不能自证代码没问题，测试员必须独立验证
- **组织关系必须真实影响任务分配**，员工权限必须真实可执行，不能只是 UI 上的角色名
- 用户始终拥有最终控制权

**已锁定的产品决策**：半自主（关键节点审批）｜Windows 本地 + 云端（本地优先）｜API + CLI 双接入｜组织自由定义｜模型不绑定供应商｜最小权限默认｜MIT 许可｜可运行可扩展可开源。

**安全红线（必须遵守，来自项目立项）**：不自动扫描/修改整台电脑；不默认读全盘；不自动删文件/装软件/关防护；不改系统环境变量；不逆向或绕过 AI 工具官方认证；API Key 不明文落日志；本地文件不自动上传；Agent 不得自提权、不得自批高危操作、不得借互相授权突破用户边界；不得无限循环/无限调模型；未授权不得执行任意终端命令。

---

## 2. 当前代码真实状态（M0 已完成，务必复用，不要重写）

### 2.1 仓库位置与结构
- 路径：`E:\AgentOS`（Windows，Git Bash，Python 3.13.14 venv 在 `.venv`，Node 22）
- Git：`main` 分支，已有 3 个 commit，未配置远程仓库
- 规模：Python 1189 行（`packages` + `apps` + `scripts` + `tests`）

```
apps/api/main.py                 FastAPI 单文件（3 个接口）
apps/web/                        React18+TS+Vite+Tailwind v4 骨架（仅 App.tsx）
packages/shared/types.py         CapabilitySet / AgentEvent / AgentTask / UsageReport
packages/model_gateway/gateway.py LiteLLM 封装：chat() + completion_cost
packages/agent_core/adapter.py   AgentAdapter Protocol + LiteLLMAdapter + collect_final
packages/persistence/            SQLAlchemy models(5 表) + db.py(SQLite WAL)
packages/workflow_engine/        sequential.py(双 Agent 交接) + approval_graph.py(LangGraph interrupt)
scripts/m0_verify.py             V1-V8 验证脚本
tests/                           7 个测试
docs/                            M0 调研/架构/产品文档（保留，不再扩写）
```

### 2.2 数据库（M0 已有的 5 张表，结构不可破坏）
`task`、`task_run`、`agent_run`、`task_event`、`usage_record`
关键设计：任务与执行记录分离（同一 task 多次 run 不覆盖）；`usage_record.cost_usd` 允许 NULL（计价失败不编造）；`agent_run.employee_key` 是临时字符串标识（M1 要加 `employee_id` 列过渡）。

### 2.3 已有接口（必须保持兼容）
`GET /api/health`、`GET /api/tasks`（真实读库）、`GET /api/employees/{model}/health`（经 LiteLLM 真实连通性测试）

### 2.4 回归基线（不得删改）
`tests/test_capability.py`（3 个：能力诚实性、interrupt 抛异常、能力序列化）、`tests/test_events.py`（2 个：事件序列化、cost=None 诚实）、`tests/test_persistence.py`（2 个：多 run 不覆盖、重启保留）——共 7 个，当前全绿；`ruff` 全绿；前端 `npm run build` 通过。

### 2.5 M0 已验证的事实（可放心依赖）
- LiteLLM → DeepSeek 真实调用成功，计价 $0.0000072/次（tokens 16+8），延迟约 1.4s【已验证】
- LangGraph `interrupt()` + `Command(resume)` 审批挂起/恢复可用，SqliteSaver 持久化 checkpoint【已验证】
- AgentAdapter 能力声明诚实性机制可用（不支持的能力调用即抛 `CapabilityNotSupported`）【已验证】
- SQLite 落库 + 进程重启后数据完整【已验证】

### 2.6 已识别的技术债（B1 必须还）
| 债务 | 现状 | 处理 |
|---|---|---|
| 无数据库迁移工具 | 只有 `create_all` | 引入 Alembic，`m0_baseline` stamp 已有库 |
| 包不可安装 | 依赖 `sys.path.insert` 才能 import | `pyproject.toml` 加 `[build-system]`，`pip install -e .` |
| `main.py` 单文件 + `on_event` 弃用 | 3 个接口挤在一起 | 拆 `routers/` + `lifespan` |
| 无统一错误格式/分页 | 各接口裸返回 | 统一错误包络 + 分页依赖 |
| 前端仅 1 页 | App.tsx 硬编码 | 逐批建页面 |
| `agent_run.employee_key` 字符串 | 临时设计 | 加 `employee_id` 列双写，M2 切换 |

---

## 3. M1 目标与非目标

### 3.1 目标（M1 结束时必须成立）
1. 5 分钟内从零建一家公司：部门、岗位、3 个员工、2 个模型连接，组织图正确反映汇报关系
2. 员工与模型彻底解耦：同模型服务多员工；员工可切主备模型；切换后历史/绩效/提示词全部保留
3. 每个员工的有效权限可计算、可解释（三层来源可见）、可审计
4. 组织关系可被程序消费：给定任务需求能产出带理由的候选人排序，并能沿汇报链推导审查人
5. 全部能力有真实后端 + 持久化 + 测试

### 3.2 非目标（M1 不做）
真实任务派发与状态机运行（M2；M1 只做"派工预览"）｜会议室（M4）｜审查报告与返工闭环（M3，M1 只推导"谁是审查人"）｜云端与设备注册（M5）｜多用户 SaaS（M6）｜MCP 工具实际执行（M2）｜CLI 员工真实执行（依赖 V7 解除，M2）

---

## 4. 领域概念与业务规则

### 4.1 概念
| 概念 | 定义 | 关键约束 |
|---|---|---|
| 公司 | 组织根节点，承载策略与预算 | 可多个；M1 至少 1 个 |
| 部门 | 树形结构 | 同公司名唯一；不得成环；最大 8 层 |
| 岗位 | 职责模板，含默认权限 | 可绑定部门或跨部门；员工可兼多岗（1 主 + n 兼） |
| 员工 | 身份 + 提示词 + 权限 + 模型引用 | 必须有公司和主模型；不得自改权限 |
| 模型连接 | 可测试的连接配置 | 只存密钥引用；被引用不可删 |
| 提示词版本 | 不可变的文件版本 | 只能新增，不能改历史 |
| 派工决策 | 候选人排序 + 理由 | 只增不改 |

### 4.2 业务规则（测试直接引用编号）
- **BR-01** 员工必须属于一个公司，且必须有 `primary_model_id`
- **BR-02** 部门名/岗位名在同公司内唯一
- **BR-03** 部门树最大深度 8
- **BR-04** 部门与汇报关系不得成环
- **BR-05** 含在册员工的部门不可删除（先迁移/停用）
- **BR-06** 被员工引用的模型连接不可删除（可停用）
- **BR-07** 提示词版本不可变；编辑即新增版本；激活版本必须存在且哈希校验通过
- **BR-08** 停用员工不进入派工候选
- **BR-09** 有效权限 = 公司策略 ∩ 岗位默认 ∩ 员工覆盖，逐项取更严，任何一层不得扩权
- **BR-10** 审查人 ≠ 执行人；跨模型审查优先
- **BR-11** 密钥只存引用（`env:`/`dpapi:`/`keyring:`），响应/日志/导出包不得出现明文
- **BR-12** Agent 侧不存在任何可修改员工/岗位/权限/模型绑定的接口（物理隔离）

---

## 5. 用户故事与验收

| 编号 | 故事 | 验收要点 |
|---|---|---|
| US-1 | 公司管理（增改查/归档） | 归档后员工不可派单，数据不删 |
| US-2 | 部门树（增删改、拖拽移动） | 拖到自身子部门被拒；含员工不可删；depth 正确 |
| US-3 | 岗位与兼任 | 主岗唯一；兼任不叠加权限；组织图显示主岗 |
| US-4 | 员工 CRUD/启停/软删 | 停用不进候选；删除保留历史 |
| US-5 | 员工-模型解耦 | 切换后 id 不变、历史 model 不变、switch_log 记录；两员工共模型不串账 |
| US-6 | 模型连接（配置/测试/模型列表） | 真实测试返回延迟；密钥不回显；失败分类可读 |
| US-7 | 提示词外置与版本 | 保存生成新版本；旧版本文件哈希不变；回滚=切指针；篡改报错 |
| US-8 | 组织图编辑 | 拖拽即持久化；成环拒绝；50 节点内可读 |
| US-9 | 权限面板 | 有效权限 + 每项来源链可见；放宽被拦截并解释 |
| US-10 | 配置导入导出 | 导出包无密钥；导入有 dry-run；往返结构与哈希一致 |
| US-11 | 派工预览 | 候选来自硬过滤；分数可解释；审查人 ≠ 执行人；决策留痕 |
| US-12 | 审计 | 12 类事件留痕；只增不改 |

---

## 6. 数据模型

### 6.1 新增 10 张表
所有新表带 `id VARCHAR(32) PK`、`owner_id VARCHAR(64) DEFAULT 'local'`、`created_at/updated_at DATETIME(TZ)`（下文不再重复）。SQLite 与 PostgreSQL 双兼容，只用通用类型。

**company**：`name`(唯一,120) `description` `policy JSON`（`{max_risk_level, allowed_providers[], default_budget_usd, require_cross_model_review}`）`status`(active/archived)

**department**：`company_id FK` `parent_id FK 自引用可空` `name` `code` `description` `sort_order` `depth`（写入时计算）
索引：`(company_id,parent_id)`；唯一 `(company_id,name)`

**position**：`company_id` `department_id 可空` `name` `level` `is_managerial BOOL` `responsibilities TEXT` `default_permissions JSON`

**employee**：`company_id` `department_id 可空` `name`(同公司唯一) `avatar` `title` `bio` `personality` `status`(active/disabled/archived) `reports_to FK 自引用` `primary_model_id FK` `fallback_model_id FK 可空` `adapter_type`(api/cli) `cli_profile JSON 可空` `tools_allowed JSON` `permission_profile JSON` `capabilities_declared JSON` `prompt_active_version INT 可空` `deleted_at 可空`
索引：`(company_id,department_id)` `(reports_to)` `(status)`

**employee_position**：`employee_id`+`position_id` 联合 PK，`is_primary BOOL`（同员工仅一条 true）`department_id` `assigned_at`

**model_connection**：`company_id` `name` `provider`(litellm 前缀) `model` `api_key_ref`(只存 `env:VAR`/`dpapi:x`/`keyring:s:u`) `base_url 可空` `timeout_s` `max_retries` `retry_policy JSON` `model_list_source`(static/api) `last_health_check_at` `last_health_status` `enabled`
唯一：`(company_id, provider, model, coalesce(base_url,''))`

**model_switch_log**：`employee_id` `from_model_id 可空` `to_model_id 可空` `slot`(primary/fallback) `actor_type` `actor_id` `reason` `created_at`（只增）

**prompt_revision**：`employee_id` `version INT`（同员工唯一）`file_path`(`data/prompts/employees/<id>/vNNNN.md`) `content_hash`(SHA-256) `note` `created_by` `is_active BOOL`（同员工仅一条 true）

**assignment_decision**：`company_id` `requested_by` `requirement JSON` `candidates JSON`（含每人 score/factors/rejected_reason）`selected_employee_id 可空` `reviewer_employee_id 可空` `algorithm_version VARCHAR(16)`

**audit_log**：`owner_id` `actor_type`(user/agent/system) `actor_id` `action`(如 `employee.model_binding.update`) `target_type` `target_id` `detail JSON`（脱敏）`request_id`（只增，无 update/delete 路由）

### 6.2 对 M0 表的变更（最小侵入）
- `agent_run` 新增 `employee_id VARCHAR(32) NULL` + 索引；保留 `employee_key` 原值；M1 新记录双写；M2 再移除旧列
- 其余 M0 表**不改结构**（`task_event.type` 值域可扩展）
- **不回填历史**：M0 的 `employee_key`（如 `m0-researcher`）不是真实员工，硬造记录会污染数据

### 6.3 迁移方案（Alembic）
- 新增依赖 `alembic`；`alembic.ini` + `migrations/`；`env.py` 必须 `render_as_batch=True`（SQLite 限制）
- 基线：先 autogenerate 再**手工裁剪**为 M0 五表 DDL；已存在的 M0 库执行 `alembic stamp m0_baseline`
- 版本序列：

| revision | 批次 | 内容 |
|---|---|---|
| `m0_baseline` | B1 | M0 五表（stamp 已有库） |
| `m1_b1_agent_run_employee_id` | B1 | agent_run 加列 + 索引 |
| `m1_b2_org` | B2 | company/department/position |
| `m1_b3_employee_model` | B3 | employee/employee_position/model_connection/model_switch_log |
| `m1_b4_prompt` | B4 | prompt_revision |
| `m1_b5_assignment_audit` | B5 | assignment_decision/audit_log |

- 每个 revision 必须有 `downgrade()`；B3 之后的 downgrade 会丢数据，仅限测试库；真实库回滚前先跑 `scripts/backup_db.py`（B1 交付）
- 导入操作单事务，失败整体回滚

---

## 7. API 设计

### 7.1 通用约定
前缀 `/api/v1`（`/api/health` 保留兼容）。分页 `?page=1&page_size=20`（≤200）。写操作带 `expected_updated_at`，不匹配返回 409 `CONFLICT_STALE`。创建接口支持 `Idempotency-Key`。时间为 ISO-8601 带时区。资源不存在与无权限统一 404。每请求生成 `request_id`。

**错误包络**：
```json
{"error":{"code":"BR_DEPARTMENT_HAS_EMPLOYEES","message":"部门下仍有 3 名员工，请先迁移","detail":{"employee_ids":["..."]},"request_id":"req_..."}}
```
**错误码**：`VALIDATION_ERROR`(422)、`BR_DEPARTMENT_CYCLE`(409)、`BR_DEPARTMENT_HAS_EMPLOYEES`(409)、`BR_MODEL_IN_USE`(409)、`BR_EMPLOYEE_NAME_TAKEN`(409)、`BR_PROMPT_HASH_MISMATCH`(409)、`PERMISSION_WIDEN_DENIED`(403)、`CONFLICT_STALE`(409)、`UPSTREAM_AUTH_FAILED`(502)、`UPSTREAM_TIMEOUT`(504)、`PERMISSION_DENIED`(403)

### 7.2 端点清单（38 个）
- **公司 5**：`GET/POST /companies`、`GET/PATCH /companies/{id}`、`POST /companies/{id}/archive`
- **部门 6**：`GET /companies/{cid}/departments`、`GET /companies/{cid}/org-tree`（一次返回部门+岗位+员工树，供 React Flow）、`POST /companies/{cid}/departments`、`PATCH /departments/{id}`、`DELETE /departments/{id}`、`POST /departments/{id}/move`（`{new_parent_id,new_index}`）
- **岗位 5**：`GET/POST /companies/{cid}/positions`、`GET/PATCH/DELETE /positions/{id}`
- **员工 12**：列表/创建（`/companies/{cid}/employees`）、详情/改档案（`/employees/{id}`）、`POST /employees/{id}/enable|disable`、`DELETE /employees/{id}`（软删）、`PUT /employees/{id}/model-binding`、`GET /employees/{id}/effective-permissions`、`PUT /employees/{id}/permission-overrides`、`GET /employees/{id}/capabilities`、`GET /employees/{id}/prompts`、`GET /employees/{id}/audit`
- **提示词 4**：`POST /employees/{id}/prompts`（`{content,note}`）、`GET /prompts/{rev_id}`、`POST /prompts/{rev_id}/activate`、`GET /prompts/{rev_id}/diff?against=prev`
- **模型连接 6**：列表/创建 `GET/POST /companies/{cid}/model-connections`、`PATCH/DELETE /model-connections/{id}`、`POST /model-connections/{id}/test`、`GET /model-connections/{id}/models`
- **派工 2**：`POST /companies/{cid}/assignments/preview`、`GET /assignments/{decision_id}`
- **配置 3**：`GET /companies/{cid}/export`、`POST /config/import?dry_run=true`、`POST /config/import`
- **审计 1**：`GET /audit?actor_type=&action=&from=&to=`

### 7.3 关键示例

**创建员工**
```http
POST /api/v1/companies/cmp_01/employees
{"name":"林知远","title":"首席分析官","department_id":"dep_research",
 "primary_model_id":"mc_deepseek","fallback_model_id":"mc_ds_reasoner",
 "personality":"严谨、先结论后依据、不臆测","bio":"负责行业与竞品分析",
 "position_ids":["pos_analyst"],"reports_to":"emp_ceo",
 "tools_allowed":["web.search","file.read"],
 "permission_profile":{"workspace_scope":"project_only","file_ops":["read"],"network":"allowlist"},
 "initial_prompt":"# 角色\n你是首席分析官……"}
→ 201 {"id":"emp_01","prompt_active_version":1}
```
服务端事务：校验 BR-01/07/09 → 写 employee → 写 employee_position → 生成 `v0001.md` + prompt_revision → 写 audit_log。

**切换模型**
```http
PUT /api/v1/employees/emp_01/model-binding
{"primary_model_id":"mc_claude","fallback_model_id":"mc_deepseek","reason":"跨模型交叉审查需要"}
→ 200 {"employee_id":"emp_01","primary_model_id":"mc_claude","history_preserved":true,
        "warnings":["新模型不支持 structured_output，相关任务将无法派发"]}
```

**派工预览**
```http
POST /api/v1/companies/cmp_01/assignments/preview
{"capabilities":["coding.python","test.unit"],"tools":["file.write"],"risk_level":"medium","budget_usd":0.5}
→ 200 {"decision_id":"asg_01",
  "candidates":[{"employee_id":"emp_dev","score":0.82,
    "factors":{"position_match":1.0,"review_chain_distance":0.9,"performance":0.7,"cost":0.6,"load":0.9}}],
  "excluded":[{"employee_id":"emp_ceo","reason":"capability_missing:tool.file.write"}],
  "reviewer":{"employee_id":"emp_qa","cross_model":true,"reason":"汇报链最近上级；跨供应商"}}
```

**连接测试**
```http
POST /api/v1/model-connections/mc_01/test
→ 200 {"ok":true,"latency_ms":812,"model":"deepseek/deepseek-chat"}
→ 502 {"error":{"code":"UPSTREAM_AUTH_FAILED","message":"认证失败（401），请检查 DEEPSEEK_API_KEY"}}
```
实现复用 M0 的 `LiteLLMAdapter.health_check()`；日志只记 code + latency。

### 7.4 代码落点（防止 main.py 再膨胀）
```
apps/api/main.py        app 装配/CORS/lifespan/异常处理器
apps/api/deps.py        get_db / get_actor / 分页
apps/api/errors.py      错误码 + 异常基类 + handler
apps/api/routers/       companies departments positions employees prompts model_connections assignments config_io audit
apps/api/schemas/       Pydantic v2 请求/响应（与领域模型分离）
packages/organization/  领域服务：companies/departments/positions/employees/assignment
packages/permissions/   effective.py(三层交集) policy.py(审批策略) audit.py
packages/model_gateway/ credentials.py(引用解析+脱敏) catalog.py(provider/模型目录)
packages/agent_core/    capabilities.py(能力三层交集)
```
规则：router 只做参数校验与调服务，业务规则不写在 router。

---

## 8. 前端设计

技术栈沿用：React 18 + TS + Vite + Tailwind v4 + zustand + react-router-dom。**M1 新增 3 个依赖（待确认 D-1）**：shadcn/ui、@tanstack/react-query、@xyflow/react。

### 8.1 路由与页面
```
/                        → /org
/org                     组织架构（React Flow 画布 + 部门树）
/employees               员工列表
/employees/new           建员工向导（3 步）
/employees/:id           员工详情（5 Tab）
/settings/organization   公司/部门/岗位设置
/settings/models         模型连接管理
/settings/import-export  导入导出
/settings/audit          审计日志
/assignments/preview     派工预览台
```

### 8.2 页面要点
**P1 组织图**：节点类型 = 公司/部门/员工；实线=汇报，虚线=兼任；拖员工到部门=调动，拖到另一员工=改汇报；拖拽结束才请求（乐观更新 + 失败回滚 + Toast）；禁用员工降透明度且不能作为汇报对象；提供"列表视图"替代（键盘可达）。右键菜单：新建子部门/新建员工/删除。

**P2 员工列表**：列 = 姓名/岗位/部门/主模型/状态/最近变更；过滤 = 状态/部门/关键词；行内启停（二次确认）；模型连接不健康时顶部黄条警示。

**P3 建员工向导**：① 身份（姓名/头像/岗位多选含主岗/部门/汇报对象/简介/性格）② 模型与工具（主模型下拉带健康点、备用、工具白名单）③ 提示词与权限（4 套模板骨架：分析师/开发/测试/主管；权限档只能选 ≤ 公司策略上限）。右侧常驻"将创建内容"摘要。

**P4 员工详情 5 Tab**：
1. 档案（含危险区：停用/删除，删除需输入姓名）
2. 模型（主备卡片 + 切换抽屉显示能力差异 warning + 切换历史）
3. 提示词（左版本列表带 active 标记，右 Markdown 编辑器；保存为新版本/与上一版对比/激活此版本；显示哈希短码）
4. 权限（三层来源可视化，见 §8.3）
5. 能力与记录（8 项能力矩阵含来源标注 + 最近 20 条审计）

**P5 模型连接**：卡片网格显示健康点/最近测试/引用员工数；测试按钮转 loading；新建时密钥字段默认提示填 `env:XXX_API_KEY`，明确"不要粘贴密钥本体"。

**P6 导入导出**：导出预览实体数量；导入先 dry-run（新建/覆盖/跳过逐项可勾选），冲突策略三选一（改名/跳过/合并）。

**P7 派工预览台**：能力/工具/风险/预算表单 → 候选人卡片（分数条 + 5 因子小条形 + 警告）、被排除折叠区（原因）、审查人卡片（cross_model 标记）、底部注明"M2 才会真正派发"。

### 8.3 权限面板展示结构（前端只展示服务端计算结果）
```
公司策略上限：workspace=project_only, file_ops=[read,write], network=allowlist
岗位默认（技术审查官）：file_ops=[read], network=deny
员工覆盖：file_ops=[read]
─────────────────────────
有效权限：file_ops=[read]  ← 标出来源链
```
比岗位默认更宽的选项置灰，hover 解释"公司策略/岗位默认不允许放宽"。

### 8.4 状态与组件
- 服务端状态：TanStack Query，queryKey 规范 `['org-tree',companyId]`、`['employee',id]`、`['models',companyId]`；写后 invalidate 相关 key
- UI 状态：zustand（当前公司、侧栏、组织图视图设置）
- 表单：react-hook-form + zod 客户端预校验，服务端仍是唯一权威
- 错误：统一 `ApiError` → Toast + 字段级错误映射；409 业务错误展示在相关控件下
- 组件目录：`components/ui`（shadcn）、`org/OrgCanvas`、`org/DepartmentTree`、`employee/EmployeeForm|ModelBindingDrawer|PermissionMatrix`、`prompt/PromptEditor|VersionList|DiffView`、`model/ConnectionCard|ConnectionForm|HealthDot`、`common/DangerConfirm|EmptyState|ErrorBoundary`
- 测试边界：纯函数（组织树组装、权限来源合并、分数归一化）用 vitest；交互用手工验收清单（Playwright 属重型依赖，未获批准不引入）

---

## 9. 员工-模型解耦（核心机制）

### 9.1 三层分离
```
员工身份层 employee          模型连接层 model_connection        执行层 adapter
id/姓名/岗位/权限/提示词  →   provider+model+凭据引用      →   LiteLLMAdapter / CLIAdapter
能力声明                      健康状态/超时重试/费用            实际调用与事件流
```
铁律：employee 只存 `primary_model_id`/`fallback_model_id` 两个引用，**不存 provider、不存 model 名、不存密钥**；`agent_run` 记录本次真实使用的 model 快照，历史不可被后续切换改写；所有"按模型统计"都必须能回退到"按员工统计"。

### 9.2 运行时解析链
```python
def resolve_model(employee, company):
    primary = get_connection(employee.primary_model_id)
    if primary and primary.enabled and health_ok(primary):        # 健康检查 TTL 5 分钟
        return ResolvedModel(primary, role="primary")
    if employee.fallback_model_id:
        fb = get_connection(employee.fallback_model_id)
        if fb and fb.enabled and health_ok(fb):
            return ResolvedModel(fb, role="fallback", warning="主模型不可用，已降级到备用模型")
    raise NoAvailableModel(employee_id=employee.id)   # 拒绝派单，绝不静默借用他人模型
```
**刻意不做全公司模型池自动兜底**：否则"谁在干活、用什么模型、花谁的钱"不可解释，破坏成本绩效中心的设计目标。

### 9.3 切换模型流程
`PUT /employees/{id}/model-binding` → 校验连接同公司/启用/引用可解析（不实际调用）→ 能力差异检测（新模型 ∩ 员工已声明能力，缺口则 200 + warnings）→ 事务内更新 employee + 写 model_switch_log + audit_log → 前端刷新（档案不变、历史 run 带旧模型名、新 run 用新模型）。

### 9.4 能力三层（不混淆）
有效能力 = **Adapter 能力 ∩ 模型能力（catalog 元数据）∩ 授权能力（tools_allowed + 权限档案）**。任一层缺失即不可派单，派工预览必须给出具体缺失项（如 `capability_missing:tool.file.write`），不能只说"不匹配"。

### 9.5 解耦测试用例（B3 必须落地）
| 编号 | 场景 | 期望 |
|---|---|---|
| A3-1 | 员工 A、B 共用连接 M | 各自 agent_run 的 model 相同但归属正确，usage 不串账 |
| A3-2 | A 从 M1 切到 M2 | A.id 不变；历史 run 仍 M1；新 run M2；switch_log +1 |
| A3-3 | 切到能力更弱的模型 | 返回 warnings，且不再出现在需要该能力的候选中 |
| A3-4 | 切到已停用连接 | 422 |
| A3-5 | 删除被引用连接 | 409 `BR_MODEL_IN_USE`（提示引用数） |

---

## 10. 组织如何驱动任务分配（M1 只交付"预览"，M2 接执行）

### 10.1 总体思路：约束式派工
```
任务需求 ──硬过滤──▶ 候选集 ──打分排序──▶ 排序结果 ──CEO 只能在候选集内选──▶ 决策落库
              （代码执行，不可协商）              （可解释）                 （越界即拒绝）
```
原因：让 LLM 在全体员工里自由点将会导致越权、自审、用贵模型干便宜活。组织数据的作用是把 LLM 的选择空间压到合法且合理范围。

### 10.2 AssignmentRequest
```python
@dataclass
class AssignmentRequest:
    required_capabilities: list[str]   # ["coding.python","test.unit"]
    required_tools: list[str]          # ["file.write"]
    risk_level: str                    # low|medium|high|critical
    budget_usd: float | None
    prefer_department_id: str | None   # 项目归属部门（偏好非硬约束）
    exclude_employee_ids: list[str]    # 例如已失败的执行人（M3 返工）
    notes: str = ""
```

### 10.3 硬过滤 8 条（顺序执行，淘汰必记原因）
| # | 规则 | 原因码 |
|---|---|---|
| 1 | 员工 active 且同公司 | `inactive` |
| 2 | 有可用模型（resolve_model 成功） | `no_model` |
| 3 | 有效能力覆盖 required_capabilities | `capability_missing:<cap>` |
| 4 | 授权工具覆盖 required_tools | `tool_denied:<tool>` |
| 5 | max_risk_level ≥ 任务风险 | `risk_exceeded` |
| 6 | 预估成本 ≤ budget | `over_budget` |
| 7 | 不在 exclude 列表 | `excluded_by_request` |
| 8 | 部门未归档 | `department_archived` |

### 10.4 打分公式（algorithm_version = m1.0）
```
score = 0.30*position_match + 0.20*review_chain_distance + 0.20*performance
      + 0.15*cost_efficiency + 0.15*load
```
- `performance` 在 M1 无数据时取中性 0.5 并标注 `data_insufficient`（**不假装有绩效数据**，M3 接真实指标）
- `load` M1 恒 0.5，M2 接真实在跑任务数
- 权重常量带 `algorithm_version`，改权重必须升版本，历史决策可追溯
- 每个因子输出 0~1 原始分与权重贡献，前端直接画条形图

### 10.5 审查链推导（伪代码）
```python
def derive_reviewer(doer, request, company):
    for candidate in walk_reports_to_up(doer, company, max_depth=5):
        if candidate.id == doer.id or candidate.status != "active": continue
        if not capability_covers(candidate, request.required_capabilities): continue
        return ReviewerDecision(candidate, cross_model=provider_of(candidate) != provider_of(doer),
                                reason=f"汇报链第 {n} 层上级；跨模型/同模型")
    pool = [e for e in active_employees(company)
            if e.department_id != doer.department_id
            and capability_covers(e, request.required_capabilities)]
    pool.sort(key=lambda e: (provider_of(e) == provider_of(doer), e.id))  # 跨模型优先
    if pool: return ReviewerDecision(pool[0], cross_model=..., reason="独立审查池（跨部门）")
    return ReviewerDecision(None, reason="无可用审查人：需用户指定或放宽能力要求")
```
约束：reviewer ≠ doer（BR-10）；同部门"开发-测试"配对允许但跨模型优先；审查人只是"建议"，最终任命权在用户。

### 10.6 管理者与审批边界
| 角色 | 能做 | 绝对不能做 |
|---|---|---|
| 执行员工 | 提交结果、发起审批请求 | 批准自己的请求、改自己权限 |
| 管理者员工（is_managerial） | 建议通过/打回、升级给用户 | 代替用户批准（系统层无此 API） |
| 用户 | 批准/拒绝/改派/改权限 | —（唯一授权源） |

`reports_to` 在审批中只决定"谁的建议先展示"，不产生自动批准能力。

### 10.7 M2 衔接方式
M2 的 task-engine 派工时调用同一个 `assignment.preview()` 拿候选集，把候选清单（含理由）注入 CEO Agent 的 prompt；CEO 选择若不在候选集内 → 拒绝并重新规划。这样"组织影响分配"在 M2 自然成立，无需重写。

### 10.8 派工算法验收
| 编号 | 给定 | 期望 |
|---|---|---|
| B8-1 | dev1（模型A）+ qa1（模型B，汇报给 dev1） | 候选含两者；审查人 ≠ 执行人 |
| B8-2 | dev1 权限 file_ops=[read] | 被 `tool_denied` 排除且理由明确 |
| B8-3 | 只有 dev1 | 审查人为空 + 原因，不硬凑 |
| B8-4 | dev1(A)、dev2(B) 同岗 | 跨模型审查优先 |
| B8-5 | 任务 critical，公司策略 max=high | 全员 `risk_exceeded`，提示"需提升策略或用户直接指派" |

---

## 11. 安全与权限

### 11.1 主体边界
| 主体 | 凭证 | 可调用 | 禁止 |
|---|---|---|---|
| 用户 | 本地单用户无登录（M5 加账号） | 全部 `/api/v1` | — |
| 系统 | 进程内标记 | 迁移、健康检查、审计写入 | 改员工权限 |
| Agent | **M1 不发放任何管理凭证** | 无 | 全部管理接口（BR-12） |

关键：不是"调用时检查权限"，而是**物理上不存在 Agent 可调用的管理端点**。M2 引入工具调用时，Agent 只能访问 `/agent-api/*`（只读上下文 + 提交结果 + 发起审批请求），路由层用独立 `ActorContext(type="agent")` 依赖。

### 11.2 三层权限交集
```
公司策略上限 ∩ 岗位默认（同员工多岗取并集，再与上层交集） ∩ 员工覆盖（只允许更严）= 有效权限
```
逐项规则：`workspace_scope`(none < project_only < company_readonly < company_write)、`file_ops`(⊂{read,write,delete})、`shell`(deny < approval_required < allow_sandbox)、`network`(deny < allowlist < allow_all)、`max_risk_level`(low<medium<high<critical)、`tools`(交集)、`budget_usd_per_task`(更小)、`requires_approval`(**并集**，越多越严)。

返回结构必须带来源链，前端直接消费：
```python
merge_strictest(...) -> {item: {"value": v, "source": "company|position|employee", "chain": [...]}}
```
测试 ≥12 组，必须包含"员工试图放宽被拒"（`PERMISSION_WIDEN_DENIED`）、"多岗并集再与公司交集"、"空集合语义=不允许而非不限制"。

### 11.3 密钥管理
存储只接受 `env:<VAR>`/`dpapi:<blob>`/`keyring:<service>:<user>`，正则拒绝 `sk-` 开头疑似明文（422）；运行时由 `credentials.py` 解析，随用随取；响应只返回 ref 与 `has_credential`；日志统一脱敏（`sk-[A-Za-z0-9]{8,}`、`Bearer\s+\S+`、`api[_-]?key\s*[:=]\s*\S+`）；导出包只含 ref；连接测试只返回 ok/latency/error_code。

### 11.4 审批策略表（M1 建表，M2 执行）
| action_type | 默认风险 | 决策 |
|---|---|---|
| file_read（工作区内） | low | allow |
| file_write（工作区内） | medium | approval（可在员工档案放宽，但不得超公司策略） |
| file_delete | high | approval（不可放宽） |
| shell_exec | high | approval（黑名单直接 deny） |
| network_upload | high | approval |
| system_config / software_install / service_deploy / code_publish | critical | approval + 二次确认 |

硬 deny 常量（测试覆盖）：`Set-MpPreference`、`netsh advfirewall`、`Add-MpPreference -ExclusionPath`、`setx` 改系统变量、注册表 `HKLM\...\Environment` 写入、`bcdedit`、`vssadmin delete`。

### 11.5 审计事件（12 类）
company.create/update/archive｜department.create/update/move/delete｜position.create/update/delete｜employee.create/update/enable/disable/delete｜employee.model_binding.update｜employee.permission_overrides.update｜prompt.publish/activate｜model_connection.create/update/delete/test｜config.export/import｜assignment.preview。
只增不改：无 UPDATE/DELETE 路由；ORM 事件监听阻止 update。

### 11.6 越权测试（10 项，必须全绿）
S-1 放宽权限 → 403 + 审计｜S-2 员工访问管理接口 → 接口不存在｜S-3 `api_key_ref` 填明文 → 422｜S-4 连接失败响应/日志无密钥片段（正则断言）｜S-5 导出包 grep 不到 `sk-`/`Bearer`｜S-6 部门成环 → 409 且库无变化｜S-7 删非空部门 → 409 员工不变｜S-8 并发改同一员工 → 409 `CONFLICT_STALE`｜S-9 恶意 zip 路径穿越 → 拒绝｜S-10 提示词被篡改 → `BR_PROMPT_HASH_MISMATCH`

### 11.7 已知限制（诚实声明）
本地单用户无认证（只监听 127.0.0.1 缓解，账号体系 M5）；`env:` 依赖用户正确设置环境变量；权限是能力/范围级非行级 ACL（工作空间细粒度在 M2）；审计防篡改靠应用层（本地 SQLite 用户可直接改）。

---

## 12. 分批开发计划

每批结束必须：`ruff` 全绿 → `pytest` 全绿 → `npm run build` 通过 → 更新 CHANGELOG → 提交一次可回滚 commit。每批 3–6 个 commit。

### B1 地基（不写新功能，先还债）
**范围**：① Alembic（`alembic.ini` + `migrations/` + `m0_baseline` + batch 模式）② `pyproject.toml` 加 `[build-system]`，`pip install -e .` 可用 ③ API 拆 `routers/`+`deps.py`+`errors.py`，`on_event`→`lifespan`，统一错误包络 ④ `tests/conftest.py`（tmp_engine/client/actor/seeded_company）⑤ `scripts/backup_db.py` ⑥ 前端装 shadcn/ui 基础组件 + TanStack Query + react-hook-form + zod，建 `api/client.ts` ⑦ CI 加迁移双路径测试。

**验收**：空库 `alembic upgrade head` 成功；M0 库 `stamp m0_baseline && upgrade head` 后 schema 与新库一致；`pytest` 7 个旧测试全过 + 迁移测试过；`/api/health`、`/api/tasks` 行为与 M0 一致；`npm run build` 通过。
**风险**：autogenerate 对 SQLite 噪音大 → 手工裁剪基线 + schema diff 脚本。

### B2 组织域
**范围**：迁移 `m1_b2_org`；`packages/organization/`（companies/departments/positions/tree）；规则 BR-02/03/04/05；API 公司 5 + 部门 6（含 org-tree）+ 岗位 5；前端组织设置页 + 组织图只读。
**验收**：3 层部门 + 2 岗位 org-tree 结构/depth 正确；成环 409 库无变化；第 9 层被拒；删非空部门 409 提示人数；重名 409；30 节点渲染无报错；新增 ≥10 个集成测试（每条规则 1 正 1 反）。

### B3 员工域 + 模型连接（解耦核心）
**范围**：迁移 `m1_b3_employee_model`（含 `agent_run.employee_id`）；`employees.py`/`model_connections.py`/`capabilities.py`；`credentials.py` + `catalog.py`；API 员工 12 + 连接 6（含真实测试）；前端员工列表/向导/详情（档案+模型）/模型连接页。
**验收**：向导落库 + 审计；A3-1..A3-5 全过；真实 DeepSeek 连接测试返回 latency；响应/日志 grep 无 `sk-`；新建 2 员工并切换模型刷新后一致；新增 ≥18 个测试（含 5 个解耦用例、1 个 live 标记）。
**风险**：真实测试耗 token → `max_tokens=8` + `@pytest.mark.live` 默认跳过。

### B4 提示词外置 + 导入导出
**范围**：迁移 `m1_b4_prompt`；文件存储 `data/prompts/employees/<id>/vNNNN.md`（YAML frontmatter：role/goal/rules/tools_policy）+ SHA-256；`prompts.py` 服务（create/activate/diff/load）；`load_active_prompt()` 供 M2 复用；`config_io.py`（zip 含 manifest/company/org/employees/prompts，dry-run，事务，路径穿越防护）；API 提示词 4 + 配置 3；前端编辑器 + 导入导出向导。
**验收**：连续保存 3 次 = 3 个文件且 v1 哈希不变；激活后指针正确、旧文件仍在；手工改文件 → 哈希报错；导出 zip 无密钥；dry-run 计数正确不写库；往返导入导出结构与哈希 100% 一致；路径穿越被拒；新增 ≥14 测试。

### B5 权限 + 派工预览 + 审计 + 组织图编辑
**范围**：迁移 `m1_b5_assignment_audit`；`packages/permissions/`（effective/policy/audit）；`organization/assignment.py`（硬过滤 8 + 5 因子 + 审查链 + algorithm_version）；API effective-permissions/permission-overrides/capabilities/assignments/preview/audit；前端权限 Tab、派工台、组织图可编辑、审计页。
**验收**：三层交集 12 组全绿；B8-1..B8-5 场景全过；每次 preview 落 assignment_decision 含 factors 与版本；`PERMISSION_WIDEN_DENIED` + 审计；12 类事件各触发一次且无更新接口；拖拽 10 次无错乱；新增 ≥20 测试。

### B6 端到端验收
**三个场景必须全过**：
1. **从零建公司**：公司→2 部门→3 岗位→2 连接→3 员工（含兼任）→组织图正确→导出→导入新库→结构一致
2. **解耦验证**：A 切换模型→历史保留→同连接员工 B 不串账→派工预览中 A 的能力缺口被正确排除
3. **权限与派工**：限制某员工 file.write→派"需写文件"任务→被硬过滤→审查人推导正确且跨模型优先

**交付**：`docs/testing/M1_TEST_REPORT.md`（真实命令 + 输出摘要 + 失败项 + 未测项）、`M1_FINAL_HANDOFF.md`（对齐 M0 的 14 项格式，单文档）、更新 README/FEATURE_MATRIX/ROADMAP、`M1` tag、`scripts/demo_m1_*.py`。
**门槛**：全量 pytest ≥50 通过（含 M0 的 7 个）；ruff 全绿；前端构建通过；三场景真实跑通有日志；无 P0/P1 缺陷。

---

## 13. M0 遗留问题处理安排

| 遗留项 | 现状 | M1 处理 | 批次 |
|---|---|---|---|
| Codex CLI headless (V7) | ⛔ 被阻塞 | **不安装**；接口不变；允许录入 CLI 员工（`cli_profile`）但执行留 M2，UI 标注"未验证" | — |
| 第二供应商 (V2) | ⏭️ SKIP | 不要求提供 Key；catalog/连接测试支持多 provider，用户自加即生效；测试用 mock | B3 |
| CrewAI 对照 (V8) | ⏭️ SKIP | **不安装**；ADR-0001 标注"缺对照数据" | — |
| LiteLLM fallbacks 故障注入 | 未测 | 增加 mock 单测（主模型抛错 → 断言走 fallback 分支），不烧钱 | B3 |
| Windows Job Object 终止 | 未验证 | 顺延 M2（CLI 真正落地时） | — |
| 浏览器端联调 | 未做 | B3 起每批前端验收都要求真起双端手工走查 | B3–B6 |
| main.py 单文件 / on_event 弃用 | 技术债 | B1 重构 | B1 |
| sys.path.insert | 技术债 | B1 改可安装包 | B1 |
| 无迁移工具 | 技术债 | B1 引入 Alembic | B1 |
| agent_run.employee_key 字符串 | 临时设计 | B3 加 employee_id 双写；M2 切换 | B3 |
| 无分页/统一错误 | 技术债 | B1 统一 | B1 |
| 前端仅 1 页 | 骨架 | B2–B5 按页面清单落地 | B2–B5 |

---

## 14. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Alembic 基线噪音大 | B1 超时 | 手工裁剪基线 + schema diff 校验 |
| React Flow 50+ 节点卡顿 | 体验 | 关动画、按部门折叠、列表视图兜底 |
| 三层权限语义歧义 | 安全 | 先写 12 组表格驱动测试，按测试实现 |
| 派工打分主观 | 争议 | 权重常量 + 版本号 + 因子可见；M1 只预览不派发 |
| 导入导出一致性 | 数据损坏 | 单事务 + dry-run + 往返测试 |
| 真实连接测试费用 | 成本 | `max_tokens=8` + live 标记默认跳过 |

---

## 15. 待确认决策（6 个，含建议默认值）

| # | 决策 | 建议 |
|---|---|---|
| D-1 | 引入 shadcn/ui + TanStack Query + React Flow | **引入**（React Flow 本就属指定技术栈） |
| D-2 | 员工姓名同公司唯一 | **唯一**（避免派工歧义） |
| D-3 | 打分权重 0.30/0.20/0.20/0.15/0.15 | **接受**，后续调整须升 algorithm_version |
| D-4 | 员工软删除 | **软删除**（硬删破坏审计） |
| D-5 | 提示词允许 UI 改历史版本 | **不允许**（只新增/回滚） |
| D-6 | 导入冲突默认策略 | **rename（改名保留两者）**，不默认覆盖 |

---

## 16. 下一步（给接手者）

1. 向所有者确认 D-1..D-6；未回复则按建议默认值执行并在首个 commit message 中声明。
2. 执行 **B1**，顺序：
   a. 读 `apps/api/main.py`、`packages/persistence/{db,models}.py`、`tests/*`（现有 7 测试）
   b. 加 alembic 依赖 + 初始化 + `m0_baseline`（stamp 现有 `data/agentos.db`）
   c. 补 `pyproject.toml` 打包配置，`pip install -e .` 后删除对 `sys.path.insert` 的依赖（保留兜底并标注）
   d. 拆 routers/deps/errors，改 lifespan，统一错误包络与分页
   e. 建 `tests/conftest.py` 夹具；跑 `pytest`、`ruff`、`npm run build`
   f. 提交 `refactor(b1): 基础设施与迁移`，并在 CHANGELOG 记录
3. **B1 验收通过后再开 B2**，不得并行开工。
4. 每批结束把真实结果（命令 + 关键数字）追加到本文件末尾的"执行记录"区（保持单文档习惯）。

---

## 附录：M1 执行记录（由后续执行者追加，勿删）

| 批次 | 日期 | 结果 | 证据 |
|---|---|---|---|
| — | — | 计划待确认 | 本文件 |
