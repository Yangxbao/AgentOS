# Changelog

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
