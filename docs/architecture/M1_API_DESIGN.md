# M1 API 接口设计

> v1.0（待确认）｜2026-11-05｜框架：FastAPI（沿用 M0）
> 统一前缀 `/api/v1`；`/api/health` 保留兼容。所有写操作需要 `ActorContext`（M1 固定为本地用户，见 M1_SECURITY.md）

---

## 1. 通用约定

### 1.1 响应包络
```json
// 成功（单对象）：直接返回对象
{ "id": "...", "name": "..." }

// 成功（列表）：分页包络
{ "items": [...], "total": 42, "page": 1, "page_size": 20 }

// 失败：统一错误
{ "error": { "code": "BR_DEPARTMENT_HAS_EMPLOYEES", "message": "部门下仍有 3 名员工，请先迁移", "detail": {"employee_ids": ["..."]}, "request_id": "req_..." } }
```

### 1.2 约定细节
| 项 | 约定 |
|---|---|
| 分页 | `?page=1&page_size=20`（page_size ≤ 200） |
| 排序 | `?sort=name` / `?sort=-created_at` |
| 过滤 | 显式白名单参数，禁止任意字段透传 |
| 并发 | 写操作请求体带 `expected_updated_at`；不匹配返回 409 `CONFLICT_STALE` |
| 幂等 | 创建接口支持 `Idempotency-Key` 头（重复提交返回同一资源） |
| 时间 | 全部 ISO-8601 带时区 |
| 404 语义 | 资源不存在与"无权限"统一 404，避免探测（M6 多租户时重要） |
| 请求追踪 | 每个请求生成 `request_id`，错误与审计共用 |

### 1.3 错误码（M1 全集，节选高频）
| code | HTTP | 场景 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Pydantic 校验失败 |
| `BR_DEPARTMENT_CYCLE` | 409 | 部门/汇报关系成环 |
| `BR_DEPARTMENT_HAS_EMPLOYEES` | 409 | 删除非空部门 |
| `BR_MODEL_IN_USE` | 409 | 删除被引用模型连接 |
| `BR_EMPLOYEE_NAME_TAKEN` | 409 | 同公司重名员工 |
| `BR_PROMPT_HASH_MISMATCH` | 409 | 提示词文件被篡改/缺失 |
| `CONFLICT_STALE` | 409 | `expected_updated_at` 不匹配 |
| `UPSTREAM_AUTH_FAILED` | 502 | 模型连接认证失败 |
| `UPSTREAM_TIMEOUT` | 504 | 连接测试超时 |
| `PERMISSION_DENIED` | 403 | 越权（含 Agent 调管理接口） |

---

## 2. 端点清单（共 38 个）

### 2.1 公司 `/companies`（5）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/companies` | 列表（含部门数/员工数/连接数聚合） |
| POST | `/companies` | 创建 |
| GET | `/companies/{id}` | 详情（含 policy） |
| PATCH | `/companies/{id}` | 改名/描述/策略（策略变更写审计） |
| POST | `/companies/{id}/archive` | 归档（联动员工不可派单） |

### 2.2 部门 `/departments`（6）
| 方法 | 说明 |
|---|---|
| GET `/companies/{cid}/departments?flat=true` | 扁平列表（含 depth/parent_id） |
| GET `/companies/{cid}/org-tree` | **一次返回公司组织树**（部门+岗位+员工节点，供 React Flow） |
| POST `/companies/{cid}/departments` | 创建（服务端计算 depth，校验 ≤8） |
| PATCH `/departments/{id}` | 改名/改父级（成环校验）/排序 |
| DELETE `/departments/{id}` | 删除（非空拒绝，BR-05） |
| POST `/departments/{id}/move` | 拖拽专用：`{new_parent_id, new_index}` |

### 2.3 岗位 `/positions`（5）
GET/POST `/companies/{cid}/positions`；GET/PATCH/DELETE `/positions/{id}`
> `default_permissions` 变更需二次确认并写审计（影响面大）

