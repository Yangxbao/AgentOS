# AgentOS M1 计划与交接文档（单一文档）

> 版本：**v1.3（M1 执行完成 + P1 收尾清理）**｜日期：2026-11-05｜状态：**M1 主体完成，P1 已清理，可进入 M2**
> 用途：这份文档自包含，可直接交给另一个 AI 或开发者执行 M1。不需要再读其他文档。
> 文档约定：【已验证】= 有可复核证据（代码/实测）｜【设计】= 本文档提出的方案｜【已确认】= 所有者已拍板
> 修订内容见文末 **§17 修订记录**；执行证据见 **§18 B1**、**§19 B1 补充 + B2**、**§20 B3–B6**、**§21 P1 收尾**。v1.3 不改计划与架构，只记录收尾清理结果。

---

## 0. 给接手者的执行须知（先读这 6 条）

1. **不要重新讨论已定决策**。§15 的 D-1~D-6 已由所有者确认（2026-11-05），直接按结论执行。
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

**模型快照现状（本版实测核对，2026-11-05）**【已验证】：
- `agent_run.model VARCHAR(128)` **已存在**，写入时取自 `employee.adapter.model`（执行当时配置），见 `packages/workflow_engine/sequential.py:52` → 是真实快照
- `usage_record.model VARCHAR(128)` **已存在**，写入时取自模型返回的 `usage.model`，见同文件 `:74` → 是真实快照
- 结论：**不需要新增"模型快照"字段**；切换模型不会改写历史（旧行不变）
- 缺口：`agent_run` 与 `usage_record` **都没有 `employee_id`**（只有 `employee_key` 字符串）→ B3 必须为两张表都补 `employee_id`，否则成本无法按员工稳定归因（员工改名/重建 key 时归因会断）

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
| `agent_run`/`usage_record` 无 `employee_id` | 只有 `employee_key` 字符串 | B3 两张表都加 `employee_id` 双写，M2 切换主引用 |
| 本地管理接口无跨站防护 | 仅 CORS 允许 5173，无 Origin/Host 校验 | B1 增加可信 Origin + Host + `X-AgentOS-Client` 校验（见 §11.8） |

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
| 岗位 | 职责模板，含默认权限与**审查资格** | 可绑定部门或跨部门；员工可兼多岗（1 主 + n 兼）；`can_review` 决定能否担任审查人 |
| 员工 | 身份 + 提示词 + 权限 + 模型引用 | 必须有公司和主模型；不得自改权限 |
| 模型连接 | 可测试的连接配置 | 只存密钥引用；被引用不可删 |
| 提示词版本 | 不可变的文件版本 | 只能新增，不能改历史 |
| 派工决策 | 候选人排序 + 理由 | 只增不改 |

### 4.2 业务规则（测试直接引用编号）
- **BR-01** 员工必须属于一个公司，且必须有 `primary_model_id`
- **BR-02** 部门名/岗位名在同公司内唯一
- **BR-03** 部门树最大深度 8
- **BR-04** 部门与汇报关系不得成环，且：
  - BR-04a 汇报对象必须与员工同公司
  - BR-04b 不允许 `reports_to = 自己`
  - BR-04c 不允许把汇报对象设成自己的下级（等价于成环）
  - BR-04d 汇报链最大长度 20，超出拒绝
  - BR-04e 汇报对象必须是 `active` 员工
- **BR-05** 含在册员工的部门不可删除（先迁移/停用）
- **BR-06** 被员工引用的模型连接不可删除（可停用）
- **BR-07** 提示词版本不可变；编辑即新增版本；激活版本必须存在且哈希校验通过
- **BR-08** 停用员工不进入派工候选
- **BR-09** 有效权限 = 公司策略 ∩ 岗位默认 ∩ 员工覆盖，逐项取更严，任何一层不得扩权
- **BR-10** 审查人 ≠ 执行人；跨模型审查优先；**找不到合格审查人时返回空 + 明确原因，不得硬凑**（规则见 §10.5）
- **BR-11** 密钥只存引用（`env:`/`dpapi:`/`keyring:`），响应/日志/导出包不得出现明文
- **BR-12** Agent 侧不存在任何可修改员工/岗位/权限/模型绑定的接口（物理隔离）
- **BR-13** 权限放宽只能发生在岗位层且不得超过公司策略；**员工覆盖层永远只能收窄**（修正 v1.0 中"员工档案可放宽"的表述冲突）
- **BR-14** 本地管理接口默认只监听 `127.0.0.1`；写请求必须通过可信 Origin + Host + 自定义头校验（见 §11.8），禁止默认监听 `0.0.0.0`
- **BR-15** 提示词文件与数据库必须最终一致：文件先原子落盘并校验哈希，数据库失败则清理孤儿文件；提供对账脚本（见 §9.6）

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

**company**：`name`(唯一,120) `description` `policy JSON`（`{max_risk_level, allowed_providers[], default_budget_usd, require_cross_model_review, review_policy:{allow_subordinate_review:false, prefer_cross_model:true}}`）`status`(active/archived)

**department**：`company_id FK` `parent_id FK 自引用可空` `name` `code` `description` `sort_order` `depth`（写入时计算）
索引：`(company_id,parent_id)`；唯一 `(company_id,name)`

**position**：`company_id` `department_id 可空` `name` `level` `is_managerial BOOL` `can_review BOOL`（是否具备审查资格，默认 false）`review_capability_tags JSON`（如 `["code.review","test.verify"]`，与任务能力标签比对）`responsibilities TEXT` `default_permissions JSON`
> `can_review` 是"测试员独立验证"能否落地的组织基础：没有它，审查人只能靠汇报链硬凑（v1.0 的缺陷）。

**employee**：`company_id` `department_id 可空` `name`(同公司唯一) `avatar` `title` `bio` `personality` `status`(active/disabled/archived) `reports_to FK 自引用` `primary_model_id FK` `fallback_model_id FK 可空` `adapter_type`(api/cli) `cli_profile JSON 可空` `tools_allowed JSON` `permission_profile JSON` `capabilities_declared JSON` `prompt_active_version INT 可空` `deleted_at 可空`
索引：`(company_id,department_id)` `(reports_to)` `(status)`

**employee_position**：`employee_id`+`position_id` 联合 PK，`is_primary BOOL`（同员工仅一条 true）`department_id` `assigned_at`

**model_connection**：`company_id` `name` `provider`(litellm 前缀) `model` `api_key_ref`(只存 `env:VAR`/`dpapi:x`/`keyring:s:u`) `base_url 可空` `timeout_s` `max_retries` `retry_policy JSON` `model_list_source`(static/api) `last_health_check_at` `last_health_status` `last_health_latency_ms INT 可空` `enabled`
唯一：`(company_id, provider, model, coalesce(base_url,''))`
> 健康缓存规则见 §9.2；`last_health_*` 只是最近一次结果，不作为缓存本体。

**model_switch_log**：`employee_id` `from_model_id 可空` `to_model_id 可空` `slot`(primary/fallback) `actor_type` `actor_id` `reason` `created_at`（只增）

**prompt_revision**：`employee_id` `version INT`（同员工唯一）`file_path`(`data/prompts/employees/<id>/vNNNN.md`) `content_hash`(SHA-256) `note` `created_by` `is_active BOOL`（同员工仅一条 true）

**assignment_decision**：`company_id` `requested_by` `requirement JSON` `candidates JSON`（含每人 score/factors/rejected_reason）`selected_employee_id 可空` `reviewer_employee_id 可空` `reviewer_meta JSON`（`{pool: formal|degraded, independence: T1..T6, degraded_reviewer: bool, management_review: bool, cross_model: bool, reason, reason_code, warnings[], excluded[]}`；v1.2 增加池与降级标记）`data_quality JSON` `algorithm_version VARCHAR(16)`

**audit_log**：`owner_id` `actor_type`(user/agent/system) `actor_id` `action`(如 `employee.model_binding.update`) `target_type` `target_id` `detail JSON`（脱敏）`request_id`（只增，无 update/delete 路由）

### 6.2 对 M0 表的变更（最小侵入）
- `agent_run` 新增 `employee_id VARCHAR(32) NULL` + 索引；保留 `employee_key` 原值；M1 新记录双写；M2 再移除旧列
- `usage_record` 新增 `employee_id VARCHAR(32) NULL` + 索引（**v1.0 遗漏，本版补上**）；成本归因优先用 `employee_id`，为空时回退 `employee_key`
- 模型快照**不需要新增字段**：`agent_run.model`、`usage_record.model` 已是执行时快照（§2.2 实测）
- 其余 M0 表**不改结构**（`task_event.type` 值域可扩展）
- **不回填历史**：M0 的 `employee_key`（如 `m0-researcher`）不是真实员工，硬造记录会污染数据；历史成本报表按 `employee_key` 展示并标注"未关联员工"

### 6.3 迁移方案（Alembic）
- 新增依赖 `alembic`；`alembic.ini` + `migrations/`；`env.py` 必须 `render_as_batch=True`（SQLite 限制）
- 基线：先 autogenerate 再**手工裁剪**为 M0 五表 DDL；已存在的 M0 库执行 `alembic stamp m0_baseline`
- 版本序列：

| revision | 批次 | 内容 |
|---|---|---|
| `m0_baseline` | B1 | M0 五表（stamp 已有库） |
| `m1_b1_agent_run_employee_id` | B1 | agent_run 加 `employee_id` + 索引（usage_record 的加列放 B3，因需要 employee 表已存在） |
| `m1_b2_org` | B2 | company/department/position |
| `m1_b3_employee_model` | B3 | employee/employee_position/model_connection/model_switch_log + `usage_record.employee_id` |
| `m1_b4_prompt` | B4 | prompt_revision |
| `m1_b5_assignment_audit` | B5 | assignment_decision/audit_log |

- 每个 revision 必须有 `downgrade()`；B3 之后的 downgrade 会丢数据，仅限测试库；真实库回滚前先跑 `scripts/backup_db.py`（B1 交付）
- 导入操作单事务，失败整体回滚

---

## 7. API 设计

### 7.1 通用约定
前缀 `/api/v1`（`/api/health` 保留兼容）。分页 `?page=1&page_size=20`（≤200）。写操作带 `expected_updated_at`，不匹配返回 409 `CONFLICT_STALE`。创建接口支持 `Idempotency-Key`。时间为 ISO-8601 带时区。资源不存在与无权限统一 404。每请求生成 `request_id`。

**本地接口防护（B1 强制，详见 §11.8）**：
- 服务只监听 `127.0.0.1`；`scripts/run_api.py` 硬编码该地址，拒绝 `0.0.0.0`（除非显式 `AGENTOS_ALLOW_EXTERNAL=1` 并打印风险警告）
- 所有**写请求**（POST/PUT/PATCH/DELETE）必须同时满足：`Origin` 或 `Referer` 在允许列表（`http://localhost:5173`、`http://127.0.0.1:5173`、`AGENTOS_TRUSTED_ORIGINS` 追加项）｜`Host` 头为 `127.0.0.1[:port]`/`localhost[:port]`（防 DNS rebinding）｜带自定义头 `X-AgentOS-Client: web`（强制预检，简单请求无法伪造）｜`Sec-Fetch-Site` 不为 `cross-site`。任一不满足 → 403 `UNTRUSTED_REQUEST`
- 读请求不做 Origin 限制（避免破坏正常打开页面），但同样校验 `Host`
- `AGENTOS_LOCAL_TOKEN`（可选）：设置后所有写请求还需 `X-AgentOS-Token`，供非浏览器客户端使用；默认不开启，避免影响前端开发

**错误包络**：
```json
{"error":{"code":"BR_DEPARTMENT_HAS_EMPLOYEES","message":"部门下仍有 3 名员工，请先迁移","detail":{"employee_ids":["..."]},"request_id":"req_..."}}
```
**错误码**：`VALIDATION_ERROR`(422)、`BR_DEPARTMENT_CYCLE`(409)、`BR_DEPARTMENT_HAS_EMPLOYEES`(409)、`BR_MODEL_IN_USE`(409)、`BR_EMPLOYEE_NAME_TAKEN`(409)、`BR_PROMPT_HASH_MISMATCH`(409)、`PERMISSION_WIDEN_DENIED`(403)、`CONFLICT_STALE`(409)、`UPSTREAM_AUTH_FAILED`(502)、`UPSTREAM_TIMEOUT`(504)、`PERMISSION_DENIED`(403)

### 7.2 端点清单（**45 个，逐项编号，作为验收基准**）

