# M1 数据模型与迁移方案

> v1.0（待确认）｜2026-11-05｜基线：M0 已落地的 5 张表（task/task_run/agent_run/task_event/usage_record）
> 兼容策略：SQLite（本地）与 PostgreSQL（云端）双后端兼容，仅用通用类型；所有新表带 `owner_id`（默认 `local`）

---

## 1. 新增表总览（10 张）

| 表 | 归属批次 | 说明 |
|---|---|---|
| `company` | B2 | 公司根节点 |
| `department` | B2 | 部门树（parent_id 自引用） |
| `position` | B2 | 岗位模板（含默认权限） |
| `employee` | B3 | 员工档案（身份，与模型解耦） |
| `employee_position` | B3 | 员工-岗位多对多（1 主 + n 兼） |
| `model_connection` | B3 | 模型连接配置（只存密钥引用） |
| `model_switch_log` | B3 | 模型切换审计 |
| `prompt_revision` | B4 | 提示词版本（文件指针 + 哈希） |
| `assignment_decision` | B5 | 派工决策留痕（候选、得分、理由） |
| `audit_log` | B5 | 审计（M1 首次启用） |

已有表仅做最小变更（§4），不重建、不丢数据。

---

## 2. 表结构定义

### 2.1 company
| 列 | 类型 | 约束/说明 |
|---|---|---|
| id | VARCHAR(32) | PK |
| owner_id | VARCHAR(64) | 默认 'local'，多租户预留 |
| name | VARCHAR(120) | 非空，全局唯一（owner 内） |
| description | TEXT | |
| policy | JSON | 公司级策略：`{max_risk_level, allowed_providers[], default_budget_usd, require_cross_model_review}` |
| status | VARCHAR(16) | active / archived |
| created_at / updated_at | DATETIME(TZ) | |

### 2.2 department
| 列 | 说明 |
|---|---|
| id | PK |
| company_id | FK company.id，ON DELETE RESTRICT |
| parent_id | FK department.id，可空（根部门） |
| name / code | VARCHAR(120)/VARCHAR(40)，code 可空；同公司 name 唯一 |
| description | TEXT |
| sort_order | INT，同级排序 |
| depth | INT（0 起，写入时计算，最大 8） |
| created_at / updated_at | |

索引：`(company_id, parent_id)`、唯一 `(company_id, name)`。

### 2.3 position
| 列 | 说明 |
|---|---|
| id / company_id | |
| department_id | 可空=跨部门岗位 |
| name | 同公司唯一 |
| level | VARCHAR(24)（如 junior/mid/senior/lead/exec，自由文本但建议枚举） |
| is_managerial | BOOL，决定是否可进审批"建议链" |
| responsibilities | TEXT，职责描述（会进入派工 prompt 上下文） |
| default_permissions | JSON，岗位默认权限（见 M1_SECURITY.md 的 profile schema） |
| created_at / updated_at | |

### 2.4 employee（核心）
| 列 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(32) | PK |
| company_id | FK | 非空 |
| department_id | FK department | 可空（直属于公司） |
| name | VARCHAR(120) | 同公司内唯一（避免派工歧义） |
| avatar | VARCHAR(255) | emoji 或资源路径 |
| title | VARCHAR(120) | 对外职位名（展示用，如"首席分析官"） |
| bio / personality | TEXT | 简介 / 性格（进 prompt） |
| status | VARCHAR(16) | active / disabled / archived |
| reports_to | FK employee.id，可空 | 汇报对象（派工排序与审查链的依据） |
| primary_model_id | FK model_connection | 非空（BR-01） |
| fallback_model_id | FK model_connection，可空 | 备用模型 |
| adapter_type | VARCHAR(16) | api / cli |
| cli_profile | JSON，可空 | CLI 员工：`{cli_kind, sandbox_level, capability_snapshot}` |
| tools_allowed | JSON | 工具白名单数组；空数组=无工具 |
| permission_profile | JSON | 员工级权限覆盖（只收窄） |
| capabilities_declared | JSON | 能力声明快照（来自 Adapter.get_capabilities） |
| prompt_active_version | INT，可空 | 指向 prompt_revision.version |
| deleted_at | DATETIME，可空 | 软删除（US-4） |
| created_at / updated_at | | |

索引：`(company_id, department_id)`、`(reports_to)`、`(status)`；唯一 `(company_id, name)` where deleted_at is null（部分索引，SQLite/Postgres 均支持）。

### 2.5 employee_position
| 列 | 说明 |
|---|---|
| employee_id / position_id | 联合 PK |
| is_primary | BOOL，同员工仅一条为 true（应用层 + 唯一部分索引保证） |
| department_id | 兼任时可指定归属部门（默认取岗位部门） |
| assigned_at | DATETIME |

### 2.6 model_connection
| 列 | 说明 |
|---|---|
| id / company_id | |
| name | 展示名（如"DeepSeek 主力"） |
| provider | litellm 前缀（deepseek/anthropic/openai/gemini/openrouter/ollama/openai_compatible） |
| model | 模型标识（deepseek/deepseek-chat） |
| api_key_ref | **仅引用**：`env:DEEPSEEK_API_KEY` / `dpapi:<blob-id>` / `keyring:<service>:<user>`，禁止明文（BR-11） |
| base_url | 可空（自建/兼容端点） |
| timeout_s / max_retries | INT |
| retry_policy | JSON（退避策略） |
| model_list_source | static / api（是否支持 /models 枚举） |
| last_health_check_at / last_health_status | 最近一次连接测试结果（ok/fail 分类） |
| enabled | BOOL |
| created_at / updated_at | |

