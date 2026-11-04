# M1 分批开发计划与验收方案

> v1.0（待用户确认）｜2026-11-05
> 原则：小步交付、每批可独立验收、每批结束跑全量回归；不一次性堆功能

---

## 0. 总览

| 批次 | 主题 | 后端 | 前端 | 依赖 | 出口标准 |
|---|---|---|---|---|---|
| B1 | 地基：迁移/打包/测试夹具/错误体系 | 重构 | shadcn+Query 接入 | 无 | 旧测试全绿 + Alembic 双路径可升级 |
| B2 | 组织域（公司/部门/岗位） | 新增 | 组织设置 + 组织图只读 | B1 | 组织树 API + 成环/删除保护测试 |
| B3 | 员工域 + 模型连接（解耦核心） | 新增 | 员工 CRUD/向导/模型页 | B2 | 解耦 5 用例 + 连接测试真实调用 |
| B4 | 提示词外置 + 导入导出 | 新增 | 提示词编辑器 + 导入导出 | B3 | 版本不可变 + 往返一致 |
| B5 | 权限计算 + 派工预览 + 审计 | 新增 | 权限面板 + 派工台 + 组织图编辑 | B3 | 三层交集 12 用例 + 派工 5 用例 |
| B6 | 端到端验收与文档 | 修补 | 打磨 | B1–B5 | M1 验收报告全项有证据 |

每批约 3–6 个 commit；每批结束必须：`ruff` 全绿 → `pytest` 全绿 → `npm run build` 通过 → 更新文档 → 提交。

---

## B1 地基（不做新功能，先还债）

### 范围
1. **Alembic 引入**：`requirements.txt` 加 `alembic`；`alembic.ini` + `migrations/`；`m0_baseline` 基线；`env.py` 开 `render_as_batch=True`
2. **打包修正**：`pyproject.toml` 加 `[build-system]` + `[tool.setuptools]`，`pip install -e .` 后不再依赖 `sys.path.insert`（保留兜底但标记 deprecated）
3. **API 分层重构**：`main.py` 拆出 `routers/`、`deps.py`、`errors.py`；`on_event` → `lifespan`；统一异常处理器返回错误包络
4. **测试夹具**：`tests/conftest.py` 提供 `tmp_engine`（临时 SQLite + 自动建表/migrate）、`client`（httpx AsyncClient）、`actor`、`seeded_company` 工厂
5. **备份脚本**：`scripts/backup_db.py`（复制 db + prompts 目录 + 版本信息）
6. **前端基建**：安装 shadcn/ui 基础组件（button/dialog/input/select/tabs/toast/badge/skeleton）、TanStack Query、react-hook-form、zod；建立 `api/client.ts`（统一 fetch + ApiError）与 `queryClient`
7. **CI 增补**：迁移双路径测试（空库 upgrade、M0 快照库 stamp+upgrade）

### 验收
| 项 | 命令 | 标准 |
|---|---|---|
| 迁移-空库 | `alembic upgrade head`（临时库） | 建出全部表，无报错 |
| 迁移-M0 库 | 复制 `data/agentos.db` → `alembic stamp m0_baseline && alembic upgrade head` | 表结构与新库一致（用 `alembic check` 或 schema diff 脚本） |
| 回归 | `pytest -q` | 7 个旧测试 + 新增迁移测试全通过 |
| 接口 | `curl /api/health`、`/api/tasks` | 行为与 M0 一致（不破坏） |
| 前端 | `npm run build` | 通过，且新依赖无漏洞报告 |

**风险**：Alembic autogenerate 对 SQLite 类型推断可能产生噪音 → 手工裁剪基线，只保留 M0 实际 DDL。

---

## B2 组织域