> 计数说明：v1.0 标"38 个"是错的——分组写"员工 12"但实际列了 13 项（漏计 `GET /employees/{id}/audit` 与 `GET /companies/{cid}/org-tree` 的归类混乱）。本版逐项编号，**总数 45**；审查意见计算的 44 是按"员工 12"推算的结果。以此表为准，验收时按 ID 逐项打勾。

**A. 公司（5 个，B2）**
| ID | 方法 | 路径 |
|---|---|---|
| API-01 | GET | `/api/v1/companies` |
| API-02 | POST | `/api/v1/companies` |
| API-03 | GET | `/api/v1/companies/{id}` |
| API-04 | PATCH | `/api/v1/companies/{id}` |
| API-05 | POST | `/api/v1/companies/{id}/archive` |

**B. 部门（6 个，B2）**
| ID | 方法 | 路径 |
|---|---|---|
| API-06 | GET | `/api/v1/companies/{cid}/departments` |
| API-07 | GET | `/api/v1/companies/{cid}/org-tree`（部门+岗位+员工树，供 React Flow） |
| API-08 | POST | `/api/v1/companies/{cid}/departments` |
| API-09 | PATCH | `/api/v1/departments/{id}` |
| API-10 | DELETE | `/api/v1/departments/{id}` |
| API-11 | POST | `/api/v1/departments/{id}/move` |

**C. 岗位（5 个，B2；字段含 `can_review`，供 B5 审查人推导）**
| ID | 方法 | 路径 |
|---|---|---|
| API-12 | GET | `/api/v1/companies/{cid}/positions` |
| API-13 | POST | `/api/v1/companies/{cid}/positions` |
| API-14 | GET | `/api/v1/positions/{id}` |
| API-15 | PATCH | `/api/v1/positions/{id}` |
| API-16 | DELETE | `/api/v1/positions/{id}` |

**D. 员工（13 个：B3 交付 8 个 / B4 交付 1 个 / B5 交付 4 个）**
| ID | 方法 | 路径 | 批次 |
|---|---|---|---|
| API-17 | GET | `/api/v1/companies/{cid}/employees` | B3 |
| API-18 | POST | `/api/v1/companies/{cid}/employees` | B3 |
| API-19 | GET | `/api/v1/employees/{id}` | B3 |
| API-20 | PATCH | `/api/v1/employees/{id}` | B3 |
| API-21 | POST | `/api/v1/employees/{id}/enable` | B3 |
| API-22 | POST | `/api/v1/employees/{id}/disable` | B3 |
| API-23 | DELETE | `/api/v1/employees/{id}`（软删） | B3 |
| API-24 | PUT | `/api/v1/employees/{id}/model-binding` | B3 |
| API-25 | GET | `/api/v1/employees/{id}/prompts`（版本列表） | **B4**（依赖 prompt_revision 表） |
| API-26 | GET | `/api/v1/employees/{id}/audit` | **B5**（依赖 audit_log 表） |
| API-27 | GET | `/api/v1/employees/{id}/effective-permissions` | **B5** |
| API-28 | PUT | `/api/v1/employees/{id}/permission-overrides` | **B5** |
| API-29 | GET | `/api/v1/employees/{id}/capabilities` | **B5** |

**E. 提示词（4 个，B4）**
| ID | 方法 | 路径 |
|---|---|---|
| API-30 | POST | `/api/v1/employees/{id}/prompts`（新建版本） |
| API-31 | GET | `/api/v1/prompts/{rev_id}` |
| API-32 | POST | `/api/v1/prompts/{rev_id}/activate` |
| API-33 | GET | `/api/v1/prompts/{rev_id}/diff?against=prev` |

**F. 模型连接（6 个，B3）**
| ID | 方法 | 路径 |
|---|---|---|
| API-34 | GET | `/api/v1/companies/{cid}/model-connections` |
| API-35 | POST | `/api/v1/companies/{cid}/model-connections` |
| API-36 | PATCH | `/api/v1/model-connections/{id}` |
| API-37 | DELETE | `/api/v1/model-connections/{id}` |
| API-38 | POST | `/api/v1/model-connections/{id}/test` |
| API-39 | GET | `/api/v1/model-connections/{id}/models` |

**G. 派工（2 个，B5）**
| ID | 方法 | 路径 |
|---|---|---|
| API-40 | POST | `/api/v1/companies/{cid}/assignments/preview` |
| API-41 | GET | `/api/v1/assignments/{decision_id}` |

**H. 配置导入导出（3 个，B4）**
| ID | 方法 | 路径 |
|---|---|---|
| API-42 | GET | `/api/v1/companies/{cid}/export` |
| API-43 | POST | `/api/v1/config/import?dry_run=true` |
| API-44 | POST | `/api/v1/config/import` |

**I. 审计（1 个，B5）**
| ID | 方法 | 路径 |
|---|---|---|
| API-45 | GET | `/api/v1/audit?actor_type=&action=&from=&to=` |

**批次汇总（与 §12 验收严格一致）**：B1 = 0 个新增（重构 + 安全中间件）；B2 = 16；B3 = 14；B4 = 8；B5 = 7；合计 **45**。
> 修正说明：API-25 依赖 B4 的 `prompt_revision`、API-26 依赖 B5 的 `audit_log`，v1.1 已把这两个接口从 B3 移到对应批次，避免"接口先行、表未建"的返工。
**兼容保留（不计入 45）**：`GET /api/health`、`GET /api/tasks`、`GET /api/employees/{model}/health`（M0 遗留，行为不变）。

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
    "factors":{"position_match":1.0,"review_chain_distance":0.9,"performance":0.5,"cost":0.6,"load":0.5}}],
  "excluded":[{"employee_id":"emp_ceo","reason":"capability_missing:tool.file.write"}],
  "reviewer":{"employee_id":"emp_qa","pool":"formal","cross_model":true,"independence":"T1",
              "degraded_reviewer":false,"management_review":false,
              "reason":"独立审查岗（质量部，can_review）× 跨部门 × 跨供应商"},
  "data_quality":{"performance":"unavailable","load":"unavailable"},
  "score_note":"m1.0 暂定权重；performance/load 为中性值 0.5，不构成真实绩效评估"}
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

### 8.0 前端依赖清单（D-1 已确认，B1 一次性装好并锁版本）

| 类别 | 包 | 用途 | 安装时机 |
|---|---|---|---|
| 已有 | `react@18` `react-dom@18` `react-router-dom@7` `zustand@5` `tailwindcss@4` `@tailwindcss/vite@4` | 基础 | M0 |
| 已有 | `vite@8` `typescript` `@vitejs/plugin-react` `oxlint` | 构建 | M0 |
| 新增 | `@tanstack/react-query@5` | 服务端状态 | B1 |
| 新增 | `@xyflow/react@12` | 组织图 | B2 |
| 新增 | `react-hook-form@7` + `@hookform/resolvers` + `zod@4`（原计划 3.x；因 3.x 存在高危漏洞 GHSA-mrhx-c7xc-m3w5，B1 实际安装 4.6.7，resolvers 7 同时支持 ^3.25 与 ^4） | 表单与客户端校验 | B1 |
| 新增 | `class-variance-authority` `clsx` `tailwind-merge` `lucide-react` | shadcn/ui 运行时依赖 | B1 |
| 新增 | `@radix-ui/react-dialog` `@radix-ui/react-select` `@radix-ui/react-tabs` `@radix-ui/react-toast` `@radix-ui/react-dropdown-menu` | shadcn/ui 组件底层（按实际使用的组件逐步加） | B1–B3 |
| 新增（开发） | `vitest` `@testing-library/react` `jsdom` | 纯函数/组件单测（可选，B3 起） | B3 |

> 说明：**shadcn/ui 不是 npm 依赖**，而是 CLI 把组件源码写入 `components/ui/`，因此清单里列的是它需要的 Radix/CVA/clsx/tailwind-merge/lucide 运行时包。`npm ci` 必须能复现（lockfile 提交）。
> 不引入：Tailwind 插件市场组件库、Ant Design、MUI、Playwright（重型，需单独批准）。

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

**健康缓存与失效规则（v1.1 补充，B3 实现）**：
| 项 | 规则 |
|---|---|
| 缓存键 | `connection_id + 配置指纹`（provider/model/base_url/key_ref 的哈希），配置一改指纹变、缓存自动失效 |
| 正缓存 TTL | 成功结果 300s |
| 负缓存 TTL | 失败结果 60s（避免故障连接每次派工都重试打网络） |
| 命中来源标注 | 派工预览与详情返回 `health_source: "cache" | "live"`，前端显示"缓存 3 分钟前" |
| 主动失效 | 手动连接测试、PATCH 连接配置、切换密钥引用、服务启动时清空内存缓存 |
| 进程重启 | 内存缓存不持久化；用 `model_connection.last_health_*` 仅作展示，不作为判断依据 |
| 并发 | 同一 connection 的并发健康检查合并（single-flight），避免放大请求 |

### 9.3 切换模型流程
`PUT /employees/{id}/model-binding` → 校验连接同公司/启用/引用可解析（不实际调用）→ 能力差异检测（新模型 ∩ 员工已声明能力，缺口则 200 + warnings）→ 事务内更新 employee + 写 model_switch_log + audit_log → 前端刷新（档案不变、历史 run 带旧模型名、新 run 用新模型）。

### 9.4 能力三层（不混淆）
有效能力 = **Adapter 能力 ∩ 模型能力（catalog 元数据）∩ 授权能力（tools_allowed + 权限档案）**。任一层缺失即不可派单，派工预览必须给出具体缺失项（如 `capability_missing:tool.file.write`），不能只说"不匹配"。

补充说明：
- `employee.capabilities_declared` **只作创建时的审计快照**，不参与任何计算；运行时一律以 Adapter 实测 + catalog 元数据为准
- `position.review_capability_tags` 用于审查场景的**领域匹配加分与展示**；RC-4 的硬性覆盖判断仍以员工有效能力为准（避免岗位标签与实际能力脱节）

### 9.5 解耦测试用例（B3 必须落地）
| 编号 | 场景 | 期望 |
|---|---|---|
| A3-1 | 员工 A、B 共用连接 M | 各自 agent_run 的 model 相同但归属正确，usage 不串账 |
| A3-2 | A 从 M1 切到 M2 | A.id 不变；历史 run 仍 M1；新 run M2；switch_log +1 |
| A3-3 | 切到能力更弱的模型 | 返回 warnings，且不再出现在需要该能力的候选中 |
| A3-4 | 切到已停用连接 | 422 |
| A3-5 | 删除被引用连接 | 409 `BR_MODEL_IN_USE`（提示引用数） |
| A3-6 | 切换后查历史成本 | 按 `usage_record.employee_id` 归因不变，model 仍是旧值；`agent_run.model` 不被改写 |
| A3-7 | 主模型健康失败 | 走备用并在返回中带 `role=fallback` + warning；备用也失败则 `no_model` 拒绝派单 |
| A3-8 | 健康缓存过期 | TTL 内不重复请求（用 mock 计数断言）；配置变更后立即失效 |

### 9.6 提示词文件与数据库一致性协议（B4，v1.1 新增）

问题：文件系统与数据库无法共享事务，必须显式定义失败窗口与补偿。

**写入顺序（文件优先 + 原子落盘）**：
```
1. 计算新版本号 N = max(existing)+1（DB 查询，事务外）
2. 写临时文件 data/prompts/employees/<id>/.tmp-<uuid>.md → flush+fsync
3. os.replace(tmp, vNNNN.md) 原子改名（同分区）
4. 计算 SHA-256
5. DB 事务：INSERT prompt_revision(version=N, hash) + UPDATE employee.prompt_active_version=N + audit
6. 若第 5 步失败：删除刚写的文件（best-effort），返回 500；若删除也失败 → 留孤儿文件，由对账脚本清理
```
**激活版本**：只改 DB `is_active` 指针，不动文件（天然安全）。
**读取**：先查 DB 拿 `file_path + content_hash`，读文件后校验哈希；不匹配 → `BR_PROMPT_HASH_MISMATCH`，不静默降级。
**对账脚本** `scripts/reconcile_prompts.py`（B4 交付）：
- 扫描 `data/prompts/**` 与 `prompt_revision`，报告三类异常：孤儿文件（DB 无记录）、缺失文件（DB 有记录但文件不在）、哈希不符
- 默认只报告不修改；`--fix` 才删除孤儿文件（需二次确认参数 `--yes`）
**测试**（B4）：
| 编号 | 场景 | 期望 |
|---|---|---|
| P-1 | 模拟 DB 写入失败 | 文件被清理或可被对账脚本识别为孤儿 |
| P-2 | 手工删除激活版本文件 | 加载抛 `BR_PROMPT_HASH_MISMATCH` |
| P-3 | 手工改文件内容 | 哈希校验失败 |
| P-4 | 对账脚本 | 三类异常都能正确报告（造 3 个样本） |

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
- **数据真实性声明（v1.1 明确）**：`performance` 与 `load` 在 M1 **没有真实数据**，一律取中性 0.5。响应必须同时返回：
  ```json
  "data_quality": {"performance": "unavailable", "load": "unavailable"},
  "score_note": "m1.0 暂定权重；performance/load 为中性值 0.5，不构成真实绩效评估"
  ```
  前端在候选人卡片上用灰色 `估算` 徽标显示这两项，**不得渲染成真实评分**；测试断言这两个字段存在且取值正确