### 2.4 员工 `/employees`（12）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/companies/{cid}/employees?status=&department_id=&q=` | 列表 |
| POST | `/companies/{cid}/employees` | 创建（可一步带 prompt 初稿） |
| GET | `/employees/{id}` | 详情（档案+主备模型+岗位+有效权限摘要） |
| PATCH | `/employees/{id}` | 改档案（不含权限/模型，分开接口） |
| POST | `/employees/{id}/enable` / `disable` | 启停（停用写审计） |
| DELETE | `/employees/{id}` | 软删除（有运行记录时提示保留历史） |
| PUT | `/employees/{id}/model-binding` | **切换主备模型**：`{primary_model_id, fallback_model_id?, reason}` |
| GET | `/employees/{id}/effective-permissions` | 三层交集计算结果 + 每项来源 |
| PUT | `/employees/{id}/permission-overrides` | 只允许收窄；越界返回 `PERMISSION_WIDEN_DENIED` |
| GET | `/employees/{id}/capabilities` | 能力矩阵（adapter 实测 ∩ 模型能力 ∩ 工具白名单） |
| GET | `/employees/{id}/prompts` | 版本列表（含 active） |
| GET | `/employees/{id}/audit?limit=` | 该员工审计摘要 |

### 2.5 提示词 `/employees/{id}/prompts`（4）
| 方法 | 说明 |
|---|---|
| POST | 新建版本：`{content, note}` → 写文件 + 落库 + 计算哈希 |
| GET `/prompts/{rev_id}` | 读内容（含 frontmatter 解析结果） |
| POST `/prompts/{rev_id}/activate` | 激活（切换 is_active 指针） |
| GET `/prompts/{rev_id}/diff?against=prev` | 与上一版差异（统一 diff 文本，前端高亮） |

### 2.6 模型连接 `/model-connections`（6）
| 方法 | 说明 |
|---|---|
| GET `/companies/{cid}/model-connections` | 列表（含 enabled、最近健康状态） |
| POST | 创建（`api_key_ref` 校验格式：`env:`/`dpapi:`/`keyring:`，拒绝疑似明文 `sk-`） |
| PATCH `/model-connections/{id}` | 改配置（换 key_ref 写审计，不回显旧值） |
| DELETE | 删除（被引用拒绝，BR-06；建议停用） |
| POST `/model-connections/{id}/test` | **真实连接测试**：最小调用，返回 `{ok, latency_ms, error_code?, error_message?}`，绝不回显密钥 |
| GET `/model-connections/{id}/models` | 可用模型列表（`model_list_source=api` 时实时拉取，`static` 时读 catalog） |

### 2.7 派工预览 `/assignments`（2）
| 方法 | 说明 |
|---|---|
| POST `/companies/{cid}/assignments/preview` | 入参 `{capabilities[], tools[], risk_level, budget_usd, notes}`；返回候选排序 + 每项因子分数 + 硬过滤原因 + 推导出的审查人 |
| GET `/assignments/{decision_id}` | 回看某次决策（审计） |

### 2.8 导入导出 `/config`（3）
| 方法 | 说明 |
|---|---|
| GET `/companies/{cid}/export` | 下载 zip（manifest + 结构 + 提示词；不含密钥） |
| POST `/config/import?dry_run=true` | 预检：将新建/覆盖/跳过明细 |
| POST `/config/import` | 执行导入（单事务；冲突策略 rename/skip/merge） |

### 2.9 审计 `/audit`（1）
GET `/audit?actor_type=&action=&from=&to=` 分页查询（只读，无删除接口）

---

## 3. 关键接口示例

