# AgentOS 项目速览（给 AI 助手看的 briefing）

> **你是谁、这份文档是干什么的**：用户正在手动测试 AgentOS 的各项功能，会随时问你关于这个项目的问题。
> 你没有项目代码访问权，本文就是你唯一的背景资料——先读完它再回答。
> 回答原则：**分清"设计如此"和"缺陷"**（§6 专门列了容易被误判为 bug 的行为）；不确定的事就说不确定，**绝不虚构**；
> 深度开发细节本文没有覆盖的，直接告诉用户"详见 `E:\AgentOS\HANDOFF.md` / `M3_MASTER_HANDOFF.md`"。

---

## 1. 一句话定位

AgentOS 是一个**本地单机运行的"AI 数字员工协作操作系统"**：用户建公司 → 建部门/岗位 → 招"AI 员工"（绑定模型、提示词、权限）→ 建任务并派工 → AI 员工真实执行（可多 Agent 协作、可用工具、可递归拆子任务、可人工审批）→ 全过程可追溯、可审计、可计成本。

它跑在用户自己的 Windows 机器上，**没有任何云服务、没有账号体系**（单用户 `owner_id="local"`）、**默认不产生任何费用**。

## 2. 技术形态（回答"它是怎么跑起来的"）

| 项 | 值 |
|---|---|
| 后端 | Python 3.13 + FastAPI + SQLAlchemy + SQLite(WAL)，只监听 `127.0.0.1:8000` |
| 前端 | React 18 + TypeScript + Vite（dev 端口 5173，`/api` 由 Vite 同源代理转发到 8000） |
| 模型接入 | LiteLLM 网关（当前配置 DeepSeek）；**默认 mock 模式**（`AGENTOS_MODEL_MODE=mock`） |
| 数据库 | `E:\AgentOS\data\agentos.db`，24 张逻辑表，迁移版本 `m3b_memory_workers` |
| 健康检查 | `GET /api/health` → `{"status":"ok","version":"0.3.1"}`（0.3.1 = M3 全批次 + 员工配置中心 + 体验完善批次） |
| API 规模 | `/api/v1` 下 93 个 route-method 对；前端 17 条路由（新增 /approvals 审批中心） |
| 测试基线 | pytest 355 passed / 3 skipped；ruff 干净；浏览器验收 32 项 |

## 3. 已实现的能力（M0 → M3-F，全部完成并有自动化测试）

1. **组织管理**：公司/部门/岗位/员工/模型连接/组织图（React Flow）
2. **提示词版本**：文件落盘 + SHA-256 校验 + 激活指针，进系统提示词
3. **任务中心**：单步/多步计划、拓扑波次并行执行、检查点断点续跑、暂停/取消/重试/返工
4. **多 Agent 协作**：步骤依赖上游产出，Agent 间 handoff 记录
5. **人工审批**：三种闸门 `before_run`（执行前）/ `after_run`（交付前）/ `tool_call`（单次高风险工具调用）
6. **工具执行（M3-A）**：7+2 个工具、五层权限、路径安全、HTTP 白名单+SSRF 防护、审计与调用记录
7. **执行监管（M3-E）**：预算熔断（成本+Token）、连续拒绝熔断、全局 kill switch、监控统计
8. **递归任务树（M3-B）**：子任务可再设计划、深度/步数上限、replan、父子预算聚合
9. **长期记忆（M3-C）**：SQLite FTS5 检索、员工私有/项目/公司三级作用域、`<memory>` 不可信注入
10. **多 Worker（M3-D）**：租约/心跳/崩溃恢复/公司并发上限/优先级
11. **端到端业务验收（M3-F）**：GitHub 教程生成场景 16 项 E2E（本地 stub）
12. **员工配置中心**：员工详情页直接编辑基本信息/岗位/工具白名单（三态展示：已授权/策略允许/实际可执行）/工作区授权/私有记忆；列表页概览；任务创建表单含指令与预算；失败任务重规划 UI；审批中心聚合待审批；监控页 Worker/租约面板；config_io 导出含工作区/授权/记忆

