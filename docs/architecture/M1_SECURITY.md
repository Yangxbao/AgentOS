# M1 安全与权限设计

> v1.0（待确认）｜2026-11-05｜承接 `SECURITY_MODEL.md` 十六条红线，落地到 M1 的组织/员工/模型域

---

## 1. 主体与能力边界

| 主体 | 凭证形式（M1） | 可调用 | 明确禁止 |
|---|---|---|---|
| 用户 user | 本地单用户，无登录（M5 引入账号） | 全部 `/api/v1` 管理接口 | — |
| 系统 system | 进程内标记 | 迁移、健康检查、审计写入 | 修改员工权限 |
| Agent agent | **M1 不发放任何 Agent 侧调用凭证** | 无任何管理 API 权限 | 全部管理接口（BR-12） |

**关键设计**：不是"Agent 调用时检查权限"，而是**物理上不存在 Agent 可调用的管理端点**。M2 引入 Agent 工具调用时，Agent 只能访问 `/agent-api/*`（只读任务上下文 + 提交结果 + 发起审批请求），该命名空间与 `/api/v1` 完全隔离，且路由层用独立依赖注入 `ActorContext(type="agent")`。

## 2. 有效权限的三层模型

```
公司策略上限 policy（不可被下层突破）
   ∩ 岗位默认 default_permissions（按岗位取并集，再与上层取交集）
   ∩ 员工覆盖 permission_profile（只允许更严）
   = 有效权限 effective
```

**逐项规则（每项独立取更严值）**：

| 权限项 | 取值域 | 收紧方向 |
|---|---|---|
| `workspace_scope` | `none < project_only < company_readonly < company_write` | 取更小 |
| `file_ops` | 集合 ⊂ {read, write, delete} | 取子集 |
| `shell` | `deny < approval_required < allow_sandbox` | 取更小 |
| `network` | `deny < allowlist < allow_all` | 取更小 |
| `max_risk_level` | `low < medium < high < critical` | 取更小 |
| `tools` | 集合（工具 ID） | 取交集 |
| `budget_usd_per_task` | 数值 | 取更小 |
| `requires_approval` | 集合（action_type） | 取并集（越多越严） |

实现：`packages/permissions/effective.py` 提供 `merge(strictest)` 纯函数，返回 `{item: {"value": v, "source": "company|position|employee", "chain": [...]}}`，前端权限面板直接消费这个结构（US-9 的"来源可见"由此保证）。

**测试要求**：至少 12 组组合用例，包含"员工试图放宽被拒"（返回 `PERMISSION_WIDEN_DENIED`）、"岗位并集后再与公司交集"、"空集合语义（= 不允许，而非不限制）"。

## 3. 密钥管理

| 环节 | 规则 |
|---|---|
| 存储 | `model_connection.api_key_ref` 只接受三种前缀：`env:<VAR>`、`dpapi:<blob_id>`、`keyring:<service>:<user>`；正则拒绝 `sk-` 开头的疑似明文（BR-11） |
| 解析 | 运行时由 `packages/model_gateway/credentials.py` 解析为内存值，随用随取，不缓存到对象属性 |
| 传输 | 任何 API 响应只返回 `api_key_ref` 与 `has_credential: true/false`，永不回显值 |
| 日志 | 统一脱敏过滤器：`sk-[A-Za-z0-9]{8,}`、`Bearer\s+\S+`、`(?i)api[_-]?key\s*[:=]\s*\S+` → `***` |
| 导出 | 导出包只含 `api_key_ref`，不含值；导入时若目标环境无该变量，连接标记 `credential_missing`（不阻断导入） |
| 连接测试 | 只返回 `ok/latency/error_code`，错误消息经脱敏后才返回 |

Windows 本地默认用 `env:`（M0 已验证可行）；`dpapi:` 作为可选增强（M5 前不强制实现，但接口预留）。

## 4. 审批策略（M1 建立表，M2 执行）

