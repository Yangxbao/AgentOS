# Changelog

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