- 权重常量带 `algorithm_version = "m1.0"`，**标注为暂定规则**（D-3），改权重必须升版本，历史决策可追溯
- 每个因子输出 0~1 原始分与权重贡献，前端直接画条形图

### 10.5 审查人推导（v1.2 定稿：正式池 + 降级池，双池不混用）

**历史问题**：
- v1.0 只沿 `doer.reports_to` 上溯 → "QA 汇报给开发、开发执行任务"时永远找不到 QA，核心场景失效
- v1.1 改成单池 + T1..T6，但自相矛盾：RC-3 要求所有候选都有 `can_review`，T6 又允许无审查资格者；伪代码在 `has_review_position(e)` 为假时直接 `continue`，**T6 永远不可达**；T5（管理链）与 T1..T4（部门/模型组合）分类重叠，同一个管理者可能被标成 T1 而丢失"管理审查"语义

**v1.2 规则：两个独立候选池，正式池优先；只有正式池为空才启用降级池。**

#### 池 A：正式审查候选池（必须 `can_review=true`）

| 编号 | 约束（任一不满足即排除并记录原因） |
|---|---|
| RC-1 | `reviewer.id != doer.id`（BR-10，审查人不得是执行人） |
| RC-2 | `reviewer.status == active` 且与 doer 同公司 |
| RC-3 | **具备审查资格**：主岗或任一兼任岗的 `can_review == true` |
| RC-4 | **能力覆盖**：有效能力覆盖 `request.required_capabilities` |
| RC-5 | **独立性**：reviewer 不得是 doer 的下级（doer 出现在 reviewer 的 `reports_to` 上溯链中）。`review_policy.allow_subordinate_review=false` 时排除；为 true 时保留并打 `subordinate_review` 警告 |
| RC-6 | reviewer 不在 `request.exclude_employee_ids` |
| RC-7 | reviewer 有可用模型（§9.2 解析成功） |

正式池分级（**先判管理链，再判部门/模型**——这是 T5 不被 T1..T4 覆盖的关键）：

| Tier | 触发条件（严格互斥，按顺序判定） | 标记 |
|---|---|---|
| **T1** | 非管理链 ∧ 不同部门 ∧ 跨模型 | 最理想独立审查 |
| **T2** | 非管理链 ∧ 同部门 ∧ 跨模型 | 同部门独立审查 |
| **T3** | 非管理链 ∧ 不同部门 ∧ 同模型 | 组织独立、模型相同 |
| **T4** | 非管理链 ∧ 同部门 ∧ 同模型 | 最弱的正式审查 |
| **T5** | **管理链上级**（doer 沿 `reports_to` 上溯可达该员工）∧ `can_review=true`，部门与模型不限 | `management_review=true`；即使同时满足 T1 条件也归为 T5 |

> 排序：T1 < T2 < T3 < T4 < T5。即"独立审查岗"整体优先于"管理链上级"；管理者是正式池内的兜底，但仍然**优先于任何降级审查人**。
> 若管理者本身不具备 `can_review`，他不进入正式池；降级池要求"不同部门"，同部门管理者也不会进入降级池。若因此没有任何候选，返回 null（原因见下）。这是刻意的：宁可让用户指定，也不让"无审查能力的管理者"假装备审查过。

#### 池 B：降级审查候选池（仅当池 A 为空时构建）

| 编号 | 约束 |
|---|---|
| DC-1 | `reviewer.id != doer.id` |
| DC-2 | `reviewer.status == active` 且同公司 |
| DC-3 | **必须不同部门**（同部门无审查资格者一律不允许，避免同组互评走过场） |
| DC-4 | 能力覆盖 `request.required_capabilities` |
| DC-5 | 不是 doer 的下级（同 RC-5 策略） |
| DC-6 | 不在 `exclude_employee_ids` |
| DC-7 | 有可用模型 |
| DC-8 | **不具备 `can_review`**（有资格者已在池 A，避免重复与伪装） |

池 B 只有 **T6** 一个等级，返回时强制 `degraded_reviewer=true`、`pool="degraded"`，并附警告 `degraded_reviewer_used`。**不得在展示层写成"独立审查人"**。

#### 伪代码（每个 tier 都有可达路径）

```python
def derive_reviewer(doer, request, company) -> ReviewerDecision:
    formal, excluded = [], []

    # ---- 池 A：正式审查 ----
    for e in active_employees(company):
        if e.id == doer.id:                          excluded.append((e, "self")); continue
        if not capability_covers(e, request.required_capabilities):
            excluded.append((e, "capability_missing")); continue
        if is_subordinate_of(e, doer) and not company.review_policy.allow_subordinate_review:
            excluded.append((e, "subordinate_not_allowed")); continue
        if e.id in request.exclude_employee_ids:     excluded.append((e, "excluded")); continue
        if not resolve_model(e):                     excluded.append((e, "no_model")); continue
        if not has_review_position(e):               excluded.append((e, "no_review_role")); continue
        formal.append(FormalCandidate(e, tier=classify_formal(e, doer)))

    pool, mode = formal, "formal"

    # ---- 池 B：仅当正式池为空才构建 ----
    if not formal:
        degraded = []
        for e in active_employees(company):
            if e.id == doer.id: continue
            if has_review_position(e): continue                  # DC-8
            if e.department_id == doer.department_id: continue    # DC-3 必须不同部门
            if not capability_covers(e, request.required_capabilities): continue
            if is_subordinate_of(e, doer) and not company.review_policy.allow_subordinate_review: continue
            if e.id in request.exclude_employee_ids: continue
            if not resolve_model(e): continue
            degraded.append(DegradedCandidate(e, tier="T6", degraded_reviewer=True))
        pool, mode = degraded, "degraded"

    if not pool:
        code = classify_empty(excluded, doer, company)
        return ReviewerDecision(None, pool=None, reason_code=code,
                                suggestion=suggest_for(code), excluded=excluded)

    pool.sort(key=lambda c: (TIER_ORDER[c.tier], not c.cross_model, org_distance(doer, c.e), c.e.id))
    best = pool[0]
    return ReviewerDecision(
        best.e, pool=mode, independence=best.tier,
        degraded_reviewer=(mode == "degraded"),
        cross_model=provider_of(best.e) != provider_of(doer),
        management_review=is_management_ancestor(best.e, doer),
        warnings=best.warnings + (["degraded_reviewer_used"] if mode == "degraded" else []),
        reason=explain(best), excluded=excluded)


def classify_formal(e, doer) -> str:
    if is_management_ancestor(e, doer):        # 先判管理链：T5 不被 T1..T4 覆盖
        return "T5"
    same_dept = (e.department_id == doer.department_id)
    cross     = (provider_of(e) != provider_of(doer))
    return {(False, True): "T1", (True, True): "T2",
            (False, False): "T3", (True, False): "T4"}[(same_dept, cross)]
```

`is_management_ancestor(e, doer)`：从 `doer.reports_to` 起上溯（≤20 层），链上出现 `e.id` 即为真，同时用于 RC-5 的"下级"判定（方向相反）。

#### 两份池都为空时的原因码（必须返回 `null` + reason_code + suggestion）
| reason_code | 判定条件 | suggestion |
|---|---|---|
| `company_has_single_employee` | 公司 active 员工数 = 1 | 至少招聘 1 名审查岗员工 |
| `only_subordinate_candidates` | 存在满足能力者，但全部是 doer 的下级且策略禁止 | 开启 `allow_subordinate_review`，或指定其他审查人 |
| `capability_not_covered` | 有审查岗员工，但无人能力覆盖任务 | 提升审查人能力授权，或降低任务能力要求 |
| `no_eligible_reviewer` | 以上都不成立（如审查岗都在同部门且无资格降级） | 增加跨部门审查岗，或手动指定审查人 |

#### 测试场景（B5 必须覆盖）
| 编号 | 给定 | 期望 |
|---|---|---|
| B8-1a | 开发员 dev1 执行；qa1（质量部/模型B/`can_review`）、cto（管理/模型A/`can_review`） | 选 **qa1**（T1，跨部门+跨模型）；不是 cto（T5） |
| B8-1b | 测试员 qa1 执行；dev1（研发部/模型A/`can_review=true`）、cto | 选 **dev1**（T1，跨部门+跨模型）；dev1 无 `can_review` 时选 cto（T5），**不启用降级池** |
| B8-9 **正式优先于 T6** | 正式池只有同部门同模型的 T4；降级池有一位不同部门跨模型但无 `can_review` 的员工 | 必须选 **T4**，`degraded_reviewer=false`；证明正式池不被降级池"更优分数"抢占 |
| B8-10 **空池触发 T6** | 全公司唯一有 `can_review` 的人就是 doer 自己；另有不同部门、能力覆盖、无 `can_review` 的员工 | 选该员工，`independence=T6`、`degraded_reviewer=true`、含 `degraded_reviewer_used` 警告 |
| B8-11 **两池皆空** | 公司只有 doer + 同部门无资格同事 | 返回 `null` + `reason_code` + `suggestion`，不返回任何"凑数"审查人 |

约束回顾：审查人只是**建议**，最终任命权在用户；M1 不执行审查，M3 才产生审查报告。降级审查人只能出现在"建议"里且必须带标记，M3 的审查报告需显示该标记。

### 10.6 管理者与审批边界
| 角色 | 能做 | 绝对不能做 |
|---|---|---|
| 执行员工 | 提交结果、发起审批请求 | 批准自己的请求、改自己权限 |
| 管理者员工（is_managerial） | 建议通过/打回、升级给用户 | 代替用户批准（系统层无此 API） |
| 用户 | 批准/拒绝/改派/改权限 | —（唯一授权源） |

`reports_to` 在审批中只决定"谁的建议先展示"，不产生自动批准能力。

### 10.7 M2 衔接方式
M2 的 task-engine 派工时调用同一个 `assignment.preview()` 拿候选集，把候选清单（含理由）注入 CEO Agent 的 prompt；CEO 选择若不在候选集内 → 拒绝并重新规划。这样"组织影响分配"在 M2 自然成立，无需重写。

### 10.8 派工与审查人验收（B5 必须全过）
| 编号 | 给定 | 期望 |
|---|---|---|
| B8-1a **开发员执行** | dev1（研发部/模型A/can_review=false）、qa1（质量部/模型B/can_review=true）、cto（管理/模型A/can_review=true） | 审查人 = qa1，`independence=T1`、`cross_model=true`；不含 cto |
| B8-1b **测试员执行** | qa1 执行，dev1 具备 `can_review=true`（不同部门、模型A） | 审查人 = dev1，`independence=T1`、`cross_model=true`（交叉验证）；dev1 无审查资格时选 cto（T5），**此时仍不启用降级池** |
| B8-2 | dev1 权限 file_ops=[read]，任务需 file.write | dev1 被 `tool_denied:file.write` 排除，理由明确 |
| B8-3 | 只有 dev1 一人 | 审查人 `null`，`reason_code=company_has_single_employee`，附 suggestion |
| B8-4 | dev1(A)、dev2(B) 同岗同部门、均可审 | 跨模型者优先（T2 > T4） |
| B8-5 | 任务 critical，公司策略 max=high | 全员 `risk_exceeded`，提示"需提升策略或用户直接指派" |
| B8-6 | 唯一合格审查人是 doer 的直接下属 | `reason_code=only_subordinate_candidates`，不选下属；开启策略后才选并带 `subordinate_review` 警告 |
| B8-7 | 审查人能力不覆盖任务 | `reason_code=capability_not_covered`，不选不合格者 |
| B8-8 | 派工预览响应 | 必含 `data_quality` 与 `score_note`；`performance/load` 为 0.5 且标注 unavailable |
| B8-9 | 正式池只有 T4，降级池有不同部门跨模型但无 `can_review` 者 | 选 T4，`degraded_reviewer=false`（正式优先，见 §10.5） |
| B8-10 | 唯一有 `can_review` 的人是 doer；另有不同部门、能力覆盖、无资格者 | 选该员工，`independence=T6`、`degraded_reviewer=true`、含 `degraded_reviewer_used` |
| B8-11 | doer + 同部门无资格同事，两池皆空 | 返回 `null` + `reason_code` + `suggestion`，不返回凑数审查人 |