约束：同公司 `(provider, model, coalesce(base_url,''))` 唯一，避免重复配置。

### 2.7 model_switch_log
| 列 | 说明 |
|---|---|
| id / employee_id | |
| from_model_id / to_model_id | 可空一侧（首次绑定时） |
| slot | primary / fallback |
| actor_type / actor_id | user / agent / system（M1 仅 user/system） |
| reason | TEXT |
| created_at | 只增 |

### 2.8 prompt_revision
| 列 | 说明 |
|---|---|
| id / employee_id | |
| version | INT，同员工内递增，唯一 `(employee_id, version)` |
| file_path | 相对路径 `data/prompts/employees/<employee_id>/v0001.md` |
| content_hash | SHA-256（加载时校验，BR-07） |
| note | 变更说明 |
| created_by | user/system |
| is_active | BOOL（同员工仅一条 true） |
| created_at | 只增 |

### 2.9 assignment_decision
| 列 | 说明 |
|---|---|
| id | PK |
| company_id / requested_by | |
| requirement | JSON（AssignmentRequest 快照：capabilities/tools/risk/budget/notes） |
| candidates | JSON（[{employee_id, score, factors{...}, rejected_reason?}]） |
| selected_employee_id | 可空（预览时为空） |
| reviewer_employee_id | 可空（审查链推导结果） |
| algorithm_version | VARCHAR(16)（权重可追溯） |
| created_at | 只增 |

### 2.10 audit_log
| 列 | 说明 |
|---|---|
| id | PK 自增 |
| owner_id / actor_type / actor_id | user/agent/system |
| action | 如 `employee.create`、`permission.update`、`model.switch`、`prompt.publish`、`config.import` |
| target_type / target_id | |
| detail | JSON（脱敏后参数；禁止含密钥） |
| request_id | 串联同一次请求 |
| created_at | 只增；无 update/delete API |

---

## 3. 关系图

```
company 1─n department (parent_id 自引用，树)
company 1─n position ──n employee_position ──n employee
company 1─n model_connection ──n employee (primary/fallback)
employee 1─n employee (reports_to)
employee 1─n prompt_revision (is_active 唯一)
employee 1─n model_switch_log
company 1─n assignment_decision
* ─n audit_log
```

---

## 4. 对 M0 已有表的变更（最小侵入）

| 表 | 变更 | 原因 | 回填 |
|---|---|---|---|
| `agent_run` | 新增 `employee_id VARCHAR(32) NULL` + 索引 | 从 `employee_key` 字符串过渡到外键 | 保留 `employee_key` 原值；M1 新记录双写；M2 完成切换后另开 revision 移除旧列 |
| `task` / `task_run` / `task_event` / `usage_record` | 不改结构 | 避免破坏 M0 验证与测试 | — |
| `task_event.type` | 值域扩展（`assignment_preview` 等） | 无结构变更 | — |

**不回填历史数据的理由**：M0 的 `employee_key`（如 `m0-researcher`）不是真实员工；强行造员工记录会污染 M1 数据。M1 起新写入带 `employee_id`，M0 历史保持原样（可查、不参与新逻辑）。

---

## 5. 迁移方案（Alembic）

### 5.1 工具与约定
- 引入 **Alembic**（纯 Python，无系统依赖；`requirements.txt` 增加一行）
- SQLite 必须用 `render_as_batch=True`（ALTER 能力受限），迁移脚本统一 `op.batch_alter_table`
- 迁移文件命名：`<revision>_m1_bN_<slug>.py`，一个批次可含多个 revision，但**每个 revision 必须可独立 upgrade/downgrade**
- 禁止在迁移里写业务逻辑；数据回填用独立脚本 `scripts/migrations/`

### 5.2 基线策略（关键）
M0 数据库已有 5 张表但无迁移历史：
1. `alembic revision --autogenerate -m "m0 baseline"` 后**手工裁剪**为"创建 5 张 M0 表"
2. 对已存在的 M0 库执行 `alembic stamp m0_baseline`（不重建表）
3. 空库执行 `alembic upgrade head` 可完整建出 M0+M1 全部表
4. CI 增加两条测试：空库 upgrade 成功、M0 快照库 upgrade 成功

### 5.3 版本序列

| revision | 批次 | 内容 |
|---|---|---|
| `m0_baseline` | B1 | M0 五表基线（stamp 已有库） |
| `m1_b1_agent_run_employee_id` | B1 | agent_run 加列 + 索引（无回填） |
| `m1_b2_org` | B2 | company / department / position |
| `m1_b3_employee_model` | B3 | employee / employee_position / model_connection / model_switch_log |
| `m1_b4_prompt` | B4 | prompt_revision |
| `m1_b5_assignment_audit` | B5 | assignment_decision / audit_log |

### 5.4 回滚策略
- 每个 revision 提供 `downgrade()`；B3 之后的下行迁移会丢数据，**仅允许在测试库执行**，生产（本地用户库）回滚要求先导出备份（`scripts/backup_db.py`，M1 B1 交付）
- 导入操作（B4）使用单事务：失败整体回滚，不留半套数据

### 5.5 索引与性能预算
- 组织图查询：`department(company_id, parent_id)` + 一次取全公司数据（≤500 行）在内存组树，避免 N+1
- 派工预览：候选人来自一次 `employee` 联表查询（含 model_connection 健康状态），单次 < 50ms（100 员工规模基线）
- 所有列表接口强制分页（默认 20，最大 200）
