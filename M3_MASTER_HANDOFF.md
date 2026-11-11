# AgentOS 交接文档（唯一交接入口 · 2026-11-11 全面重写）

> **给接手的 AI**：本文是项目**唯一**交接入口，读完即可直接接手。你的前任（ZCode/GLM）已完成 M3 全部批次、三模型真实链路接入与四轮体验完善，工作区干净。请先读 §1-3（状态/环境/坑），再按用户指令行事。
> 状态图例：✅已实现且测试通过｜🟡已实现未充分验证｜♻️已有机制回归确认｜⬜未实现｜🚫因授权限制未执行

---

## 1. 项目一句话与架构

AgentOS 是**本地单机运行**的 AI 数字员工协作系统：公司 → 部门/岗位 → AI 员工（绑定模型/提示词/权限）→ 任务派工 → AI 员工真实执行（多 Agent 协作、受控工具、递归拆分、人工审批）→ 全程可追溯/审计/计成本。

- 后端：Python 3.13 + FastAPI + SQLite(WAL)，**只监听 127.0.0.1:8000**，`/api/v1` 下 93 个 route-method 对
- 前端：React 18 + Vite（dev 5173，`/api` 同源代理）；17 条路由
- 模型：LiteLLM（已接 DeepSeek 付费 / 智谱 GLM-4-Flash 免费 / OpenRouter Nemotron :free 三链路）
- 安全：五层工具权限、LocalGuard（Host/Origin/Sec-Fetch-Site/X-AgentOS-Client）、Kill Switch、审批、预算熔断、连续拒绝熔断、Worker 租约、审计脱敏
- 单用户 `owner_id="local"`，无账号体系（M4 内容，未开始）

## 2. 当前状态（接手时基线，全部实测）

```
Git HEAD：4cc6e43（工作区干净，本地提交未 Push；提交史见 git log，均带详细说明）
数据库：m3b_memory_workers (head)，24 张逻辑表
测试：357 passed / 3 skipped（全 Mock，免费）；ruff 全过；前端 tsc+build ✓
浏览器验收：32 项全过（scripts/browser_acceptance.py，需 8000/5173/9333 空闲）
后端进程：交接时可能已停止（前任实验后未保持运行）——启动命令见 §8
真实费用累计：约 $0.0015（全部经用户授权）
```

### 2.1 已完成里程碑

| 里程碑 | 状态 |
|---|---|
| M0-M2（基座/组织/任务闭环/多Agent/审批） | ✅ |
| M3-A 工具执行层（工作区/五层权限/审计） | ✅ |
| M3-E 执行监管（预算熔断/连续拒绝/kill switch/监控） | ✅ |
| M3-B 递归任务树（深度/步数上限/replan/父子预算/自动分配） | ✅ |
| M3-C 长期记忆（FTS5/三级作用域/不可信注入） | ✅ |
| M3-D 多 Worker（租约/心跳/崩溃恢复） | ✅ |
| M3-F 端到端验收（GitHub 教程 16 项，本地 stub） | ✅ |
| 员工配置中心（详情页编辑工具/工作区/岗位/记忆） | ✅ |
| 审批中心页面 + 嵌套审批自动续跑（三层级联验证） | ✅ |
| 工作区文件浏览器（owner 管理视图，只读） | ✅ |
| 预算预扣（real 模式调模型前拦截超支） | ✅ |
| config_io 扩展（工作区/授权/记忆随包迁移） | ✅ |
| **真实模型三链路实验** | ✅ 见 §5 |

### 2.2 未实现（不要当作缺陷）

账号体系（M4）、真实外网业务、embedding 向量检索、PostgreSQL/Redis、任务/审批历史导出、config_io 的任务运行历史导出、员工删除 UI、审核人 can_review 前端过滤（后端已校验）。

## 3. 环境与关键路径