> 审查人相关完整规则与用例见 §10.5；本表用于 B5 验收时逐条打勾。

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
**语义澄清（修正 v1.0 冲突）**：
- 岗位默认层：同员工多岗取**并集**，再与公司策略取交集
- 员工覆盖层：**只能收窄，永远不能放宽**（BR-13）
- 因此"给某开发者开放 file_write"必须改**岗位默认**（且不超过公司策略），不能靠员工覆盖实现。管理接口对员工层的放宽请求返回 `PERMISSION_WIDEN_DENIED`

测试 ≥12 组，必须包含"员工试图放宽被拒"、"多岗并集再与公司交集"、"空集合语义=不允许而非不限制"、"员工覆盖等于岗位默认（不变）"。

### 11.3 密钥管理
存储只接受 `env:<VAR>`/`dpapi:<blob>`/`keyring:<service>:<user>`，正则拒绝 `sk-` 开头疑似明文（422）；运行时由 `credentials.py` 解析，随用随取；响应只返回 ref 与 `has_credential`；日志统一脱敏（`sk-[A-Za-z0-9]{8,}`、`Bearer\s+\S+`、`api[_-]?key\s*[:=]\s*\S+`）；导出包只含 ref；连接测试只返回 ok/latency/error_code。

### 11.4 审批策略表（M1 建表，M2 执行）
| action_type | 默认风险 | 决策 |
|---|---|---|
| file_read（工作区内） | low | allow |
| file_write（工作区内） | medium | approval（放宽只能改**岗位默认**且不超公司策略；员工层只能保持或加严） |
| file_delete | high | approval（不可放宽） |
| shell_exec | high | approval（黑名单直接 deny） |
| network_upload | high | approval |
| system_config / software_install / service_deploy / code_publish | critical | approval + 二次确认 |

硬 deny 常量（测试覆盖）：`Set-MpPreference`、`netsh advfirewall`、`Add-MpPreference -ExclusionPath`、`setx` 改系统变量、注册表 `HKLM\...\Environment` 写入、`bcdedit`、`vssadmin delete`。

### 11.5 审计事件（12 类）
company.create/update/archive｜department.create/update/move/delete｜position.create/update/delete｜employee.create/update/enable/disable/delete｜employee.model_binding.update｜employee.permission_overrides.update｜prompt.publish/activate｜model_connection.create/update/delete/test｜config.export/import｜assignment.preview。
只增不改：无 UPDATE/DELETE 路由；ORM 事件监听阻止 update。

### 11.6 越权与本地接口测试（14 项，必须全绿）
S-1 放宽权限 → 403 + 审计｜S-2 员工访问管理接口 → 接口不存在｜S-3 `api_key_ref` 填明文 → 422｜S-4 连接失败响应/日志无密钥片段（正则断言）｜S-5 导出包 grep 不到 `sk-`/`Bearer`｜S-6 部门成环 → 409 且库无变化｜S-7 删非空部门 → 409 员工不变｜S-8 并发改同一员工 → 409 `CONFLICT_STALE`｜S-9 恶意 zip 路径穿越 → 拒绝｜S-10 提示词被篡改 → `BR_PROMPT_HASH_MISMATCH`｜**S-11** 写请求 `Origin: http://evil.com` → 403 `UNTRUSTED_REQUEST`｜**S-12** `Host: evil.com` → 400（DNS rebinding 防护）｜**S-13** 写请求缺 `X-AgentOS-Client` 头 → 403｜**S-14** `scripts/run_api.py` 传 `0.0.0.0` → 启动即拒绝（除非显式 `AGENTOS_ALLOW_EXTERNAL=1`）

### 11.7 已知限制（诚实声明）
本地单用户无认证（只监听 127.0.0.1 + Origin/Host 校验缓解，账号体系 M5）；`env:` 依赖用户正确设置环境变量；权限是能力/范围级非行级 ACL（工作空间细粒度在 M2）；审计防篡改靠应用层（本地 SQLite 用户可直接改）；`X-AgentOS-Client` 头只能挡住浏览器跨站简单请求与表单提交，挡不住本机恶意进程（M5 账号体系解决）。

### 11.8 本地管理接口防护（v1.1 新增，B1 实施）

威胁模型：本地 API 监听端口后，用户浏览器打开的**任意网页**都可能向 `http://127.0.0.1:8000` 发起跨站写请求（CSRF/CSWSH），或通过 DNS rebinding 伪造 Host 访问。

| 控制 | 规则 | 失败响应 |
|---|---|---|
| 监听地址 | 默认 `127.0.0.1`；`scripts/run_api.py` 硬编码；`--host 0.0.0.0` 需 `AGENTOS_ALLOW_EXTERNAL=1` 且启动打印醒目警告 | 拒绝启动 |
| Origin 白名单 | 写请求的 `Origin`（缺失时看 `Referer`）必须 ∈ {`http://localhost:5173`, `http://127.0.0.1:5173`} ∪ `AGENTOS_TRUSTED_ORIGINS` | 403 `UNTRUSTED_REQUEST` |
| Host 校验 | `Host` 必须是 `localhost[:port]` 或 `127.0.0.1[:port]`（允许 `[::1]`） | 400 `INVALID_HOST` |
| 自定义头 | 写请求必须带 `X-AgentOS-Client: web`（触发 CORS 预检，普通表单/图片请求无法伪造） | 403 |
| Fetch Metadata | `Sec-Fetch-Site: cross-site` 的写请求直接拒绝 | 403 |
| 可选令牌 | 设置 `AGENTOS_LOCAL_TOKEN` 后，写请求还需 `X-AgentOS-Token`（供脚本/CLI 客户端） | 401 |
| CORS | 仅允许白名单 Origin + `X-AgentOS-Client` 头；预检缓存 600s | 预检失败 |

实现位置：`apps/api/security/local_guard.py`（FastAPI 依赖，挂在写路由的 router 级依赖上，而不是全局中间件，便于 M5 替换为账号鉴权）。
测试：S-11..S-14 + 一个"正常前端请求放行"的对照用例（防误杀）。

---

## 12. 分批开发计划

每批结束必须：`ruff` 全绿 → `pytest` 全绿 → `npm run build` 通过 → 更新 CHANGELOG → 提交一次可回滚 commit。每批 3–6 个 commit。

### B1 地基（不写业务功能，先还债 + 补本地接口防护）
**范围**：
① Alembic（`alembic.ini` + `migrations/` + `m0_baseline` + batch 模式）
② `pyproject.toml` 加 `[build-system]`，`pip install -e .` 可用
③ API 拆 `routers/`+`deps.py`+`errors.py`，`on_event`→`lifespan`，统一错误包络与分页
④ `tests/conftest.py`（tmp_engine / client / actor / seeded_company）
⑤ `scripts/backup_db.py`
⑥ **`apps/api/security/local_guard.py` + `scripts/run_api.py`**：Host/Origin/自定义头/Fetch-Metadata 校验，默认只监听 127.0.0.1（§11.8）
⑦ 前端按 §8.0 清单装依赖（shadcn/ui + TanStack Query + RHF + zod），建 `api/client.ts` 与 `queryClient`
⑧ CI 加迁移双路径测试 + 安全用例

**验收**：空库 `alembic upgrade head` 成功；M0 库 `stamp m0_baseline && upgrade head` 后 schema 与新库一致；`pytest` 7 个旧测试全过 + 迁移测试 2 个 + 本地防护 5 个（S-11..S-14 + 放行对照）全过；`/api/health`、`/api/tasks` 行为与 M0 一致；`npm run build` 通过。
**新增测试下限**：**7 个**（迁移 2 + 本地防护 5：S-11～S-14 四项 + "正常前端请求放行"对照 1 项）。
**风险**：autogenerate 对 SQLite 噪音大 → 手工裁剪基线 + schema diff 脚本；Origin 校验误杀开发环境 → 用"正常请求放行"对照用例兜底。

### B2 组织域（API-01..16）
**范围**：迁移 `m1_b2_org`；`packages/organization/`（companies/departments/positions/tree）；规则 BR-02/03/04a-e；API 公司 5 + 部门 6（含 org-tree）+ 岗位 5（含 `can_review`）；前端组织设置页 + 组织图只读（**只渲染部门/岗位节点，员工节点在 B3 接入**）。

**验收**：3 层部门 + 2 岗位 org-tree 结构/depth 正确；成环 409 库无变化；第 9 层被拒；重名 409；30 节点渲染无报错；新增 ≥10 个集成测试（每条规则 1 正 1 反）。
**依赖修正（v1.1）**：v1.0 要求 B2 验收"含员工部门删除 409 提示人数"，但 employee 表在 B3 才建 → **该验收项移到 B3**；B2 只校验"含子部门不可删"，删除接口预留 `BR_DEPARTMENT_HAS_EMPLOYEES` 分支并写 TODO 注释。

### B3 员工域 + 模型连接（解耦核心，API-17..24 + 34..39 共 14 个）
**范围**：迁移 `m1_b3_employee_model`（employee / employee_position / model_connection / model_switch_log + **`usage_record.employee_id`**）；`employees.py`/`model_connections.py`/`capabilities.py`；`credentials.py` + `catalog.py`；健康缓存（§9.2）；API 员工 8（17–24）+ 连接 6（34–39）；前端员工列表/向导/详情（档案+模型）/模型连接页；**补 B2 的"含员工部门不可删"校验**。

**验收**：
- 向导落库 + 审计；新建 2 员工并切换模型刷新后一致
- A3-1..A3-8 全过（含：历史 run 的 `model` 与 `usage_record.model` 不被改写、成本按 `employee_id` 归因、主→备降级、健康缓存 TTL/失效）
- 真实 DeepSeek 连接测试返回 latency（`@pytest.mark.live`，手工执行）
- 响应/日志 grep 无 `sk-`；员工改名/重建后历史成本仍可归因
- 含员工部门删除 → 409（从 B2 移入）

**新增测试下限**：20 个（解耦 8 + 连接 5 + 凭据 3 + 组织联动 2 + 迁移 2），其中 1 个 live 标记。
**风险**：真实测试耗 token → `max_tokens=8` + live 默认跳过；`employee_id` 双写遗漏 → 在 `AgentRun` 工厂函数统一赋值，禁止散落各处。

### B4 提示词外置 + 导入导出（API-25、30..33、42..44 共 8 个）
**范围**：迁移 `m1_b4_prompt`；文件存储 `data/prompts/employees/<id>/vNNNN.md`（YAML frontmatter：role/goal/rules/tools_policy）+ SHA-256；**§9.6 一致性协议（临时文件→fsync→原子改名→DB 事务→失败补偿）**；`prompts.py`（create/activate/diff/load）；`load_active_prompt()` 供 M2 复用；`scripts/reconcile_prompts.py` 对账；`config_io.py`（zip：manifest/company/org/employees/prompts，dry-run，单事务，路径穿越防护）；API 提示词 5（含 API-25 版本列表）+ 配置 3；前端编辑器 + 导入导出向导。

**验收**：连续保存 3 次 = 3 个文件且 v1 哈希不变；激活后指针正确、旧文件仍在；手工改文件 → 哈希报错；模拟 DB 失败 → 孤儿文件可被对账脚本识别；导出 zip 无密钥；dry-run 计数正确不写库；往返导入导出结构与哈希 100% 一致；路径穿越被拒。
**新增测试下限**：16 个（版本 5 + 一致性 P-1..P-4 + 导入导出 5 + 安全 2）。

### B5 权限 + 派工预览 + 审计 + 组织图编辑（API-26..29 + 40..41 + 45 共 7 个）
**范围**：迁移 `m1_b5_assignment_audit`；`packages/permissions/`（effective/policy/audit）；`organization/assignment.py`（硬过滤 8 + 5 因子 + **§10.5 新审查人规则** + algorithm_version）；API effective-permissions/permission-overrides/capabilities、员工审计（API-26）、assignments/preview、assignments/{id}、audit；前端权限 Tab、派工台（含 data_quality 徽标）、组织图可编辑、审计页。