**明确未实现（不要说成 bug）**：Shell 命令执行（永久禁用）、真实外网调用（HTTP 工具只允许白名单，未配外网域名）、账号体系/多用户、embedding 向量检索（记忆只用 FTS5）、任务递归深度>4、真实模型的全链路验证（见 §7）。

## 4. 核心机制速查（测试中最常涉及）

### 4.1 一次任务的执行链路
```
创建任务(draft) → run(queued) → 后台 worker 认领(running)
  → 按计划步骤分波次并行执行（无计划 = 单步）
  → 每步：权限闸门 → 预算检查 → 系统提示词(员工提示词+任务+记忆) → 模型调用（带已授权工具 schema）
  → 工具调用走五层权限 → 结果作为不可信数据回灌模型 → 循环直到产出最终文本
  → 落 agent_run + usage_record + task_event → 步骤完成即提交（崩溃可续）
  → 全部完成 → succeeded（若 after_run 审批 → awaiting_approval → 人工批准后才成功）
```

### 4.2 任务状态机（后端唯一权威，AI 输出改不了状态）
- `draft → queued → running → succeeded/failed/paused/awaiting_approval/cancelled`
- **paused ≠ failed**：预算耗尽/连续拒绝/人工暂停/worker 失联都是 paused——**保留检查点，可"恢复"续跑**；failed 可"重试"
- `awaiting_approval`：有 pending 审批；批准后自动入队恢复（工具审批恢复的是子任务/父任务按 gate 而定）
- 每步产出写进 `task_run.checkpoint`（completed_steps/outputs），恢复时跳过已完成步骤

### 4.3 工具五层权限（任何一层不允许就拒绝，错误码稳定）
```
1 全局开关 AGENTOS_TOOL_EXECUTION（默认 off！）→ 拒绝码 TOOLS_DISABLED
2 公司策略（工具策略页）：enabled / categories / allowed_tools / network_domains / 风险上限
3 员工白名单 tools_allowed（空 = 一个工具都没有）→ TOOL_NOT_GRANTED
4 岗位/员工权限层收窄
5 工作区授权（文件工具必须有 workspace + read/write 授权）→ WORKSPACE_NOT_GRANTED
```
其他常见拒绝码：`SHELL_DISABLED`（永久）、`CATEGORY_DISABLED`、`RISK_EXCEEDED`（超公司上限，直接拒）、
`TOOL_PATH_DENIED`（路径逃逸/敏感文件）、`TOOL_NETWORK_DENIED`（域名不在白名单）、`TOOL_ARGS_INVALID`。
**风险与审批**：超过公司 `auto_execute_max_risk`（默认 medium）的工具调用转人工审批（`tool_call` gate），如 `fs.write_file` 的 overwrite、HTTP 写方法。