### 范围
- 模型与迁移：`company` / `department` / `position`（revision `m1_b2_org`）
- 领域服务：`packages/organization/`（`companies.py`、`departments.py`、`positions.py`、`tree.py`）
- 规则：BR-02/03/04/05（唯一性、深度 ≤8、成环、非空部门不可删）
- API：公司 5 + 部门 6（含 org-tree）+ 岗位 5
- 前端：`/settings/organization` 增删改；`/org` 组织图**只读**渲染（React Flow，部门+岗位节点，员工节点占位）

### 验收
| 项 | 标准 |
|---|---|
| 组织树 | 建 3 层部门 + 2 岗位，`GET /org-tree` 返回结构正确、depth 计算正确 |
| 成环 | 把父部门拖到子部门下 → 409 `BR_DEPARTMENT_CYCLE`，库无变化 |
| 深度 | 第 9 层创建被拒 |
| 删除保护 | 含员工部门删除 → 409，提示人数 |
| 唯一性 | 同公司重名部门 → 409 |
| 前端 | 组织图渲染 30 节点无报错；缩放/适应可用 |
| 测试 | 新增 ≥ 10 个集成测试（每个规则至少 1 正 1 反） |

---

## B3 员工域 + 模型连接（解耦核心）

### 范围
- 迁移 `m1_b3_employee_model`：employee / employee_position / model_connection / model_switch_log；`agent_run.employee_id` 加列
- 领域服务：`employees.py`（CRUD/启停/软删/汇报链校验）、`model_connections.py`（CRUD/健康/引用计数）、`capabilities.py`（三层交集）
- 凭据层：`packages/model_gateway/credentials.py`（`env:`/`dpapi:`/`keyring:` 解析 + 格式校验 + 脱敏）
- provider catalog：`packages/model_gateway/catalog.py`（deepseek/openai/anthropic/gemini/openrouter/ollama 的静态模型清单 + 能力标注）
- API：员工 12 + 连接 6（含真实连接测试）
- 前端：员工列表、建员工向导、员工详情（档案/模型 Tab）、模型连接页

### 验收
| 项 | 标准 |
|---|---|
| 创建员工 | 3 步向导走通，落库 employee + employee_position + 审计 |
| 解耦 A3-1 | 两员工共用连接，各自 usage/run 归属正确（测试断言） |
| 解耦 A3-2 | 切换模型后 id 不变、历史 model 不变、switch_log +1 |
| 解耦 A3-3 | 切到弱能力模型返回 warnings |
| 解耦 A3-4/5 | 切到停用连接 422；删被引用连接 409 |
| 连接测试 | 对 DeepSeek 真实调用成功返回 latency（用现有 `DEEPSEEK_API_KEY`）；错误 Key 场景用假 ref 验证 502 分类（不真发请求或允许失败） |
| 密钥 | 响应/日志 grep 无 `sk-`（自动化测试） |
| 前端 | 新建 2 个员工并切换模型，刷新后状态一致 |
| 测试 | ≥ 18 个新测试（含 5 个解耦用例） |

**风险**：连接测试会消耗真实 token → 用 `max_tokens=8` 且测试中 mock 大部分场景，仅 1 个"真实连通"用例（可跳过，标记 `@pytest.mark.live`）。

---

## B4 提示词外置 + 导入导出

### 范围
- 迁移 `m1_b4_prompt`：prompt_revision
- 提示词存储：`data/prompts/employees/<employee_id>/vNNNN.md`（YAML frontmatter：role/goal/rules/tools_policy），写入即计算 SHA-256；`prompts.py` 服务（create/activate/diff/load）
- 运行时加载器：`load_active_prompt(employee_id)` 供 M2 复用；哈希不符抛 `BR_PROMPT_HASH_MISMATCH`
- 导入导出：`config_io.py`（zip：`manifest.json` + `company.json` + `org.json` + `employees/*.json` + `prompts/*.md`）；dry-run 与事务导入；路径穿越防护
- API：提示词 4 + 导入导出 3
- 前端：提示词编辑器（版本列表/编辑/对比/激活）+ 导入导出向导