### 3.1 创建员工
```http
POST /api/v1/companies/cmp_01/employees
{
  "name": "林知远", "title": "首席分析官", "department_id": "dep_research",
  "primary_model_id": "mc_deepseek_chat", "fallback_model_id": "mc_ds_reasoner",
  "personality": "严谨、先给结论再给依据、不臆测",
  "bio": "负责行业与竞品分析",
  "position_ids": ["pos_analyst"], "reports_to": "emp_ceo",
  "tools_allowed": ["web.search", "file.read"],
  "permission_profile": {"workspace_scope": "project_only", "file_ops": ["read"], "network": "allowlist"},
  "initial_prompt": "# 角色\n你是首席分析官……"
}
→ 201 { "id": "emp_01", "prompt_active_version": 1, ... }
```
服务端动作：校验 BR-01/BR-07/BR-09 → 写 employee → 写 employee_position → 生成 `v0001.md` + prompt_revision → 写 audit_log（一次事务）。

### 3.2 切换模型（解耦核心操作）
```http
PUT /api/v1/employees/emp_01/model-binding
{ "primary_model_id": "mc_claude_sonnet", "fallback_model_id": "mc_deepseek_chat", "reason": "跨模型交叉审查需要" }
→ 200 { "employee_id": "emp_01", "primary_model_id": "mc_claude_sonnet", "switched_at": "...", "history_preserved": true }
```
副作用：写 `model_switch_log`；不改动任何历史 `agent_run`；若新模型能力弱于员工已声明能力（如失去 structured_output），返回 200 但带 `warnings: ["新模型不支持 structured_output，相关任务将无法派发给该员工"]`。

### 3.3 派工预览
```http
POST /api/v1/companies/cmp_01/assignments/preview
{ "capabilities": ["coding.python", "test.unit"], "tools": ["file.write"], "risk_level": "medium", "budget_usd": 0.5 }
→ 200 {
  "decision_id": "asg_01",
  "candidates": [
    {"employee_id":"emp_dev","score":0.82,"factors":{"position_match":1.0,"review_chain_distance":0.9,"performance":0.7,"cost":0.6,"load":0.9},
     "effective_model":"deepseek/deepseek-chat","warnings":[]},
    {"employee_id":"emp_qa","score":0.61,"factors":{...},"rejected_reason":null}
  ],
  "excluded": [{"employee_id":"emp_ceo","reason":"capability_missing:tool.file.write"}],
  "reviewer": {"employee_id":"emp_qa","reason":"reports_to 链最近上级；与执行人不同模型供应商","cross_model":true}
}
```

### 3.4 连接测试
```http
POST /api/v1/model-connections/mc_01/test
→ 200 {"ok":true,"latency_ms":812,"model":"deepseek/deepseek-chat","checked_at":"..."}
→ 502 {"error":{"code":"UPSTREAM_AUTH_FAILED","message":"认证失败（401），请检查 DEEPSEEK_API_KEY","request_id":"req_..."}}
```
实现：复用 M0 `LiteLLMAdapter.health_check()`，异常分类映射到错误码；日志仅记 code+latency。

---

## 4. 分层与代码落点（避免 main.py 膨胀）

```
apps/api/
├── main.py                 # app 装配、CORS、lifespan、异常处理器
├── deps.py                 # get_db / get_actor / 分页参数
├── errors.py               # 错误码枚举 + 异常基类 + 统一 handler
├── routers/
│   ├── companies.py  departments.py  positions.py
│   ├── employees.py  prompts.py  model_connections.py
│   ├── assignments.py  config_io.py  audit.py
└── schemas/                # Pydantic v2 请求/响应模型（与 packages 领域模型分离）
packages/
├── organization/           # 领域服务：公司/部门/岗位/员工校验与变更
├── model_gateway/catalog.py# provider 元数据与静态模型目录
├── agent_core/capabilities.py # 能力交集计算
└── permissions/            # 有效权限计算/审批策略（M1 建立）
```
**约束**：router 只做参数校验与调用领域服务；业务规则不写在 router（便于 M2 复用与单测）。
