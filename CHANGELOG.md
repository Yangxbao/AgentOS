# Changelog

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased] - M3-A 工具执行层

### Added
- **工作区与授权**：`workspace` / `employee_workspace_grant`；目录级 read/write；撤权立即生效；归档不删磁盘文件；系统目录/用户主目录/盘符根拒绝
- **工具注册中心**：`fs.list_dir`、`fs.read_file`、`fs.stat`、`fs.write_file`、`fs.delete_file`、`http.request`、`shell.run`（禁用态）；参数 Schema、风险、超时、输出上限
- **五层权限**：全局开关 → 公司策略/类别/工具白名单 → 员工 `tools_allowed` → 岗位/员工收窄 → 工作区授权；每层独立错误码
- **路径安全**：`safe_resolve` 拒绝绝对路径/盘符/UNC/ADS/NUL/`..`/保留设备名，逐级检查 symlink 与 junction，敏感文件名单
- **文件工具**：文本读取（256KB、UTF-8、密钥内容拒绝）、原子写入（create/overwrite/append、1MB）、单文件删除（返回 sha256）
- **HTTP 工具**：域名白名单、DNS 后 IP 检查（回环/私网/链路本地/云元数据）、重定向逐跳校验、请求头白名单、2MB/超时限制、禁用系统代理
- **工具循环**：只下发已授权 schema；最多 8 次；`TOOL_LOOP_EXCEEDED`；幂等键防重复副作用
- **工具审批**：`gate=tool_call`，保存 messages/pending/call_index；批准后从同一调用恢复（不重新调模型）；驳回 → `TOOL_APPROVAL_REJECTED`
- **审计与事件**：`tool_call` 全状态落库 + `audit_log` + `task_event`；参数/输出强制脱敏
- **API M3-01..10**：工作区 CRUD/授权、工具目录、公司工具策略、员工工具权限诊断、任务工具调用列表与详情
- **前端**：`/settings/workspaces`、`/settings/tools`、任务详情“工具调用”面板（含批准/驳回调用）
- 迁移 `m3_a_tools`（3 张新表 + 3 个新列）
- 测试：新增 171 个（路径 60 / 权限 23 / 文件 22 / HTTP 17 / 入口 14 / 循环 13 / Shell 9 / API 13）

### Fixed
- SQLite WAL 读快照导致 `cancel_requested/pause_requested` 不可见（M2 时序侥幸通过）
- 步骤会话在模型调用期间持有写锁，阻塞取消/暂停请求
- 工具连续调用复用同一条 `tool_call` 记录
- 工具路径 `handle` 未定义导致执行完成后抛错
- HTTP 4xx/5xx 被误判为执行失败（应为正常工具结果）

### Security
- `AGENTOS_TOOL_EXECUTION` 默认 **off**；即使开启仍需公司策略 + 员工白名单 + 工作区授权
- Shell 永久禁用：无任何命令执行代码路径（AST 扫描证明），策略与 API 均拒绝开启
- 已知限制：Windows TOCTOU 未彻底消除（见 `M3_MASTER_HANDOFF.md` §6.2）

## [Unreleased] - M2 任务闭环

### Added
- **任务中心**：任务/子任务统一实体；公司/部门/执行人/审核人、优先级、截止、交付标准、风险、预算、执行模式；状态机与乐观锁
- **执行引擎**：DB 队列 + 后台 TaskRunner；原子认领；部分唯一索引 `uq_task_run_active` 防重复执行；启动恢复（running → interrupted → paused）
- **执行前权限闸门**：在职/同公司、模型可用、风险 ≤ 有效上限、工具 ⊆ 授权、预算估算；不通过则不调模型
- **Mock 执行体**：确定性输出、可配置延迟与故障注入；`usage_record.billable=false`、cost=0，绝不冒充真实调用
- **多 Agent 协作**：依赖 DAG + 拓扑波次并行 + `agent_handoff` 交接；管理者自动拆分（LLM JSON + 严格校验）
- **人工审批**：`task_approval`；before_run / after_run 双关卡；批准/驳回/要求修改；回退指定步骤；返工上限
- **检查点恢复**：步骤级 `checkpoint`，恢复只跑未完成步骤
- **可观测性**：任务时间线、Agent 执行详情、Token/成本聚合、监控摘要；`/monitor` 页面
- 迁移 `m2_task_center`（task +25 列、task_run +6 列、agent_run +5 列、2 张新表）
- 前端：任务中心、任务详情（计划/审批/时间线/成本）、执行监控
- E2E：`scripts/e2e_m2.py`（Mock 13 项；`--real` 增加一次最小真实调用）
- 测试：新增 38 个（任务 8 / 执行 11 / 协作 7 / 审批 6 / 监控 6）

### Changed
- `LiteLLMAdapter` 支持 `max_tokens`；`AGENTOS_MAX_TOKENS` 控制真实调用上限（默认 1024，E2E 用 96）
- SQLite 连接增加 `timeout=30`，降低并行步骤写入锁冲突
- 前端首页改为任务中心；导航新增「执行监控」
- API 版本标识 `0.2.0-m2`

### Notes
- 真实模型仅在验收时调用 4 次（含一次两步协作），共 353 tokens、约 $0.00006285；未新增付费服务
- 浏览器可视化验收未执行（未安装 Playwright，按约束不安装）；构建与 API 合同验证通过

## [Unreleased] - M1 收尾（P1 清理）