### 验收
| 项 | 标准 |
|---|---|
| 版本不可变 | 连续保存 3 次 → 3 个文件、v1 内容哈希不变 |
| 激活 | 激活 v1 后 `prompt_active_version=1`，旧版本文件仍在 |
| 篡改检测 | 手工改文件内容 → 加载报 `BR_PROMPT_HASH_MISMATCH` |
| 导出 | zip 内无密钥（grep 断言），manifest 计数与实际文件一致 |
| 导入 dry-run | 新建/覆盖/跳过计数正确，不写库 |
| 往返 | 导出→导入新库→组织结构与提示词哈希 100% 一致（自动化测试） |
| 路径穿越 | 构造 `../../evil.md` 的 zip → 拒绝 |
| 测试 | ≥ 14 个新测试 |

---

## B5 权限计算 + 派工预览 + 审计 + 组织图编辑

### 范围
- 迁移 `m1_b5_assignment_audit`：assignment_decision / audit_log
- `packages/permissions/`：`effective.py`（三层交集 + 来源链）、`policy.py`（action×risk 决策表 + 硬 deny 清单）、`audit.py`（只增写入器）
- `packages/organization/assignment.py`：硬过滤 8 条 + 5 因子打分 + 审查链推导 + `algorithm_version`
- API：effective-permissions、permission-overrides、capabilities、assignments/preview、audit
- 前端：权限 Tab（三层可视化）、派工预览台、组织图**可编辑**（拖拽改部门/汇报对象）、审计页

### 验收
| 项 | 标准 |
|---|---|
| 三层交集 | 12 组用例全绿（含"员工放宽被拒"） |
| 派工 B8-1..B8-5 | 5 组场景断言通过（含审查人 ≠ 执行人、无审查人时返回空+原因） |
| 决策留痕 | 每次 preview 落 assignment_decision，含 factors 与 algorithm_version |
| 权限拒绝 | `PERMISSION_WIDEN_DENIED` + 审计记录 |
| 审计 | 9 类事件各触发一次，记录可查、无更新接口 |
| 前端 | 权限来源链可见；派工台展示 5 因子；拖拽 10 次无错乱 |
| 测试 | ≥ 20 个新测试（权限 12 + 派工 5 + 审计 3） |

---

## B6 端到端验收

### 场景（必须三个全过）
1. **从零建公司**：建公司 → 2 部门 → 3 岗位 → 2 模型连接 → 3 员工（含兼任）→ 组织图正确 → 导出 → 导入到新库 → 结构一致
2. **解耦验证**：员工 A 切换模型 → 历史保留 → 同一连接的员工 B 记录不串账 → 派工预览中 A 的能力缺口被正确排除
3. **权限与派工**：限制某员工 file.write → 派"需要写文件"的任务 → 该员工被硬过滤 → 审查人推导正确且跨模型优先

### 交付
- `docs/testing/M1_TEST_REPORT.md`（真实命令、输出摘要、失败项、未测项）
- `docs/development/M1_HANDOFF.md`（对齐 M0_FINAL_HANDOFF 的 14 项格式）
- 更新 README / FEATURE_MATRIX / ROADMAP 状态
- `M1` tag + 三个演示脚本（`scripts/demo_m1_*.py`，可重复执行）

### 验收门槛
- 全量 `pytest` ≥ 50 个测试通过（M0 的 7 个必须在内）
- `ruff` 全绿、`npm run build` 通过
- 三个 E2E 场景真实跑通（截图或终端日志留证）
- 无 P0/P1 缺陷；P2 缺陷列清单并说明处理计划

---

## 3. M0 遗留问题处理安排