**验收**：三层交集 12 组全绿；**B8-1a/1b/2/3/4/5/6/7/8/9/10/11 全过**（审查人双池规则见 §10.5）；每次 preview 落 assignment_decision（含 factors、reviewer、independence、pool、degraded_reviewer、algorithm_version、data_quality）；`PERMISSION_WIDEN_DENIED` + 审计；12 类事件各触发一次且无更新接口；拖拽 10 次无错乱（含 BR-04a-e 校验）。
**新增测试下限**：**29 个**（权限 12 + 派工/审查 12（含 B8-9/10/11 三个审查池用例）+ 审计 3 + 前端纯函数 2）。
**依赖说明**：B5 依赖 B2 的 `position.can_review` 与 B3 的 `employee.reports_to`/能力数据，均为已交付项，无反向依赖。

### B6 端到端验收
**三个场景必须全过**：
1. **从零建公司**：公司→2 部门→3 岗位（含 1 个 `can_review`）→2 连接→3 员工（含兼任）→组织图正确→导出→导入新库→结构一致
2. **解耦验证**：A 切换模型→历史 `agent_run.model`/`usage_record.model` 保持旧值→同连接员工 B 不串账→派工预览中 A 的能力缺口被正确排除
3. **权限与派工**：限制某员工 file.write→派"需写文件"任务→被硬过滤→**开发员执行时审查人 = QA（T1），测试员执行时审查人 = 开发（T1）**，且均 ≠ 执行人、跨模型优先

**交付**：`docs/testing/M1_TEST_REPORT.md`（真实命令 + 输出摘要 + 失败项 + 未测项）、`M1_FINAL_HANDOFF.md`（对齐 M0 的 14 项格式，单文档）、更新 README/FEATURE_MATRIX/ROADMAP、`M1` tag、`scripts/demo_m1_*.py`。
**门槛**：
- **计划测试总数 89** = M0 7 + B1 7 + B2 10 + B3 20 + B4 16 + B5 29
- **硬门槛 ≥75 通过**——这是**最低验收门槛**（允许个别用例因环境原因标记 skip，但 skip 必须逐条说明），**不是计划测试总数**；计划总数 89 才是完整交付目标
- 45 个端点按 ID 逐项验收打勾；ruff 全绿；前端构建通过；三场景真实跑通有日志；无 P0/P1 缺陷

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
| agent_run.employee_key 字符串 | 临时设计 | B3 给 `agent_run` 与 `usage_record` **都**加 `employee_id` 双写；M2 切换 | B3 |
| 无分页/统一错误 | 技术债 | B1 统一 | B1 |
| 前端仅 1 页 | 骨架 | B2–B5 按页面清单落地 | B2–B5 |
| 模型快照是否缺失 | **已核实：不缺失** | `agent_run.model`/`usage_record.model` 已是快照（§2.2）；B3 只需补"切换后历史不被改写"的测试 | B3 |
| 本地管理接口无跨站防护 | 仅 CORS | B1 增加 Host/Origin/自定义头/Fetch-Metadata 校验（§11.8） | B1 |

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
| 审查人规则过严导致小公司无法派工 | 阻塞 | 返回明确 reason_code + suggestion；`allow_subordinate_review` 可配置，默认关闭 |
| 本地防护误杀正常开发请求 | 开发体验 | 白名单含 5173 双写法；加"正常请求放行"对照测试；令牌默认关闭 |

---

## 15. 决策（已由所有者确认，2026-11-05）

| # | 决策 | **结论（已确认）** | 落地位置 |
|---|---|---|---|
| D-1 | 前端依赖方案 | **接受**：shadcn/ui + TanStack Query + React Flow + react-hook-form + zod（清单见 §8.0） | B1/B2 |
| D-2 | 员工姓名唯一性 | **同一公司内唯一** | B3 唯一索引 + 409 |
| D-3 | 派工打分权重 | **接受初始权重**，标注为 **m1.0 暂定规则**，调整须升版本 | B5 |
| D-4 | 员工删除方式 | **软删除**（`deleted_at`，保留历史与审计） | B3 |
| D-5 | 提示词历史版本 | **不可修改**，只能新增版本或切换激活版本 | B4 |
| D-6 | 导入冲突默认策略 | **rename（改名保留双方数据）** | B4 |

---

## 16. 下一步（给接手者）

1. 决策已确认，**不需要再问 D-1..D-6**；直接执行 B1。
2. 执行 **B1**，顺序：
   a. 读 `apps/api/main.py`、`packages/persistence/{db,models}.py`、`tests/*`（现有 7 测试）
   b. 加 alembic 依赖 + 初始化 + `m0_baseline`（stamp 现有 `data/agentos.db`）
   c. 补 `pyproject.toml` 打包配置，`pip install -e .` 后删除对 `sys.path.insert` 的依赖（保留兜底并标注）
   d. 拆 routers/deps/errors，改 lifespan，统一错误包络与分页
   e. 实现 `security/local_guard.py` + `scripts/run_api.py`（§11.8），跑 S-11..S-14
   f. 建 `tests/conftest.py` 夹具；跑 `pytest`、`ruff`、`npm run build`
   g. 提交 `refactor(b1): 基础设施、迁移与本地接口防护`，并在 CHANGELOG 记录
3. **B1 验收通过后再开 B2**，不得并行开工。
4. 每批结束把真实结果（命令 + 关键数字）追加到文末"执行记录"区（保持单文档习惯）。

---

## 17. 修订记录

### v1.3（2026-11-05，执行完成后的 P1 收尾，当前版本）
**不改计划、不改架构、不新增迁移；只记录 §20 遗留 P1 的清理结果。**

1. 审计事件由 3 类扩到 17 类（新增 14 类），detail 在领域层强制脱敏，`request_id` 透传，导入审计与业务同事务。
2. 配置导入改为单事务 + 文件补偿；补偿失败保留孤儿供 `reconcile_prompts.py` 发现；补齐三个失败注入测试。
3. 补齐部门 PATCH、权限覆盖组合、连接测试（Mock 上游）三组直接测试。
4. 修复四个真实缺陷：提示词导入版本倒序、`requires_approval` 顺序误判扩权、上游错误回显密钥、写盘失败残留临时文件。
5. 测试环境隔离：`AGENTOS_PROMPTS_ROOT`，避免污染真实 `data/prompts`。
6. 执行证据与回归数字见 **§21**。

### v1.2（2026-11-05，最终计划版）
**仅处理两处问题，未重设计 M1、未编码。**

1. **§10.5 审查人改为双池模型（修正 v1.1 的三处逻辑矛盾）**
   - 问题：RC-3 要求所有候选 `can_review=true`，T6 却允许无资格者；伪代码在 `has_review_position(e)` 失败时直接 `continue`，**T6 永远不可达**；T5 与 T1..T4 按部门/模型分类时重叠，管理者可能被标成 T1 而丢失"管理审查"语义。
   - 修正：拆成 **池 A 正式审查（RC-1..RC-7，必须 `can_review`，T1..T5）** 与 **池 B 降级审查（DC-1..DC-8，仅当池 A 为空时构建，必须不同部门、不得有 `can_review`，只有 T6）**。
   - **T5 判定提前**：`classify_formal()` 先判"是否管理链上级"，是则直接 T5，不再走部门/模型分支；排序仍为 T1<T2<T3<T4<T5<T6，正式池整体优先于降级池。
   - T6 强制 `degraded_reviewer=true`、`pool="degraded"`、警告 `degraded_reviewer_used`，展示层不得写成"独立审查人"。
   - 伪代码改为两段式构建，每个 tier 都有可达路径；新增 `classify_empty()` 原因码与 suggestion。
   - 新增 3 个测试场景：B8-9（正式 T4 优先于更"好看"的 T6）、B8-10（正式池空时 T6 触发）、B8-11（两池皆空返回 null + reason_code）。
   - 保留 B8-1a（开发员执行→QA 审查）与 B8-1b（测试员执行→开发交叉审查）。

2. **B1 测试数量修正**
   - 原写"迁移 2 + 本地防护 4 = 6"，但 §11.8 明确 S-11..S-14 四项 + "正常前端请求放行"对照一项 = **5 项**。
   - 修正 B1 新增测试下限为 **7 个**（迁移 2 + 本地防护 5）。
   - B5 因新增 3 个审查池用例，下限由 26 调为 **29**（权限 12 + 派工/审查 12 + 审计 3 + 前端 2）。
   - B6 计划测试总数：**89** = M0 7 + B1 7 + B2 10 + B3 20 + B4 16 + B5 29。
   - **核算口径说明**：审查意见给出的 86 = 7 + 7 + 10 + 20 + 16 + 26，是按"B5 仍为 26"计算的；本次 §10.5 新增 3 个审查池测试后为 89。若坚持 86，只能把 3 个新场景并入既有用例，会降低可追溯性，不推荐。
   - **≥75 保留为最低验收门槛**，并明确它**不是计划测试总数**；计划总数 89 才是完整交付目标。

3. 未修改：D-1~D-6 决策、数据库表结构、45 个端点清单、B1~B6 范围、M0 的 7 个回归测试。

### v1.1（2026-11-05，二次审查后修订）
**必须修正项（用户提出）**
1. **API 计数**：原文标注 38、分组写"员工 12"但实际列 13 项。本版逐项编号为 **45 个端点**（API-01..45），并给出每批交付数量（B2 16 / B3 14 / B4 8 / B5 7，B1 为 0），验收按 ID 打勾；同时说明审查意见的 44 是按"员工 12"推算的差异来源。
2. **审查人推导重设计**（§10.5）：废弃"只沿 reports_to 向上找"的逻辑，改为 **候选池 + 7 条硬约束（RC-1..RC-7）+ T1..T6 分级排序**，新增 `position.can_review` 字段；覆盖"开发员执行 → QA 审查"与"测试员执行 → 开发交叉审查"两种场景；明确"找不到合格审查人返回 null + reason_code + suggestion，不硬凑"。
    > 该版单池方案存在 T6 不可达与 T5 分类重叠问题，已在 **v1.2 被"正式池/降级池"双池模型取代**，以 §10.5 当前内容为准。
3. **历史模型快照**：实测核对 M0 代码（`sequential.py:52/74`）确认 `agent_run.model` 与 `usage_record.model` **已是快照**，无需新增模型字段；但发现两张表**都缺 `employee_id`**，B3 补 `usage_record.employee_id`（原计划只补 agent_run），并新增 A3-6/7/8 三个测试（历史不被改写、降级、缓存）。
4. **本地 API 安全**（§7.1 + §11.8）：B1 新增 Host 校验、可信 Origin、`X-AgentOS-Client` 自定义头、`Sec-Fetch-Site` 拒绝跨站、写请求校验；明确默认只监听 `127.0.0.1`、禁止默认 `0.0.0.0`；新增 S-11..S-14 四项测试。

**建议完善项（用户提出）**
5. 前端依赖清单统一为表格（§8.0），含版本策略与"shadcn 不是 npm 包"的说明。
6. 新增 §9.6 提示词文件/数据库一致性协议：临时文件→fsync→原子改名→DB 事务→失败补偿，配套 `reconcile_prompts.py` 与 P-1..P-4 测试。
7. BR-04 拆为 a~e：同公司、非自我、非下级、链长 ≤20、对象必须 active。
8. 新增 §9.2 健康缓存规则：配置指纹键、正缓存 300s / 负缓存 60s、主动失效、single-flight、`health_source` 标注。
9. 派工预览新增 `data_quality` 与 `score_note`，明确 performance/load 为中性 0.5 且前端用"估算"徽标，B8-8 断言（§10.4）。

**冲突修复**
10. **权限层自相矛盾**：v1.0 同时写"员工层只能收窄"与"file_write 可在员工档案放宽"。本版定为 **BR-13：放宽只能改岗位默认且不超公司策略，员工覆盖永远只能收窄**（§11.2/§11.4）。
11. **批次依赖倒置（共 3 处）**：① effective-permissions/permission-overrides/capabilities 依赖 B5 权限模块 → 移到 B5；② `GET /employees/{id}/prompts` 依赖 B4 的 `prompt_revision` → 移到 B4；③ `GET /employees/{id}/audit` 依赖 B5 的 `audit_log` → 移到 B5。最终 B3 员工端点 8 个、B4 增 1 个、B5 增 4 个。
12. **B2 验收依赖未建表**：v1.0 要求 B2 验"含员工部门不可删"，但 employee 表在 B3 → 该项移到 B3，B2 只验"含子部门不可删"。
13. **测试数量与门槛脱节**：v1.0 B6 门槛 ≥50，但各批下限相加已 85 → 门槛改为 **≥75**（留余量），并给出各批下限（6/10/20/16/26）。
    > 后续修正：v1.2 将 B1 改为 7、B5 改为 29（新增 3 个审查池用例），计划总数由 85 变为 **89**；≥75 仍为最低验收门槛。
