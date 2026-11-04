# AgentOS 数据库设计（初版）

> v0.1｜2026-11-05｜SQLite(WAL) 与 PostgreSQL 双后端兼容：只用通用类型（TEXT/INTEGER/REAL/BOOLEAN/JSON-as-TEXT/DateTime），不用方言特性
> 约定：所有表含 `id`(TEXT, uuid4) `created_at` `updated_at`；业务表含 `owner_id`（多租户预留，M0/M1 默认 'local'）

## 1. 实体关系总览

```
company 1─n department 1─n position
company 1─n employee n─1 model_connection（主）+ n─1 model_connection（备）
employee n─n position（employee_position，兼任）
employee n─1 employee（reports_to，上下级）
project 1─n task 1─n task_run 1─n agent_run
task_run 1─n task_event        task_run 1─n review_report
agent_run 1─n usage_record     *─n approval_request → audit_log
```

## 2. 组织域

### company
| 列 | 类型 | 说明 |
|---|---|---|
| name | TEXT | 公司名 |
| description | TEXT | |
| settings | TEXT(JSON) | 预算上限等 |

### department / position
| 列 | 说明 |
|---|---|
| company_id / name / description | 用户自由创建，无预设枚举 |
| position.extra: level(TXT), is_managerial(BOOL) | 仅展示语义，不编码权限 |

### employee（AI 员工 = 身份，与模型解耦）
| 列 | 类型 | 说明 |
|---|---|---|
| company_id | FK | |
| name / avatar / title / bio | TEXT | |
| personality | TEXT | 性格描述 |
| system_prompt | TEXT | 主提示词（可引用 prompts 表外置模板） |
| primary_model_id | FK→model_connection | 主模型 |
| fallback_model_id | FK→model_connection | 备用模型（可空） |
| tools_allowed | TEXT(JSON数组) | 工具白名单（MCP server:tool 形式） |
| permission_profile | TEXT(JSON) | 工作权限：可访问工作空间范围、高危动作禁限 |
| status | TEXT | active / disabled |
| reports_to | FK→employee, null | 上下级 |
| adapter_type | TEXT | 'api' / 'cli' |
| cli_profile | TEXT(JSON), null | CLI 员工：cli_kind、能力声明快照 |

### model_connection（模型连接 = 可测试的连接配置）
| 列 | 说明 |
|---|---|
| name / provider(litellm 前缀) / model | 如 deepseek/deepseek-chat |
| api_key_ref | **只存环境变量名/密钥库引用，不存明文** |
| base_url, timeout_s, retry_policy(JSON) | |
| last_health_check_at / last_health_status | |

### employee_position（兼任）
(employee_id, position_id, department_id, is_primary)

## 3. 任务域（任务与执行记录分离——铁律）

### task
| 列 | 说明 |
|---|---|
| project_id / parent_task_id(子任务) / title / objective | |
| state | TEXT，状态机唯一权威字段：draft / plan_pending_approval / approved / running / in_review / review_passed / rework / pending_final_acceptance / done / paused / cancelled / failed / waiting_user_input / waiting_approval / over_budget |
| assigned_employee_id | 当前负责员工 |
| depends_on | TEXT(JSON数组 of task_id) |
| priority / deadline / budget_limit_usd | |
| rework_count / max_rework | 返工计数与上限 |
| final_deliverable | TEXT(JSON，指向工作空间产物) |

### task_run（一次执行 = 一条记录，历史不覆盖）
| 列 | 说明 |
|---|---|
| task_id / run_no(同 task 内递增) / trigger(manual/schedule/rework) | |
| state | running / succeeded / failed / cancelled |
| started_at / ended_at / error | 失败必记 error |

### agent_run（某员工在一次 task_run 中的执行单元）
| 列 | 说明 |
|---|---|
| task_run_id / employee_id / adapter_type | |
| external_ref | CLI session id / LiteLLM request id |
| input_payload / output_payload | TEXT(JSON) |
| state / error | |

### task_event（事件流，与审计日志分离——借鉴 HALF）
| 列 | 说明 |
|---|---|
| task_id / task_run_id / ts / type | dispatched/progress/message/completed/timeout/approval_requested/state_changed… |
| payload | TEXT(JSON) |

## 4. 监督域

### review_report（结构化审查报告，6 要素必填）
| 列 | 说明 |
|---|---|
| task_run_id / reviewer_employee_id / reviewed_employee_id | |
| conclusion | pass / reject / conditional |
| issues | TEXT(JSON数组: {severity: critical/major/minor, description, evidence, suggestion}) |
| next_action | approve / rework / escalate_to_user |
| cross_model | BOOL（是否跨模型交叉审查） |

## 5. 审批与审计域

### approval_request
| 列 | 说明 |
|---|---|
| agent_run_id / action_type | file_write/file_delete/shell_exec/software_install/cloud_upload/system_config/code_publish/service_deploy/unauthorized_tool |
| risk_level | low/medium/high/critical |
| params_preview / evidence | TEXT |
| state | pending / approved / rejected / modified |
| decided_by | 'user'（Agent 永远不可能出现在此列——DB 层 CHECK 约束 + 应用层双保险） |
| decided_at / decision_payload | |

### audit_log
| actor_type(user/agent/system) / actor_id / action / target / detail(JSON) / ts | 只增不改 |

## 6. 成本域

### usage_record
| 列 | 说明 |
|---|---|
| agent_run_id / employee_id / model | |
| prompt_tokens / completion_tokens / cost_usd(REAL, 可空) | cost 计算失败记 null（降级策略） |
| latency_ms | |

## 7. 工作空间与会议域（M2/M4 详细化）

- **workspace**：project_id、root_path（用户授权的本地目录）、agent ACL 表 `workspace_grant(employee_id, workspace_id, read/write)`
- **meeting / meeting_message / meeting_decision**：M4 定稿；decision 可关联生成的 task_id

## 8. 索引与约束（初版）

- task(state)、task_event(task_id, ts)、usage_record(employee_id)、approval_request(state) 建索引
- CHECK：task.state 枚举内；approval_request.decided_by='user'；rework_count<=max_rework 由应用层裁决
- LangGraph checkpointer 表独立 schema 前缀 `lg_`，与业务表隔离