`packages/permissions/policy.py` 维护 action_type × risk_level → 决策：

| action_type | 默认风险 | 决策 |
|---|---|---|
| `file_read`（工作区内） | low | allow |
| `file_write`（工作区内） | medium | approval（可在员工权限档案中放宽为 allow，但不可超过公司策略） |
| `file_delete` | high | approval（不可放宽） |
| `shell_exec` | high | approval（黑名单命令直接 deny，永不询问） |
| `network_upload` | high | approval |
| `system_config` / `software_install` / `service_deploy` / `code_publish` | critical | approval + 二次确认（M1 仅登记策略，M2 接入执行） |

不可配置的硬 deny 清单（M1 写入常量，测试覆盖）：`Set-MpPreference`、`netsh advfirewall`、`Add-MpPreference -ExclusionPath`、`setx` 修改系统变量、注册表 `HKLM\...\Environment` 写入、`bcdedit`、`vssadmin delete`。

## 5. 审计事件清单（M1 必须落库）

| action | 触发点 | 关键字段 |
|---|---|---|
| `company.create/update/archive` | 公司接口 | policy diff |
| `department.create/update/move/delete` | 部门接口 | old/new parent |
| `position.create/update/delete` | 岗位接口 | default_permissions diff |
| `employee.create/update/enable/disable/delete` | 员工接口 | 变更字段（脱敏） |
| `employee.model_binding.update` | 切换模型 | from/to + reason |
| `employee.permission_overrides.update` | 权限变更 | 每项 before/after + 拒绝记录 |
| `prompt.publish/activate` | 提示词接口 | version + hash |
| `model_connection.create/update/delete/test` | 连接接口 | 仅 ref 与结果，无密钥 |
| `config.export/import` | 导入导出 | 计数 + 冲突策略 |
| `assignment.preview` | 派工预览 | decision_id + 候选数 |

审计表**只增不改**：无 UPDATE/DELETE 路由；ORM 层用事件监听阻止 update（防御性）。

## 6. 越权测试清单（M1 必须全绿）

| # | 攻击面 | 期望 |
|---|---|---|
| S-1 | 用 `POST /api/v1/employees/{id}/permission-overrides` 传入比岗位默认更宽的项 | 403 `PERMISSION_WIDEN_DENIED`，且审计记录被拒绝 |
| S-2 | 员工通过工具调用尝试访问 `/api/v1/*` | 路由层不存在该能力（M2 用独立命名空间 + 集成测试验证） |
| S-3 | 创建连接时 `api_key_ref` 填 `sk-xxxx` 明文 | 422 拒绝，提示使用 `env:` |
| S-4 | 连接测试失败，检查响应与日志 | 无密钥片段（用正则断言响应体与日志文件） |
| S-5 | 导出公司配置 | zip 内所有文件 grep 不到 `sk-`/`Bearer` |
| S-6 | 拖拽部门成环 | 409，数据库无变化 |
| S-7 | 删除有员工的部门 | 409，员工记录不变 |
| S-8 | 并发修改同一员工（stale updated_at） | 409 `CONFLICT_STALE`，后写不覆盖 |
| S-9 | 导入恶意 zip（路径穿越 `../../`） | 拒绝并报错，不写盘 |
| S-10 | 提示词文件被手工篡改 | 加载失败 `BR_PROMPT_HASH_MISMATCH`，不静默降级 |

## 7. 已知限制（诚实声明）

1. 本地单用户无认证，任何能访问本机 8000 端口的进程都能调管理接口——M1 只监听 `127.0.0.1` 缓解，账号体系在 M5
2. `env:` 密钥引用依赖用户正确设置环境变量；M1 不做操作系统级密钥库强制
3. 权限模型是"能力/范围"级别，不是行级 ACL；工作空间级细粒度授权在 M2 随 workspace 表落地
4. 审计防篡改靠应用层约束，本地 SQLite 文件仍可被用户直接修改（本地单用户场景可接受）