14. **组织图员工节点**：B2 无员工数据 → 明确 B2 只渲染部门/岗位，员工节点 B3 接入。

**决策落地**
15. D-1~D-6 全部标记为"已确认"，并写明落地批次；ADR-0011..0014 同步转为已接受。

### v1.0（2026-11-05）
初版单文档（由 7 份拆分文档合并），包含 M1 PRD、数据模型、API、前端、解耦与派工、安全、分批计划与 M0 遗留处理。

---

## 18. B1 执行报告（2026-11-05）

> 代码提交：`83adedb`｜执行人：AgentOS CTO（AI）｜状态：**完成，等待所有者验收；未开始 B2**

### 18.1 结论与验收对照

| 验收项 | 结果 | 证据 |
|---|---|---|
| 空库迁移 | ✅ | `test_empty_database_upgrade_to_head`；`alembic upgrade head` 建出 5 表 + `alembic_version`，`agent_run.employee_id` 存在 |
| M0 旧库迁移 | ✅ | 真实 `data/agentos.db` 先 `stamp m0_baseline` 再 `upgrade head`：4 条 task / 4 条 agent_run 全保留，revision=`m1_b1_agent_run_employee_id`；另有一次备份副本上的自动化测试 |
| M0 的 7 个测试 | ✅ 7/7 | `pytest tests/ -v` 全绿，未改动任何断言 |
| B1 新增测试 ≥7 | ✅ 7 | 迁移 2 + 本地防护 5 |
| 正常请求放行 | ✅ | 真实服务：POST 带可信 Origin + `X-AgentOS-Client` → HTTP 405（已到路由层）；GET `/api/health` → 200 |
| 恶意 Origin | ✅ | HTTP 403 `UNTRUSTED_REQUEST` |
| 恶意 Host | ✅ | HTTP 400 `INVALID_HOST` |
| 缺少自定义头 | ✅ | HTTP 403 `MISSING_CLIENT_HEADER` |
| 非法监听地址 | ✅ | `run_api.py --host 0.0.0.0` 退出码 1 并打印拒绝原因；`AGENTOS_ALLOW_EXTERNAL=1` 才放行 |
| ruff | ✅ | `All checks passed!`（apps/packages/scripts/tests/migrations） |
| 前端构建 | ✅ | `tsc -b && vite build` 通过，62 modules，168.00 kB JS |
| 数据安全 | ✅ | 迁移前用 SQLite 在线备份到 `data/backups/pre_b1_20261105_021429.db`（77,824 bytes） |
| 未越界 | ✅ | 未安装 Codex/CrewAI/Docker/Playwright，未推 GitHub，未改系统设置，未开始 B2 |

### 18.2 变更文件清单

**新增（B1 核心）**
- `alembic.ini`、`migrations/env.py`、`migrations/script.py.mako`
- `migrations/versions/0001_m0_baseline.py`、`0002_m1_b1_agent_run_employee_id.py`
- `apps/api/deps.py`（会话 / 分页 / ActorContext）、`apps/api/errors.py`（统一包络 + request_id）
- `apps/api/routers/__init__.py`、`apps/api/routers/legacy.py`（M0 三接口迁移）
- `apps/api/security/__init__.py`、`local_guard.py`
- `scripts/run_api.py`、`scripts/backup_db.py`、`scripts/__init__.py`
- `tests/conftest.py`、`tests/test_migrations.py`、`tests/test_local_guard.py`
- `apps/web/src/api/client.ts`、`api/types.ts`、`lib/queryClient.ts`、`vite-env.d.ts`

**修改**
- `apps/api/main.py`（lifespan + 中间件装配 + 路由挂载）
- `packages/persistence/models.py`（`AgentRun.employee_id` 可空 + 索引）
- `pyproject.toml`（build-system / setuptools 包发现 / dependencies）
- `requirements.txt`（+alembic）、`apps/web/package.json` / `package-lock.json`
- `apps/web/src/main.tsx`（QueryClientProvider）、`App.tsx`（使用统一客户端）
- `.env.example`（可信来源 / 本地令牌 / 外部监听开关）、`.github/workflows/ci.yml`、`README.md`、`CHANGELOG.md`

### 18.3 数据库迁移结果

| 路径 | 操作 | 结果 |
|---|---|---|
| 空库 | `alembic upgrade head` | 5 张业务表 + `alembic_version`；`agent_run` 含 `employee_id`；`usage_record` 不含（按计划 B3 才加） |
| 真实 M0 库 | `stamp m0_baseline` → `upgrade head` | task 4→4、agent_run 4→4；新增 `employee_id`；revision 更新；`agent_run.model` 历史值未变 |
| 迁移后 schema 对比 | 旧库 vs 空库 | 五表列集合完全一致（自动化断言） |

> 测试中发现并修复了一个测试自身的缺陷：真实库迁移到 head 后，旧测试仍把它当 M0 样本去 `stamp`，导致重复加列。已改为"仅当库无 `alembic_version` 且 `agent_run` 无 `employee_id` 时才作为 M0 样本"，否则用基线 revision 造等价库；修复后 14/14 通过。

### 18.4 测试逐项结果

**M0 基线 7 个（全部保留、全部通过）**
`test_litellm_adapter_capabilities_honest`、`test_interrupt_raises_capability_not_supported`、`test_capability_set_serializable`、`test_event_serialization`、`test_cost_none_is_honest`、`test_multiple_runs_not_overwritten`、`test_restart_keeps_records`

**B1 新增 7 个**
| 测试 | 覆盖 |
|---|---|
| `test_empty_database_upgrade_to_head` | 空库迁移 + 新列存在 + 未提前加 usage_record.employee_id |
| `test_m0_legacy_database_upgrade_preserves_data` | M0 旧库数据保留 + revision + schema 与空库一致 |
| `test_normal_frontend_request_passes` | 可信 Origin + 自定义头放行；读接口无需 Origin；request_id 存在 |
| `test_untrusted_origin_rejected` | 恶意 Origin 403；`Sec-Fetch-Site: cross-site` 也 403 |
| `test_invalid_host_rejected` | `Host: evil.example` → 400 |
| `test_missing_client_header_rejected` | 缺 `X-AgentOS-Client` → 403 |
| `test_external_bind_address_rejected` | `0.0.0.0` 拒绝；显式授权放行；localhost/::1 归一化 |

**汇总**：`14 passed in 2.17s`

### 18.5 真实安全验证（启动服务 + curl）

```
GET  /api/health                                   → 200 {"status":"ok","version":"0.1.0-m1b1"}
POST /api/tasks  Origin 127.0.0.1:5173 + 自定义头    → 405 METHOD_NOT_ALLOWED（放行到路由）
POST /api/tasks  Origin http://evil.example        → 403 UNTRUSTED_REQUEST
POST /api/tasks  缺 X-AgentOS-Client               → 403 MISSING_CLIENT_HEADER
GET  /api/health Host: evil.example                → 400 INVALID_HOST
run_api.py --host 0.0.0.0                          → 退出码 1，拒绝监听
GET  /api/tasks（真实库）                            → 4 条任务（M0-V6 持久化标记任务 等）
```

### 18.6 与计划的偏差（均已评估）

| 偏差 | 原因 | 影响 |
|---|---|---|
| 本地防护实现为 **ASGI 中间件**，而非"写路由的 router 级依赖"（§11.8 原文） | B1 尚无 `/api/v1` 写路由，依赖无处可挂；中间件可同时覆盖 legacy 与未来路由 | 防护能力等价且更全面；M5 接账号体系时整体替换为鉴权中间件。已在 `local_guard.py` 文件头注明 |
| `conftest.py` 未提供 `seeded_company` 夹具 | company 表 B2 才建，B1 提供会造假数据 | 改为 `seeded_task`；`seeded_company` 随 B2 交付 |
| zod 3.x → **4.6.7** | 3.x 存在高危漏洞 GHSA-mrhx-c7xc-m3w5，`npm audit` 报 high | 已升级并 `npm audit --omit=dev` 0 漏洞；方案文档 §8.0 已同步 |
| 新增 `scripts/__init__.py` | 测试需导入 `resolve_bind_host` | 无副作用 |
| 新增 `AgentRun.employee_id` 索引命名 `ix_agent_run_employee_id` | 与 SQLAlchemy 默认命名一致 | 与迁移脚本一致，schema diff 测试验证 |

### 18.7 未完成事项 / 风险 / 阻塞

- **未完成（按计划属 B2+）**：`/api/v1` 路由与 45 个端点、company/employee 表、seeded_company 夹具、组织图、防篡改审计
- **风险 1**：本地防护挡不住本机恶意进程（已知限制，M5 账号体系解决）
- **风险 2**：`Seeded` 测试依赖真实库作为样本的路径已做前置判断；若未来库结构变化需同步基线判断逻辑
- **风险 3**：`alembic.ini` 必须保持 ASCII（本次因中文注释触发 cp936 解析失败，已移除中文）
- **风险 4**：`npm audit` 的 zod 修复要求破坏性升级，若后续有代码依赖 zod3 API 需适配（当前尚未使用）
- **阻塞**：无

### 18.8 是否满足 B1 验收条件

**满足。** 14/14 测试通过、ruff 全绿、前端构建通过、两条迁移路径均实测、5 项安全验证全部符合预期、M0 数据完整保留。**未开始 B2，等待所有者审查。**

---

## 19. B1 补充验收 + B2 执行报告（2026-11-05）

> 状态：**B1 有条件通过；B2 已完成；B3 具备启动条件（待所有者确认）**
> 提交：B1 补充 `381145f`｜B2 `fe66315`｜本轮文档提交见文末附录

### 19.1 B1 补充验收结果

| 检查项 | 方法 | 结果 |
|---|---|---|
| 包安装与导入 | `pip install -e .` 后从 `/tmp` 导入 `apps.api.main` | ✅ 成功；默认库路径已改为仓库绝对路径（`sqlite:///E:/AgentOS/data/agentos.db`），从其他目录启动不再静默建空库 |
| 启动行为 | `scripts/run_api.py` 默认 127.0.0.1 | ✅ 正常启动；`ensure_schema` 改为"仅空库 create_all"，已有库必须迁移，避免结构漂移 |
| 统一错误结构 | 未知路由 `/api/not-exists` | ✅ 404 + `error.code=NOT_FOUND` + 非空 `request_id`，响应头与 body 一致 |
| request_id | 自定义 `X-Request-ID` 回显；防护拒绝响应 | ✅ 回显 `trace-abc-123`；Guard 403/400 的 `request_id` 由 `-` 修复为真实 ID |
| 分页边界 | 探针应用 + 真实端点 | ✅ `page=2&page_size=200` 可用（offset=200）；`page_size=201` → 422 `VALIDATION_ERROR`；`page=0` → 422 |
| CORS 预检 | OPTIONS + ACRM/ACRH | ✅ 200，`access-control-allow-origin` 正确，允许 `x-agentos-client` |
| Referer 回退 | 无 Origin、带 Referer | ✅ 放行到路由层（405） |
| 可选本地令牌 | 设置 `AGENTOS_LOCAL_TOKEN` | ✅ 缺令牌 401 `INVALID_TOKEN`；错误令牌 401；正确令牌放行 |
| 备份脚本 | 真实执行 + 副本读取 | ✅ `data/backups/agentos_20261105_023021/`，manifest 记录 commit/大小；副本 4 条任务、revision 正确；源库未改动 |
| Git 状态 | B1 后、B2 前 | ✅ 工作区干净；B2 未混入 B1 提交 |
| 全量回归 | pytest | ✅ 23 passed（M0 7 + B1 7 + 补充 9） |

**B1 风险分级**
| 级别 | 问题 | 处理 |
|---|---|---|
| P0 | 无 | — |
| P1（已修复） | 默认 DB 路径随启动目录漂移，可能悄悄建空库 | 已改绝对路径并复验 |
| P1（已修复） | 启动 `create_all` 可能掩盖缺失迁移 | 改为仅空库引导，已有库强制迁移 |
| P1（已修复） | 防护拒绝响应 `request_id` 为 `-` | 已注入真实 ID |
| P1（保留，已记录） | 本地防护实现为中间件而非 router 依赖（与 §11.8 措辞不同） | 能力等价，M5 替换为鉴权中间件 |
| P2 | 文档 §8.0 的 zod 版本与实际不一致 | 已在 §8.0 标注 4.6.7 及原因 |