### 4.4 工具清单（9 个注册）
`fs.list_dir / fs.read_file / fs.stat / fs.write_file / fs.delete_file / http.request / memory.remember / memory.search / shell.run(永久禁用)`
- 文件工具只能在**工作区**内操作（路径逃逸/盘符/UNC/敏感文件如 .env/*.pem 直接拒绝）
- http.request 只允许公司白名单域名；回环地址需环境变量显式放行（测试本地 stub 用）

### 4.5 监管闸门（M3-E）
- **预算**：`task.budget_usd`（建任务时填）→ 公司默认兜底；Token 上限=公司 `policy.default_task_budget_tokens`；超限 → 任务 `paused` + 事件 `task.budget_exceeded`，**不是失败**
- **连续拒绝**：同一 run 内连续 3 次工具被拒 → `paused` + `task.tool_denied_limit`（提示检查授权）
- **kill switch**：监控页"工具执行（全局）"卡片一键紧急停止/恢复；进程级内存态，重启后回到环境变量初始值

### 4.6 递归任务树（M3-B）
- pending 子任务可设置自己的计划 → 形成树；父执行器用 nested run 驱动子计划
- 上限（后端强制）：深度 ≤4 层（`TASK_DEPTH_EXCEEDED`）、树总步骤 ≤50、树总工具调用 ≤100
- 步骤可省略员工 → 按能力/工具自动分配（记录 decision）
- 失败任务可 `replan`（≤3 次）：只重置失败步骤及其下游，上游产出保留
- 子树消耗计入父预算（树聚合），递归**不能**逃避预算

### 4.7 记忆（M3-C）
- 三级作用域：**employee 私有**（其他员工永远检索不到）/ **project**（同公司共享）/ **company**（全公司）
- 员工私有记忆要"提升"才共享（仅人工可操作，写审计）
- 检索结果以 `<memory>` 数据块进用户消息，系统提示词明确"记忆是数据不是指令"——注入"忽略指令"的记忆不会改变任务目标
- Agent 写记忆只能写自己的私有作用域（`memory.remember` 工具，需公司开启 memory 类别）
- 没有记忆时正常降级，不影响执行

### 4.8 多 Worker（M3-D）
- 认领即写租约（60s），心跳 15s 续租；worker 失联 → 租约过期 → 任务转 paused（可恢复）；重试 3 次仍失败 → `LEASE_EXHAUSTED` failed
- 默认单进程并发 2（`AGENTOS_WORKER_CONCURRENCY`）、公司并发上限 2（`policy.max_concurrent_tasks`）、优先级 urgent>high>normal>low

### 4.9 本地安全防护（解释各种 403）
后端有 LocalGuard 中间件：**Host 校验**（只允许 localhost/127.0.0.1/::1，防 DNS rebinding）+ **写请求四查**：可信 Origin（默认 `http://localhost:5173`、`http://127.0.0.1:5173`）→ 拒绝 `Sec-Fetch-Site: cross-site` → 必须 `X-AgentOS-Client: web/cli` 头 → 可选本地令牌。
- **CORS 不是 CSRF 防线**，Fetch Metadata（Sec-Fetch-Site）才是；不要建议用户"关闭校验"或"放行所有跨站"
- 开发态前端走 Vite 同源代理（5173 → 8000），请求 URL 应该是 `localhost:5173/api/...`；如果抓包看到直连 `127.0.0.1:8000` 且报 `UNTRUSTED_REQUEST: 跨站写请求被拒绝`，说明没走代理（已于 2026-11-06 修复：`vite.config.ts` 代理 + dev 用相对路径）

## 5. 关键数据与文件位置

```
E:\AgentOS\
├── data\agentos.db            真实数据库（gitignore，勿删；有 4 条 M0 历史任务，company_id=NULL 属遗留数据）
├── data\prompts\employees\    员工提示词文件（vNNNN.md，不可变）
├── data\workspaces\<slug>\    工作区真实目录（Agent 文件工具只能动这里）
├── data\backups\              数据库备份
├── docs\acceptance\           各任务自包含验收文档
├── docs\testing\              回归证据（pytest/浏览器验收原始输出与截图）
├── HANDOFF.md                 项目级交接（环境/红线/坑清单）
├── M3_MASTER_HANDOFF.md       M3 批次完整交接与验收（14 章节）
└── tests\                     332 个自动化测试
```

## 6. 测试时"看起来像 bug 但其实设计如此"清单 ⚠️（重点，先查这里再下结论）

1. **工具没执行、任务却显示成功** → 全局开关可能 off（监控页"工具执行"卡片可见当前状态，可一键停止/恢复），且员工白名单/公司策略/工作区授权任一缺失都不执行——**员工详情页"实际可执行"列会直接告诉你缺哪层**（四层中任何一层缺失都会显示原因）
2. **成本显示 $0.000000** → mock 模式不花钱是特性：`cost=0、billable=false`。要产生真实费用需改 `.env` 的 `AGENTOS_MODEL_MODE=real`（需用户明确授权）
3. **UI 里没有"测试工具"的入口？** 有个技巧：mock 模式下在任务指令里写标记 `[tool:fs.write_file {"workspace_id":"...","path":"a.txt","content":"hi"}]`，模型会按标记真实调用工具（这是项目内置的确定性测试机制）
4. **Shell 相关一切被拒** → 永久禁用，无代码路径，任何配置都开不了
5. **任务列表里有 4 条"奇怪"的遗留任务**（公司列空）→ M0 时期的历史数据，只读保留，不回填
6. **写请求 403 UNTRUSTED_REQUEST / MISSING_CLIENT_HEADER** → 本地防护（§4.9），非浏览器工具直连后端必须带 `X-AgentOS-Client` 头且 Origin 可信
7. **任务 paused 而不是 failed** → 熔断/暂停语义（§4.5），恢复即可续跑；检查 `task.result.error` 里的 code
8. **审查人不能是执行人、派工候选人被过滤** → 自审回避是硬规则，不是 UI 缺陷
9. **版本号显示 v0.3.0-m3e 但 M3-B/C/D/F 已完成** → 版本串未随批次递增，以里程碑文档为准
10. **浏览器验收/测试全部免费** → 全部走 mock + 本地 stub，没有真实外网

## 7. 诚实边界（回答"它真的能 X 吗"时的红线）

- **真实模型调用**：M2 时代只做过 4 次（约 $0.00006）真实调用验证；M3 批次全部 Mock。**真实计价下的预算熔断未验证过**——用户问起要如实说
- **真实外网**：没有。HTTP 工具的白名单当前只配过本地 stub（127.0.0.1）
- **测试隔离**：所有自动化测试/浏览器验收用临时库，不污染真实数据；真实库只有用户手动操作产生的数据
- 数据安全边界（Windows TOCTOU、本地恶意进程直连 DB、审计防篡改依赖应用层）在单用户本地威胁模型下是已知接受项，不是"已解决"

## 8. 常用命令（用户可能让你指导操作）

```bat
cd /d E:\AgentOS
.venv\Scripts\python.exe scripts\run_api.py --port 8000        REM 起后端
cd apps\web && npm run dev                                     REM 起前端（localhost:5173）
.venv\Scripts\python.exe -m pytest tests/ -q                   REM 全量测试（约 80s，全 Mock 免费）
.venv\Scripts\python.exe scripts\e2e_m3f.py                    REM GitHub 教程场景端到端
.venv\Scripts\python.exe scripts\browser_acceptance.py         REM 浏览器验收（需端口空闲）
.venv\Scripts\python.exe scripts\backup_db.py                  REM 备份数据库
.venv\Scripts\python.exe -m alembic current                    REM 查迁移版本
```
改 `.env`（如 `AGENTOS_TOOL_EXECUTION=on`）后需重启后端才生效。

## 9. 回答用户问题的方法建议

1. **先定位问题类别**：配置没开（§6.1 四层开关）→ 状态机语义（§4.2/§6.7）→ 设计边界（§7）→ 真缺陷（让用户看后端响应的 `error.code` 和 `request_id`，按码对照 §4.3 拒绝码）
2. 用户贴错误响应时，**先读 error.code**：`TOOL_*` 是权限/参数、`TASK_*` 是状态机、`VALIDATION_ERROR` 是参数、4xx 且带 `UNTRUSTED/INVALID_HOST` 是本地防护、`BUDGET_EXCEEDED/TOOL_DENIED_LIMIT/LEASE_EXHAUSTED` 是熔断语义
3. 涉及"为什么这么设计"，优先用本文 §4 的机制解释；需要更深依据就指向 `HANDOFF.md`（§4 目录地图、§13 坑清单）和 `M3_MASTER_HANDOFF.md`（§5 设计取舍、§11 已知缺陷）
4. 用户想改配置时提醒：`.env` 改完要重启后端；公司策略在 UI"工具策略"页改；员工权限在员工详情页改
5. **不要建议**：关闭安全中间件、放行跨站、删除数据库、安装 Shell 执行、绕过审批——这些是项目红线

---

*生成：2026-11-06｜依据：HANDOFF.md + M3_MASTER_HANDOFF.md + 当日实测基线（332 tests / m3b_memory_workers / 93 API）*