### Added
- 核心审计事件 14 类：员工创建/修改/启停/软删除、模型绑定切换、模型连接创建/变更/删除/测试、提示词版本创建/激活、配置导入/导出
- `apps/api/audit.py`：统一注入 `request_id`、actor 并强制脱敏的审计入口
- `tests/test_audit_events.py`（7）、`tests/test_import_transaction.py`（4）、`tests/test_api_gaps.py`（7）
- `AGENTOS_PROMPTS_ROOT` 环境变量：提示词根目录可覆盖，测试与 E2E 使用独立目录

### Changed
- `packages.permissions.audit.write_audit` 新增 `commit` 参数，支持加入调用方显式事务（导入用 `commit=False`）
- 配置导入改为**单事务**：公司/部门/岗位/连接/员工/岗位关联/提示词元数据/审计一次提交，失败整体回滚
- 提示词导出改为版本升序、导入按 `version` 排序，并校验 `content_hash`（不符报 `IMPORT_PROMPT_HASH_MISMATCH`）
- `create_revision` / `activate_revision` 支持 `commit=False`；写盘或改名失败会清理临时文件

### Fixed
- 配置导入失败可能留下部分数据与孤儿提示词文件；现按“本批次新建文件清单”补偿删除，补偿失败保留孤儿供对账
- 提示词往返导入版本倒序（v2 内容被存成 v1）
- `requires_approval` 的合法收紧因列表顺序被误判为扩权（列表类权限改为集合语义比较）
- 连接测试的上游错误信息可能回显密钥片段，现 `redact()` 后再生错误消息
- 测试向真实 `data/prompts` 写入文件：改为每测试独立根目录；历史 36 个目录已移入 `data/backups/prompt_orphans_20261105_194225/`

## [Unreleased] - M1 完成（B3–B6）

### Added
- 员工与模型解耦：employee / employee_position / model_connection / model_switch_log + 14 个 API
- 凭据引用（env:/dpapi:/keyring:）与脱敏、模型目录、健康缓存（正 300s/负 60s/配置指纹）
- 提示词外置与不可变版本（原子写 + SHA-256 + 激活指针 + diff + 对账脚本）
- 公司配置导出/导入（zip、dry-run、rename 冲突、无密钥、路径穿越防护）
- 三层权限（公司∩岗位∩员工，只收窄）、有效能力、派工硬过滤/评分、双池审查人 T1–T6
- 派工决策与审计日志（只增不改）
- 前端：员工/模型连接/提示词/导入导出/派工预览/审计/权限面板
- M1 E2E 脚本（3 场景、23 项检查）

### Changed
- `cross_model` 与 `cross_provider` 明确区分：tier 按"模型不同"判定，排序优先"供应商不同"
- 45 个契约端点全部注册；`/model-providers` 为辅助目录端点（不计入 45）

## [Unreleased] - M1 / B2

### Added
- 组织域数据模型：`company` / `department` / `position`（含 `can_review`、`review_capability_tags`）
- 迁移 `m1_b2_org`
- 领域服务 `packages/organization/`：公司、部门树（深度/成环/删除保护）、岗位、组织树组装
- 16 个 `/api/v1` 端点（API-01..16）：公司 5、部门 6、岗位 5
- 前端页面：组织架构（React Flow 只读）、组织设置（公司/部门/岗位 CRUD）
- B1 补充验收测试 9 个（错误包络/request_id、分页边界、CORS 预检、Referer、本地令牌、备份脚本）

### Fixed
- 默认数据库路径改为仓库绝对路径，避免从其他目录启动时静默建空库
- 启动时仅空库 `create_all`，已有库必须迁移，防止结构漂移
- LocalGuard 拒绝响应的 `request_id` 由 `-` 改为真实请求 ID
- 迁移测试改为动态读取 Alembic head，避免新增 revision 后断言失效

## [Unreleased] - M1 / B1

### Added
- Alembic 迁移体系：`m0_baseline` 基线 + `m1_b1_agent_run_employee_id`（SQLite batch 模式）
- 数据库备份脚本 `scripts/backup_db.py`（SQLite 在线备份 + 清单）
- 本地管理接口防护 `apps/api/security/local_guard.py`：Host / Origin / `X-AgentOS-Client` / Fetch Metadata / 可选令牌
- 安全启动器 `scripts/run_api.py`：默认 127.0.0.1，拒绝 0.0.0.0（需显式授权）
- API 分层：`routers/`、`deps.py`（分页/会话/调用主体）、`errors.py`（统一错误包络 + request_id）
- 前端基础依赖：TanStack Query、React Flow、react-hook-form + zod、shadcn 运行时依赖
- 前端 API 客户端 `apps/web/src/api/client.ts` 与 `queryClient`
- 测试：迁移 2 个（空库 / M0 旧库）+ 本地防护 5 个

### Changed
- `agent_run` 新增可空 `employee_id`（双写过渡，M2 切换主引用）
- 项目可通过 `pip install -e .` 安装，`main.py` 保留兜底导入但不再依赖
- `@app.on_event` 改为 `lifespan`；接口错误统一为 `{"error": {...}}` 包络
- 前端健康检查改用统一 API 客户端；zod 由 3.x 升至 4.6.7（修复 GHSA-mrhx-c7xc-m3w5）

## [Unreleased] - M0

### Added
- 12 个 GitHub 竞品调研（docs/research/）
- PRD 与功能矩阵（docs/product/）
- 六份架构文档（docs/architecture/）
- Monorepo 项目骨架（apps/api、apps/web、packages/）
- M0 最小技术验证脚本（scripts/m0_verify.py）
- 开源基础设施：MIT LICENSE、CONTRIBUTING、CODE_OF_CONDUCT、SECURITY、CI