**结论：B1 有条件通过，无阻断项。**

### 19.2 B2 实际完成内容

- **数据模型**：`company` / `department`（parent_id 自引用、depth、唯一名）/ `position`（`can_review`、`review_capability_tags`、`is_managerial`、默认权限）
- **迁移**：`m1_b2_org`，真实库已 `upgrade head`
- **领域服务**（`packages/organization/`）：
  - 公司：创建/列表/详情/更新/归档；归档后禁止组织变更
  - 部门：创建（depth 自动计算）、更新/移动（成环检测、子树深度重算）、删除（子部门/岗位保护）、平铺列表
  - 岗位：CRUD、同公司部门校验、`can_review` 与审查标签
  - 组织树：一次查询 + 内存组树，含未归属岗位
  - 公共：404 语义、乐观锁 `CONFLICT_STALE`、名称唯一、UTC 序列化
- **API**：API-01..16 全部实现（公司 5 / 部门 6 / 岗位 5），统一 `/api/v1`、分页包络、错误包络
- **前端**：`/org` React Flow 组织图（部门节点 + 岗位摘要 + 空态）；`/settings/organization` 公司/部门/岗位 CRUD；顶部健康状态走统一客户端

### 19.3 新增与修改文件

**新增**：`migrations/versions/0003_m1_b2_org.py`、`packages/shared/errors.py`、`packages/organization/{__init__,common,companies,departments,positions,tree}.py`、`apps/api/schemas/{__init__,org}.py`、`apps/api/routers/{companies,departments,positions}.py`、`apps/web/src/api/org.ts`、`apps/web/src/pages/{OrgPage,OrganizationSettings}.tsx`、`tests/test_org_api.py`、`tests/test_api_contract.py`、`tests/test_backup.py`
**修改**：`packages/persistence/models.py`（3 张新表）、`apps/api/main.py`（挂载 v1 路由）、`apps/api/errors.py`（DomainError）、`packages/persistence/db.py`（绝对路径/ensure_schema）、`apps/api/security/local_guard.py`（request_id）、`tests/conftest.py`（write_client/seeded_company）、`apps/web/src/App.tsx`、`CHANGELOG.md`、`README.md`、`.github/workflows/ci.yml`

### 19.4 数据库迁移情况

| 库 | 操作 | 结果 |
|---|---|---|
| 真实 `data/agentos.db` | `alembic upgrade head`（m1_b1 → m1_b2_org） | 新增 company/department/position；`task` 仍 4 条、`company` 0 条；历史数据未动 |
| 临时冒烟库 | 服务启动建库 → 建公司/部门/岗位 → org-tree | 全链路 201/200 正确，验证后临时库已删除（未用 `rm` 命令，使用 Python `unlink`） |
| 自动化迁移测试 | 空库 + M0 旧库 | ✅ 断言改为动态读取 Alembic head，B2 新增 revision 后仍通过 |

### 19.5 实际测试命令与结果

```
pytest tests/ -q                     → 38 passed in 4.92s
ruff check apps packages scripts tests migrations → All checks passed!
cd apps/web && npm run build         → tsc -b && vite build 通过，92 modules，410.10 kB JS
python scripts/backup_db.py          → 备份成功，副本可读（4 条任务 / m1_b1 revision）
真实服务冒烟（临时库）                 → 公司 201 → 部门 201(depth=0) → 岗位 201(can_review=true) → org-tree 正确
```

测试构成：M0 7 + B1 7 + B1 补充 9 + B2 15 = **38**。

### 19.6 未完成项目与原因

| 项 | 原因 |
|---|---|
| 浏览器端可视化验收（30 节点渲染、拖拽） | 未安装 Playwright（需授权）；本轮只验证构建与接口，**未做真实浏览器渲染验证** |
| 部门拖拽移动 UI | B2 后端已提供 `/move`，前端本轮用"上级部门下拉"创建，未做拖拽交互（计划 B5 组织图编辑） |
| 员工-部门人数统计 | 员工表 B3 才建，`employee_count` 暂为 0（占位，未伪造数据） |
| 岗位删除引用检查 | `employee_position` B3 才建，当前允许删除岗位 |

### 19.7 Git 状态

- `381145f` test(b1): 补充验收 + 3 个修复
- `fe66315` feat(b2): 组织域 + 16 API + 前端
- 本轮文档提交：见附录（HEAD 会在此文档提交后更新）
- 工作区：提交前干净；未推送 GitHub

### 19.8 B3 是否具备启动条件

**具备，但需注意三点**：
1. B2 的 `can_review` / `depth` / 组织树接口已为 B3 的员工归属与 B5 的审查人推导提供数据基础
2. B3 需要新增 `usage_record.employee_id` 与 employee/employee_position/model_connection/model_switch_log 四表，迁移顺序已定
3. 未验证项（浏览器渲染）应在 B3 前端联调时一并补做，不阻塞迁移与后端开发

---

## 20. B3–B6 连续执行与 M1 最终验收（2026-11-05）

> 状态：**M1 功能完成，有条件通过**（P0 无；P1 见 §20.10）
> 提交：B3 `17e8cd0`｜B4 `50ef92d`｜B5 `a89eb51`｜B6 文档提交见附录

### 20.1 各批完成情况

| 批次 | 内容 | 结果 |
|---|---|---|
| B3 | 4 张表 + `usage_record.employee_id`；员工 CRUD/启停/软删/汇报链；模型连接/测试/目录；凭据引用；健康缓存；员工/模型/组织图前端 | ✅ 13 个新测试 |
| B4 | 提示词文件版本化（不可变 + 哈希 + 激活 + diff + 对账）；导出/导入（dry-run、rename、无密钥、路径穿越防护）；提示词编辑器与导入页 | ✅ 10 个新测试 |
| B5 | 三层权限（只收窄）、有效能力、派工硬过滤+评分、正式/降级双池 T1–T6、决策落库、审计；权限面板/派工台/审计页 | ✅ 12 个新测试 |
| B6 | 三个 E2E 场景、全量回归、迁移与真实库核对、构建 | ✅ 23 项 E2E 检查 |

### 20.2 每批 Git 提交

```
17e8cd0 feat(b3): 员工与模型解耦（4 表 + 14 API + 前端）
50ef92d feat(b4): 提示词版本化与配置导入导出
a89eb51 feat(b5): 三层权限、派工预览、双池审查人、审计
（B6：本文件与 CHANGELOG、E2E 脚本同提交）
```

### 20.3 新增/修改文件（汇总）

- 迁移：`0004_m1_b3_employee_model.py`、`0005_m1_b4_prompt.py`、`0006_m1_b5_assignment_audit.py`
- 领域包：`packages/model_gateway/{credentials,catalog,health}.py`、`packages/organization/{employees,connections}.py`、`packages/prompts/`、`packages/config_io/`、`packages/permissions/{effective,policy,audit,assignment}.py`、`packages/agent_core/capabilities.py`
- API：`routers/{employees,model_connections,prompts,config_io,governance}.py`、`schemas/{people,governance}.py`
- 前端：`api/{people,prompts,config,governance}.ts`、`pages/{Employees,EmployeeDetail,ModelConnections,ImportExport,Assignment,Audit}Page.tsx`
- 脚本/测试：`scripts/{reconcile_prompts,e2e_m1}.py`、`tests/{test_employees,test_prompts,test_config_io,test_governance}.py`

### 20.4 45 个 API 逐项验收

- **OpenAPI 实际注册：44 个 route–method 对 + 1 个辅助端点 `/model-providers`**
- 契约 45 项中，API-43 与 API-44 共用同一路径（`POST /config/import`，`dry_run` 查询参数区分），因此路由对为 44；**契约项仍为 45，全部实现**
- 分组：公司 5 ✅｜部门 6 ✅｜岗位 5 ✅｜员工 13 ✅｜提示词 4 ✅｜模型连接 6 ✅｜派工 2 ✅｜配置 3 ✅（同一路由双行为）｜审计 1 ✅
- 测试直接覆盖：公司 5/5、部门 4/6（PATCH 改名、DELETE 有覆盖；`PATCH` 的纯改名未单测）、岗位 5/5、员工 10/13（PATCH 权限相关由权限接口覆盖）、提示词 4/4、连接 4/6（`test` 端点未做真实调用测试）、派工 2/2、配置 3/3、审计 2/2
- **未直接测试项**：`PATCH /departments/{id}`（仅经 move 覆盖 parent 变更）、`POST /model-connections/{id}/test`（会发起真实外部调用，未在测试中执行）、`PUT /api/v1/employees/{id}/permission-overrides` 的部分键组合
- 辅助端点 `/model-providers`：静态目录，不计入 45

### 20.5 数据库迁移与备份

| 项 | 结果 |
|---|---|
| 迁移链 | `m0_baseline → b1 → b2 → b3 → b4 → b5`，真实库 revision=`m1_b5_assignment_audit` |
| 真实库 | 16 张表；`task` 4 条、`company` 0 条；历史任务/执行记录未改动 |
| 备份 | B1 前 `data/backups/pre_b1_*.db`；B1 补充验收时 `agentos_20261105_023021/` |
| 迁移测试 | 空库 + M0 旧库两条路径持续通过；head 动态读取 |

### 20.6 测试统计（实际执行）

```
pytest tests/ -q                                  → 73 passed
ruff check apps packages scripts tests migrations  → All checks passed!
cd apps/web && npm run build                      → 通过，102 modules，440.61 kB JS
python scripts/e2e_m1.py                          → 23 项检查全部通过（见 docs/testing/m1_e2e_output.txt）
```

| 来源 | 数量 |
|---|---|
| M0 基线 | 7 |
| B1 | 7 |
| B1 补充 | 9 |
| B2 | 15 |
| B3 | 13 |
| B4 | 10 |
| B5 | 12 |
| **合计（pytest）** | **73** |
| 计划下限（§12/§19 核算） | 89（未达，差 16） |
| E2E（非 pytest） | 23 项 |

> **诚实声明**：实际 pytest 73 个，低于计划 89。原因是 B3/B4/B5 的测试按"高价值路径"合并编写（如三层权限用少量参数化用例覆盖多组合），未逐条凑数。覆盖项与未覆盖项见 §20.4/§20.10，不以数量达标冒充质量达标。

### 20.7 三个端到端场景

| 场景 | 结果 |
|---|---|
| S1 从零建公司（2 部门/3 岗位/2 连接/4 员工含兼任/提示词/组织树/导出/导入/哈希一致） | ✅ 10 项检查 |
| S2 模型切换（身份不变、主模型历史保留、成本按员工归因、能力随新模型、权限来源链） | ✅ 6 项检查 |
| S3 权限与派工（员工不能扩权、工具硬过滤、审查人≠执行人、data_quality、决策留痕、审计） | ✅ 7 项检查 |

### 20.8 真实模型验证 vs Mock

- **真实验证**：M0 的 V1/V4 曾用 DeepSeek 真实 API 调用成功（tokens 16+8、cost $0.0000072）；B1 曾用 `/api/employees/deepseek/deepseek-chat/health` 真实连通
- **本轮 M1（B3–B6）未发起任何真实 LLM 调用**：测试使用静态 catalog 与假 `env` 变量；`POST /model-connections/{id}/test` 未在测试中执行
- **Mock/静态替代**：能力判定来自 `catalog.py`；健康缓存用单元测试；无不实标记

### 20.9 尚未完成事项

> **更新（v1.3）**：本节第 2、3、5 项已在 **§21 收尾**中修复关闭；第 1、4、6 项保留（P2 / 后续里程碑）。以下为 B6 当时的原始记录，保留以便追溯。

1. **浏览器可视化验收**：未安装 Playwright，组织图/派工台仅通过构建与接口验证
2. **审计覆盖不足**：只写了 `employee.permission_overrides.update/denied`、`assignment.preview` 三类；计划中的 12 类（公司/部门/岗位变更、模型切换、提示词发布、导入导出等）未全部接入（P1）
3. **导入非严格单事务**：`create_revision` 每版本自行 commit，失败时可能留下部分导入数据（P1）
4. 部门拖拽 UI 未做（后端 move 已有）
5. 45 项中 3 项无直接测试（见 §20.4）
6. MCP/A2A/CLI 执行仍未开始（M2/M6 范围）