| 项 | 值 |
|---|---|
| 项目根 | `E:\AgentOS`（所有命令在此执行；Python 用 `.venv\Scripts\python.exe`） |
| `.env` 现状 | `AGENTOS_MODEL_MODE=real`、`AGENTOS_TOOL_EXECUTION=on`、`AGENTOS_DB_URL=sqlite:///data/agentos.db`、`AGENTOS_MODE=local`、密钥：`DEEPSEEK_API_KEY`（已配）、`ZHIPU_API_KEY`（已配）、`OPENROUTER_API_KEY` + `_2`（用户提供，已配）——**不要修改/打印这些值** |
| 三模型连接（真实库） | DeepSeek「测试连接」budget 档；智谱「GLM-4-Flash（免费）」OpenAI 兼容通道 base_url=open.bigmodel.cn/api/paas/v4；OpenRouter「Nemotron 3 Ultra（免费）」:free 档 |
| 免费模型实测 | 智谱 GLM-4-Flash：function calling **3/3 稳定**；OpenRouter Nemotron :free：**不稳定**（时灵时不灵）——生产建议智谱 |
| 真实库数据 | M0 遗留 4 任务 + 用户真实实验数据（小宝公司 fc3efd74、15 名员工含 10 人实验团队、实验区工作区、3 个实验任务及产物）——**全部是用户数据，勿删勿改** |
| 实验工作区 | `E:\AgentOS\experiment_workspace`：test.txt（"大肥鱼是诗人"，用户数据勿动）、协作报告.md、协作实验报告.md、final_summary.md、user_guide.md、requirements_brief.md、raw_notes.txt、competitor.md（实验产物） |
| 入口文档 | `M3_MASTER_HANDOFF.md`（本文）、`HANDOFF.md`（项目级环境/红线/坑）、`docs/AI_PROJECT_BRIEFING.md`（给外部 LLM 答疑）、`docs/acceptance/`（各轮验收报告） |

## 4. 数据库与迁移

- 迁移链：`m0_baseline → ... → m3_a_tools → m3b_memory_workers (head)`
- `tests/test_migrations.py` 双路径验证（空库+旧库副本）；真实库已备份于 `data/backups/`（多份）
- **只向前迁移**；如需新表/列走 Alembic 规范
- **真实库含用户实验数据**：小宝公司 15 员工、7+ 任务（含三模型实验记录）、实验区工作区——测试一律用临时库，绝不写入真实库

## 5. 真实模型实验记录（三链路全通）

| # | 链路 | 实验 | 结果 | 费用 |
|---|---|---|---|---|
| 1 | DeepSeek（付费 budget 档） | 单员工 fs.read_file 读 test.txt | ✅ PASS（nonce 铁证：汇报含"大肥鱼是诗人"） | $0.00044 |
| 2 | 智谱 GLM-4-Flash（免费） | 三员工协作（读→析→写） | ✅ 读/析 PASS；写步骤教训见下 | $0.00 |
| 3 | OpenRouter Nemotron 550B（:free） | 三员工协作+报告落盘 | ✅ 全 PASS（报告 1242B 落盘，含批判性观察） | $0.00 |

**关键教训（写新实验必读）**：
1. **Mock marker 语法（`[tool:...]`）对真实模型无效**——真实模型走原生 function calling，实验指令必须用自然语言描述任务
2. **免费模型 function calling 可靠性差异真实存在**：智谱 GLM-4-Flash 稳定（4/4），OpenRouter Nemotron :free 不稳定（时灵时不灵）——真实业务步骤建议智谱，Nemotron 用于纯文本步骤
3. 预算预扣在真实链路验证：real 模式按目录档位预估计入检查，超支在调模型前拦截
4. 详细报告：`docs/acceptance/2026-11-11_真实实验报告.md`、`2026-11-11_OpenRouter实验报告.md`、`2026-11-11_十人闭环实验报告.md`

## 6. 本会话新增的坑（接手必读，完整版见 HANDOFF.md §13）

1. **`.env` 追加必须先查末尾换行**——前任曾把 `ZHIPU_API_KEY` 追加拼到 `AGENTOS_TOOL_EXECUTION=on` 行尾，两个配置同时失效（已拆行修复）。追加前用 Python 检查 `src.endswith("\n")`
2. **heredoc 写代码文件会产生 NULL 字节**（`\x00` 双层转义事故）——改代码文件用 Write/Edit 工具，不用 python heredoc；事故修复用字节算术 `bytes([92]) + b'x00'` 构造替换
3. **覆盖已跟踪文件前先查 git**——前任曾覆盖用户 test.txt（已恢复）；写文件前查 `git log/diff`
4. **browser_acceptance 的 SPA 断言必须轮询重试**——React 首次提交存在"只有 header"的中间态，单次 CDP eval 会撞上（B5.5/B7 已改轮询模式）
5. **curl JSON 用 ASCII**（中文 body 会被 GBK 弄坏导致解析失败）
6. **load_dotenv 在 create_app 时执行**——改 .env 后必须重启后端；测试进程会被 .env 泄漏，conftest 已固定 mock/off
7. **前端新增字段必须同步验证后端聚合是否返回**（monitor workers 字段曾漏导致面板空白）
8. **OpenRouter :free 清单随平台调整**——接入前实时查询 `/api/v1/models`（llama-3.3:free 已下架为先例）
9. 重复 curl 的中文 JSON 会被 GBK 编码弄坏——验证脚本 body 用 ASCII