| 遗留项 | 当前状态 | M1 处理 | 归属批次 |
|---|---|---|---|
| V7 Codex CLI headless | ⛔ 被阻塞 | **不安装**；保持 BLOCKED，Adapter 接口不变；M1 允许录入 CLI 员工（`cli_profile`）但执行留 M2，且 UI 明确标"未验证" | — |
| V2 第二供应商 | ⏭️ SKIP | 不要求用户提供 Key；`catalog` 与连接测试支持多 provider，用户自行添加即生效；测试用 mock 覆盖 | B3 |
| V8 CrewAI 对照 | ⏭️ SKIP | **不安装**；LangGraph 选型结论维持（M0 V5 已实测核心原语），在 ADR-0001 标注"缺 CrewAI 对照数据" | — |
| LiteLLM fallbacks 故障注入 | 未测 | B3 增加一个不依赖外网的单元测试（mock 主模型抛错 → 断言走 fallback 分支） | B3 |
| Windows Job Object 子进程终止 | 未设计验证 | 顺延至 M2（CLI 执行真正落地时），M1 不做 | — |
| 浏览器端前后端联调 | 未做 | B3 起每批前端验收都要求真起双端手工走查 | B3–B6 |
| `main.py` 单文件、`on_event` 弃用 | 技术债 | B1 重构为 routers + lifespan | B1 |
| `sys.path.insert` 导入 | 技术债 | B1 改成可安装包（`pip install -e .`） | B1 |
| 无迁移工具 | 技术债 | B1 引入 Alembic | B1 |
| `agent_run.employee_key` 字符串 | 临时设计 | B3 加 `employee_id` 列并双写；M2 完成切换 | B3 |
| 无分页/统一错误格式 | 技术债 | B1 统一错误包络 + 分页依赖 | B1 |
| 前端仅 1 个页面 | 骨架 | B2–B5 按页面清单逐步落地 | B2–B5 |

---

## 4. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Alembic 基线在 SQLite 上 autogenerate 噪音大 | B1 超时 | 手工裁剪基线；写 schema diff 脚本做校验 |
| 组织图 React Flow 在 50+ 节点卡顿 | 体验 | 关闭动画、按部门折叠、必要时切换列表视图 |
| 三层权限交集语义歧义 | 安全 | 先写 12 组测试用例（表格驱动），实现按测试走；文档先定语义 |
| 派工打分主观 | 争议 | 权重常量 + 版本号 + 因子可见；M1 只做预览不做最终派发 |
| 导入导出数据一致性 | 数据损坏 | 单事务 + dry-run + 往返测试 |
| 真实连接测试消耗费用 | 成本 | `max_tokens=8`，`@pytest.mark.live` 默认跳过，仅手工执行 |

---

## 5. 需要你确认的 6 个决策点

| # | 决策 | 我的建议 |
|---|---|---|
| D-1 | M1 是否引入 shadcn/ui + TanStack Query + React Flow（3 个前端依赖） | **引入**（React Flow 已在你指定的技术栈里） |
| D-2 | 员工姓名是否要求同公司唯一 | **要求唯一**（避免派工歧义） |
| D-3 | 派工打分权重（0.30/0.20/0.20/0.15/0.15）是否接受 | 接受，后续可调但需升 `algorithm_version` |
| D-4 | M1 是否包含"员工软删除"（保留历史） | **包含**（硬删除会破坏审计） |
| D-5 | 提示词是否允许在 UI 里直接改历史版本 | **不允许**（只能新增/回滚） |
| D-6 | 导入冲突默认策略 | 默认 **rename（改名保留两者）**，不默认覆盖 |

---

## 6. 执行纪律（与你的约束逐条对应）

1. 每批开始前先读相关现有代码（B1 已列出要重构的文件清单）
2. 不删除、不改弱 M0 的 7 个测试断言
3. 不安装 Codex CLI / CrewAI / Docker / Playwright
4. 不要求提供除 DeepSeek 外的 Key
5. 不上传 GitHub（本地 commit 保留）
6. 每个功能：领域服务 → API → 测试 → 前端，四件齐了才算完成
7. 每批结束提交一次可回滚的 commit，并在 `CHANGELOG.md` 记录