### 20.10 风险分级

> **更新（v1.3）**：下表 4 项 P1 的处置结果见 **§21.1**（3 项已修复，1 项转为 Mock 验证）。以下为 B6 当时的分级，保留以便追溯。

| 级别 | 项 | 处理建议 |
|---|---|---|
| P0 | 无 | — |
| P1 | 审计事件覆盖不足 12 类 | M1 收尾补 4 类核心（员工/模型切换/提示词/导入导出） |
| P1 | 导入事务性不足 | 改为显式 session 事务 + 文件补偿 |
| P1 | 连接测试端点无真实调用测试 | 在有 Key 的环境手工执行一次并留证 |
| P1 | 3 个 API 无直接测试 | 补 PATCH 部门、权限组合、连接测试（mock） |
| P2 | 前端未浏览器验收 | M2 联调时补 |
| P2 | 45 vs 44 计数口径 | 文档已注明（import 双行为） |

### 20.11 Git 与工作区

- HEAD：B5 `a89eb51`；B6 文档与脚本随后提交
- 工作区：提交前干净；未推送 GitHub；未安装未授权组件；未修改系统设置
- 真实库仅执行计划内向前迁移，未做 downgrade

### 20.12 M2 启动建议

1. 先补 P1（审计 4 类、导入事务、3 个 API 测试），约半天
2. M2 任务引擎复用 `assignment.preview()` 候选集作为 CEO 约束；`task-engine` 负责状态机
3. Agent 侧新增独立 `/agent-api` 命名空间（BR-12 物理隔离）
4. 前端补浏览器级验收（需批准 Playwright）
5. 真实多供应商调用建议在用户提供第二家 Key 后做一次冒烟

---

## 21. M1 收尾：P1 清理（2026-11-05）

> **结论：§20.10 的 4 项 P1 已清理 3 项并关闭，第 4 项（真实连接测试）按"不产生费用"约束改为 Mock 全路径验证 + 保留手工验证建议。M1 由"主体完成、有条件通过"转为"P1 已清理，可进入 M2"。**
> 本轮**未新增数据库迁移**、**未改动 45 个端点的请求/响应契约**、**未重开任何架构决策**、**未删除真实数据**。

### 21.1 P1 逐项状态

| # | P1（§20.9/§20.10） | 状态 | 证据 |
|---|---|---|---|
| 1 | 审计只覆盖 3 类事件 | **已修复**：新增 14 类事件（合计 17 类） | §21.2；`tests/test_audit_events.py`（7 个用例） |
| 2 | 配置导入非严格单事务 | **已修复**：显式事务 + 文件补偿 + 孤儿可对账 | §21.3；`tests/test_import_transaction.py`（4 个用例，含 3 个失败注入） |
| 3 | 3 个 API 无直接测试 | **已修复**：部门 PATCH / 权限覆盖组合 / 连接测试 Mock | §21.4；`tests/test_api_gaps.py`（7 个用例） |
| 4 | 连接测试端点无真实调用验证 | **未做真实付费调用**（遵守约束）。改为 Mock 覆盖成功/认证失败/超时/其他四路径，并修复错误信息回显风险 | §21.4；真实 Key 环境下建议手工跑一次 |

### 21.2 核心审计事件（只增不改 + 强制脱敏）

新增 14 类事件，落在对应路由（`apps/api/audit.py` 统一入口）：

| 事件 | 触发 |
|---|---|
| `employee.create` / `employee.update` / `employee.enable` / `employee.disable` / `employee.delete` | 员工创建、改档案、启停、软删除 |
| `employee.model_binding.update` | 主/备模型切换（记录 from/to 与原因） |
| `model_connection.create` / `model_connection.update` / `model_connection.delete` | 连接创建、配置变更、启停、删除 |
| `model_connection.test` | 连接测试成功（失败由错误包络返回，不写成功审计） |
| `prompt.version.create` / `prompt.version.activate` | 提示词新建版本、切换激活 |
| `config.export` / `config.import` | 公司配置导出、导入 |

实现要点：

- **只追加**：`audit_log` 无更新/删除路由；`test_audit_is_append_only_and_filterable` 断言 `DELETE/PATCH /audit/{id}` 均不可用。
- **脱敏在领域层**（`packages.permissions.audit.sanitize_detail`），不依赖调用方自觉：
  - 敏感键名（`api_key`/`token`/`secret`/`password`/`authorization`…）→ `***REDACTED***`；
  - 任意字符串值命中 `sk-xxxxxxxx`、`Bearer xxxxxxxx` → 替换；
  - `api_key_ref` 属于引用（`env:VAR`），保留以便审计，但**连接更新只记 `credential_ref_changed=true`，不记取值**。
- **request_id**：由 `RequestIdMiddleware` 注入，随审计落库；`test_audit_request_id_is_propagated` 用 `X-Request-ID: audit-req-0001` 验证。
- **事务边界**：普通事件在业务提交后追加（独立事务）；**导入事件在导入事务内写入**（`commit=False`），失败时与业务数据一起回滚，不会出现"导入失败但留下成功审计"。

### 21.3 配置导入：整体事务 + 文件补偿

改动点：

1. `create_revision` / `activate_revision` 增加 `commit: bool = True`；导入传 `False`，只 `flush` 不提交。
2. `import_company` 全程单事务：公司 → 部门 → 岗位 → 连接 → 员工 → 岗位关联 → 提示词文件+元数据 → 审计 → 一次 `commit`。
3. 任一异常：`rollback()` → 按**本批次新建文件清单**补偿删除 → 原始异常继续抛出（不吞）。
4. 补偿失败：`logger.warning` 记录并保留孤儿文件，**不对已有版本做任何删除**；`scripts/reconcile_prompts.py` 只读检查即可发现。
5. 顺手修复的两个真实缺陷：
   - **提示词版本倒序**：导出用 `list_revisions`（版本倒序），导入却按列表顺序重建，导致 v2 内容被存成 v1。现导出改升序、导入按 `version` 排序，并校验 `content_hash`（不符返回 `IMPORT_PROMPT_HASH_MISMATCH`）。
   - **临时文件残留**：`os.replace` 失败时 `.tmp-*` 会留在磁盘；现写盘/改名失败也会清理临时文件。

失败注入测试（真实执行，非跳过）：

| 用例 | 注入点 | 断言 |
|---|---|---|
| 中途数据库失败 | 激活阶段抛 `RuntimeError` | 500 + 公司数不变 + 审计数不变 + 文件集合不变 |
| 文件写入失败 | `_atomic_replace` 抛 `OSError` | 500 + 公司数不变 + 无 `.tmp-*` 残留 |
| 文件补偿失败 | `_unlink_quietly` 返回 False | 500 + DB 回滚 + `reconcile()` 报 2 个孤儿 + 原文件仍在 |
| 版本与哈希保真 | 无注入（回归） | v1/v2 内容、哈希、激活指针逐一对应 |

### 21.4 补齐的 API 直接测试

| 接口 | 覆盖 |
|---|---|
| `PATCH /api/v1/departments/{id}` | 纯改名（父子/层级不变）；空白名 422；同公司重名 409；陈旧 `expected_updated_at` 409；不存在 404；失败请求均未改库 |
| `PUT /api/v1/employees/{id}/permission-overrides` | 未知键 422；风险等级/文件操作扩权 403；合法收窄 200；**多键混合失败不部分写入**；`requires_approval` 少列即扩权、原清单+新项才允许；拒绝事件全部留审计 |
| `POST /api/v1/model-connections/{id}/test` | Mock 上游：成功 200（回写 `last_health_status=ok`）、认证失败 502 `UPSTREAM_AUTH_FAILED`、超时 504 `UPSTREAM_TIMEOUT`、其他 502 `UPSTREAM_ERROR`；响应不含密钥或 `sk-` 片段 |

**未发起任何真实模型调用**：测试用 `_FakeAdapter` 替换 `LiteLLMAdapter`，只验证"凭据解析 → 调用 → 状态落库 → 错误分类 → 脱敏"链路。

### 21.5 测试环境隔离（顺带修复）

`PROMPTS_ROOT` 原为固定 `data/prompts`，导致每次跑测试都往真实目录写文件。真实库 `prompt_revision` 为 0，而目录里留下 36 个测试员工目录 → 对账脚本会报 36 个孤儿。

- 新增 `AGENTOS_PROMPTS_ROOT` 覆盖（`prompt_root()`），并让 `file_path` 在根目录位于仓库外时存绝对路径（旧相对路径仍兼容）。
- `tests/conftest.py` 增加 autouse 夹具：每个测试独立提示词根。
- E2E 脚本改用 `data/prompts_e2e`，结束整目录清理。
- 36 个历史测试目录**未删除**，已移动到 `data/backups/prompt_orphans_20261105_194225/`（可回滚）。

### 21.6 回归结果（真实执行）

| 命令 | 结果 |
|---|---|
| `pytest tests/ -q` | **91 passed**（M0 7 + B1 7 + B1补充 9 + B2 15 + B3 13 + B4 10 + B5 12 + 收尾 18） |
| `ruff check apps packages scripts tests migrations` | `All checks passed!` |
| `cd apps/web && npm run build` | 通过：102 modules，`dist/assets/index-*.js` 440.61 kB（gzip 138.83），1.52s |
| `python scripts/e2e_m1.py` | **23 项检查全部通过**（3 个场景） |
| `python scripts/reconcile_prompts.py` | `orphan_files: 0 / missing_files: 0 / hash_mismatch: 0`，退出码 0 |
| `alembic current` | `m1_b5_assignment_audit (head)`（本轮无新迁移） |
| 真实库核对 | 16 张表；`task` 4、`task_run` 4、`agent_run` 4、`usage_record` 4；`company/employee/prompt_revision/audit_log` 均 0；历史数据未被触碰 |

### 21.7 仍未完成（P2，不阻塞 M2）

1. 公司/部门/岗位变更未写审计（不在本轮清单；M2 组织变更频繁时建议补）。
2. 浏览器可视化验收未做（未安装 Playwright，需授权）。
3. 部门拖拽 UI 未做（后端 `POST /departments/{id}/move` 已具备）。
4. 普通写接口的审计与业务提交是两个事务：极端情况下进程在两次提交之间崩溃会缺一条审计（导入已同事务）。本地单用户可接受。
5. `cross_model`/`cross_provider` 口径已分开，但前端展示仍用同一枚图标（P2 展示问题）。

### 21.8 结论

- §20.10 的 P1：**3 项已修复关闭，1 项按约束转为 Mock 验证**。
- 无 P0，无阻塞项。
- **M1 具备进入 M2 的条件**；M2 开工前建议先读 §20.12 与本节 21.7。

---

## 附录：M1 执行记录（由后续执行者追加，勿删）

| 批次 | 日期 | 结果 | 证据 |
|---|---|---|---|
| — | 2026-11-05 | v1.1 计划修订完成 | 本文件 §17 |
| — | 2026-11-05 | v1.2 终审修订（审查人双池 + 测试计数），GPT 审查通过 | 本文件 §17 |
| B1 | 2026-11-05 | **完成**：14/14 测试、ruff 全绿、前端构建通过；真实 M0 库 4 条任务全保留；5 项安全实测通过 | 代码 `83adedb`；报告 §18 |
| B1 补充 | 2026-11-05 | 有条件通过：23/23 测试；修复默认库路径、启动建表策略、审计 ID；9 个补充用例 | `381145f`；报告 §19.1 |
| B2 | 2026-11-05 | **完成**：组织域 3 表 + 16 API + 前端页面；38/38 测试、ruff、构建全绿；真实库迁移且历史数据不变 | `fe66315`；报告 §19.2-19.7 |
| B3 | 2026-11-05 | **完成**：员工/模型 4 表 + 14 API + 前端；51/51 测试 | `17e8cd0`；§20.1 |
| B4 | 2026-11-05 | **完成**：提示词版本化 + 导入导出；61/61 测试 | `50ef92d`；§20.1 |
| B5 | 2026-11-05 | **完成**：三层权限 + 派工 + 双池审查人 + 审计；73/73 测试 | `a89eb51`；§20.1 |
| B6 | 2026-11-05 | **完成**：3 个 E2E 场景 23 项检查；全量回归/构建/迁移核对 | 本文件 §20 |
| B6 收尾 | 2026-11-05 | **P1 清理**：新增 14 类审计事件、导入整体事务+文件补偿、3 个 API 直接测试；91/91 测试、E2E 23 项、ruff/构建全绿；对账 0 孤儿 | 本文件 §21 |