## 7. 安全红线（不可违反，继承自用户历次任务书）

- 不调用未授权付费模型（当前 DeepSeek 与免费模型均经用户授权；**新增付费调用仍需用户明示**）
- 不接真实外网新服务、不装 Redis/PostgreSQL/Playwright、不修改 Windows Defender/系统设置
- 不 Push（用户未给通道）、不删除/覆盖用户真实数据（真实库、experiment_workspace 的用户文件）
- 不削弱任何安全机制（五层权限/Kill Switch/审批/熔断/审计）；不擅自改 `.env` 的模型模式与开关
- 密钥不入库不进日志不进报告；`.env` 在 gitignore 中 ✓

## 8. 启动与验收命令

```cmd
cd /d E:\AgentOS
.venv\Scripts\python.exe scripts\run_api.py --port 8000        & REM 后端（health: /api/health → 0.3.1）
cd apps\web && npm run dev                                      & REM 前端 localhost:5173
.venv\Scripts\python.exe -m pytest tests\ -q                    & REM 357 passed, 3 skipped（全 Mock 免费）
.venv\Scripts\python.exe -m ruff check apps packages scripts tests migrations
.venv\Scripts\python.exe scripts\browser_acceptance.py          & REM 32 项（需端口空闲）
.venv\Scripts\python.exe scripts\backup_db.py                   & REM 备份
```

## 9. API 速览（93 个端点的主要域）

组织/部门/岗位 16｜员工/模型连接 16（含 PATCH tools_allowed、model-binding、test）｜提示词/导入导出 7｜治理（权限/派工/审计）7｜任务/审批 21（含 replan、plan-revisions）｜工具（工作区/策略/文件浏览/授权/工具目录/五层诊断）14｜记忆 7｜系统（kill switch）2｜监控（summary 含 tool_execution/tools/budgets/workers）｜Workers 2

## 10. 前端页面（17 路由）

任务中心/详情（含重规划区块、预算对比）/审批中心 /approvals/监控（工具统计+Worker 面板+预算）/组织图/员工列表（概览+编辑配置入口）/员工详情（基本信息+岗位+工具三态+工作区授权+记忆区块+检索预览）/工作区（含文件浏览器）/工具策略/记忆中心/模型连接/导入导出/审计/组织设置

## 11. 已知限制（🟡，如实转述给用户）

1. 免费模型 function calling 可靠性差异（智谱稳/Nemotron 不稳）——真实业务步骤建议智谱
2. Mock marker 语法只在 Mock 有效——真实模型实验指令用自然语言
3. Kill switch 进程内存态，重启回到 env 初始值（设计取舍，文档三处明示）
4. env off 时 kill switch 只能重启后端复位（API 409 拒绝清除；功能无差异）
5. 单步成本超支由"调模型前预扣"拦截（保守档位估计，非精确计价）
6. denied_count 跨并行步骤极端并发下可能少计（SQLite 单写者 last-write-wins）
7. FTS5 中文按连续字串匹配，召回靠"FTS+LIKE 混合"兜底；无量化指标
8. config_io 导出不含任务/审批运行历史（设计边界：导出=配置与资产）
9. 多层嵌套（>3 层）自动续跑机制适用但仅验证到 3 层
10. 岗位新建/编辑在组织设置（员工详情只能选配）；员工删除无 UI（API 有）

## 12. 下一步待办（用户未裁决，不要擅自执行）

1. **用户统一真实实验**（用户说"我再统一实验"——等用户指令，不要代跑新实验）
2. Git Push（需用户提供通道；本机代理仅放行 api.github.com）
3. M4 方向（账号体系/真实外网业务/生产化）——用户未裁决
4. 可选打磨：审核人 can_review 前端过滤、岗位新建/编辑入口优化、FTS 分词增强

## 13. 启动检查清单（接手后先跑一遍）

```cmd
cd /d E:\AgentOS
git status --short                                              & REM 应干净
git log --oneline -3                                            & REM 应见 4cc6e43 或更新
.venv\Scripts\python.exe -m pytest tests\ -q                    & REM 357 passed, 3 skipped
.venv\Scripts\python.exe -m ruff check apps packages scripts tests migrations
cd apps\web && npm run build                                    & REM ✓
```

全部符合 → 接手成功。不符合 → 先查 §6 坑清单与 `docs/acceptance/` 最新报告定位。

---

*交接完成：2026-11-11｜前任：ZCode（GLM）｜累计真实费用 $0.0015（全部经用户授权）｜本文档替代此前所有交接类文档，保持单一入口*
