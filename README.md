# AgentOS

**AI 数字员工协作操作系统** — 像经营一家真实公司一样，组建、管理并交付成果的 AI 团队。

不是多 AI 群聊工具。每个 AI 员工有自己的身份、岗位、能力、职责和权限；不同 AI 可以协作也可以互相质疑；开发员必须接受测试员的独立验证；**用户始终拥有最终控制权**。

> 当前状态：**M2 完成；M3-A 工具执行层已落地（工作区/文件/HTTP/工具审批/审计），浏览器验收 29/29**
> 接手项目请先读 **[HANDOFF.md](HANDOFF.md)**（环境/架构/数据/命令/坑/下一步，一份就够）
> 历史：M1 [单文档](M1_PLAN_HANDOFF.md)｜M2 [设计](M2_MASTER_PLAN.md) · [交接](M2_MASTER_HANDOFF.md)｜M3 [设计](M3_MASTER_PLAN.md)

## 特性

- 🏢 **AI 公司组织**：公司/部门/岗位/上下级，组织图；员工与模型解耦（主备模型、工具授权）
- 🔌 **多模型接入**：LiteLLM 统一调用；凭据只存引用（`env:`），连接级超时/重试/健康检查
- 📋 **任务中心**：优先级、截止、交付标准、执行/审核人、状态机、计划与子任务、乐观锁
- ⚙️ **执行引擎**：后台队列真实执行（不依赖页面打开）；失败/超时/重试/取消/暂停/恢复；重启恢复
- 🤝 **多 Agent 协作**：依赖 DAG、拓扑波次并行、上下文交接、管理者自动拆分（严格校验，失败不伪造）
- ✅ **人工审批**：执行前/交付后双关卡；批准/驳回/要求修改；驳回可回退到指定步骤，已完成上游不重跑
- 💰 **可观测与成本**：任务时间线、Agent 执行详情、Token/成本聚合、监控摘要；Mock 明确不计费
- 🧰 **工具执行层（M3-A）**：工作区 + 员工授权、文件读写/列目录/stat、HTTP 白名单；五层权限、敏感文件与路径逃逸防护、逐次审计、高风险调用人工审批、恢复不重复调用模型
- 🏠 **本地优先**：Windows 本地完整运行，默认只监听 `127.0.0.1`；工具全局开关默认关闭，Shell 永久禁用

## 文档

| 类别 | 入口 |
|---|---|
| 产品 | [docs/product/PRD.md](docs/product/PRD.md) · [功能矩阵](docs/product/FEATURE_MATRIX.md) |
| 调研 | [竞品分析](docs/research/COMPETITOR_ANALYSIS.md) · [技术对比](docs/research/TECHNOLOGY_COMPARISON.md) · [选型决策](docs/research/PROJECT_SELECTION.md) |
| 架构 | [系统架构](docs/architecture/SYSTEM_ARCHITECTURE.md) · [数据库](docs/architecture/DATABASE_DESIGN.md) · [Agent Adapter](docs/architecture/AGENT_ADAPTER.md) · [安全模型](docs/architecture/SECURITY_MODEL.md) |
| M1 | [M1_PLAN_HANDOFF.md](M1_PLAN_HANDOFF.md)（组织/员工/模型/提示词/权限/派工/审计） |
| M2 | [M2_MASTER_PLAN.md](M2_MASTER_PLAN.md)（架构/数据/API/状态机/时序）· [M2_MASTER_HANDOFF.md](M2_MASTER_HANDOFF.md)（进度/证据/风险） |
| 交接 | **[HANDOFF.md](HANDOFF.md)**（唯一入口：环境变量/目录/架构/数据库/命令/坑/下一步） |
| M3 | [M3_MASTER_PLAN.md](M3_MASTER_PLAN.md)（工具层/权限/文件安全/递归/记忆/Worker 设计） |
| 开发 | [路线图](docs/development/ROADMAP.md) · [里程碑验收](docs/development/MILESTONE_ACCEPTANCE.md) · [ADR](docs/decisions/ADR_INDEX.md) |
| 测试 | [M0](docs/testing/M0_TEST_REPORT.md) · [M1](docs/testing/m1_final_regression.txt) · [M2 回归](docs/testing/m2_final_regression.txt) · [M2 E2E](docs/testing/m2_e2e_mock.txt) · [M3 浏览器验收](docs/testing/m3_browser_acceptance.txt) |

## 快速开始

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
pip install -e .
copy .env.example .env          # 填入 DEEPSEEK_API_KEY（只用于真实模式）
alembic upgrade head            # 已有 M0 库先 stamp m0_baseline
python scripts/run_api.py --port 8000   # 默认只监听 127.0.0.1

# 前端（另开终端）
cd apps/web && npm install && npm run dev   # http://127.0.0.1:5173

# 测试
pytest tests/ -v
ruff check apps packages scripts tests migrations
cd apps/web && npm run build

# 端到端（默认全 Mock，不产生费用）
python scripts/e2e_m2.py
python scripts/e2e_m2.py --real   # 额外一次最小真实调用（需 .env 有 Key）

# 真实浏览器验收（使用本机 Edge，不安装 Playwright；M3 起会自动打开工具开关）
python scripts/browser_acceptance.py

# 真实浏览器验收（使用本机 Edge，不安装 Playwright；M3 起会自动打开工具开关）
python scripts/browser_acceptance.py

# 备份 / 提示词对账
python scripts/backup_db.py
python scripts/reconcile_prompts.py
```

### 执行模式

| 模式 | 触发 | 说明 |
|---|---|---|
| `mock` | 任务 `execution_mode=mock` 或 `AGENTOS_MODEL_MODE=mock` | 不调外部服务；`usage_record.billable=false`、cost=0 |
| `real` | `execution_mode=real` 或 auto（默认） | 使用员工主/备模型连接；真实计费；`AGENTOS_MAX_TOKENS` 控制单次上限 |

### 任务怎么跑

1. 组织设置建公司/部门/岗位；AI 员工建人（至少一人 `can_review`，自动拆分需 `is_managerial`）
2. 模型连接用 `env:DEEPSEEK_API_KEY` 这类引用，不存明文
3. 任务中心新建任务 → 分配员工 →（可选）设计划/审批 → 执行
4. 审批在任务详情页处理；执行过程与成本在时间线/成本明细中查看
5. 服务重启后，遗留执行会标记 `interrupted` 并把任务转 `paused`，点“恢复”从检查点续跑

## 许可证

[MIT](LICENSE)
