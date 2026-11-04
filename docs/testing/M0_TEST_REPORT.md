# M0 测试报告

> 生成时间：2026-11-05（Asia/Shanghai）｜机器可读原始数据：`docs/testing/m0_results.json`
> 原则：只记录真实执行结果；PASS/FAIL/SKIP/BLOCKED 如实标注

## 1. 测试环境

| 项 | 值 |
|---|---|
| OS | Windows（win32），Git Bash |
| Python | 3.13.14（项目 venv：E:\AgentOS\.venv） |
| Node | v22.22.2 / npm 10.9.7 |
| 关键依赖 | litellm 1.108.0、langgraph 1.2.19、langgraph-checkpoint-sqlite 3.1.3、fastapi 0.162.0、sqlalchemy 2.1.8 |
| 网络 | 受限代理环境（raw.githubusercontent.com 超时；api.deepseek.com 可直连） |
| API Key | DEEPSEEK_API_KEY 已配置（用户提供）；其余供应商未配置 |

## 2. 验证项结果（执行命令：`python scripts/m0_verify.py`）

| # | 验证项 | 结果 | 关键证据 |
|---|---|---|---|
| V1 | LiteLLM → DeepSeek 真实调用 | ✅ **PASS** | 返回 `'1+1 等于 2。'`；tokens=16+8；cost=$0.0000072（真实计价）；延迟 1405ms |
| V2 | 第二供应商调用 | ⏭️ **SKIP** | 未配置第二家 Key（OPENAI/ANTHROPIC/GOOGLE/OPENROUTER 均空），如实标记不计失败 |
| V3 | AgentAdapter 接口与能力声明 | ✅ **PASS** | 8 项能力完整；file_ops/approval_hook 诚实为 False；不支持 interrupt 正确抛 CapabilityNotSupported |
| V4 | 双 Agent 顺序协作（研究员→审查员） | ✅ **PASS** | 真实交接：审查员输入即研究员产出全文；审查员输出结构化 JSON 结论 `pass` 并指出一处事实性风险（"checkpointing 依赖后端配置，存在夸大风险"）；task_state=review_passed；落库 task/task_run/agent_run×2/usage_record×2 |
| V5 | LangGraph interrupt 审批暂停/恢复 | ✅ **PASS** | 图在审批点真实挂起（`__interrupt__`），外部 `Command(resume={approved:False})` 恢复后 result=rejected、decided_by=user；SqliteSaver 持久化 checkpoint |
| V6 | 执行记录持久化与重启保留 | ✅ **PASS** | 写入失败任务样例 → dispose 引擎 → 全新引擎重开 → 记录完整，error 字段非空；多次 run 不覆盖（另有单元测试） |
| V7 | Codex CLI headless | ⛔ **BLOCKED** | 未检测到 codex 可执行文件；解除条件：用户授权 `npm i -g @openai/codex` + ChatGPT/API 认证 |
| V8 | CrewAI 对照实验 | ⏭️ **SKIP** | crewai 未安装（可选依赖）；按需补做 |

**统计：PASS 5 / FAIL 0 / SKIP 2 / BLOCKED 1**

## 3. 补充实测（验证脚本之外）

| 项 | 命令/方式 | 结果 |
|---|---|---|
| 单元测试 | `pytest tests/ -v` | **7/7 通过**（能力诚实性、interrupt 异常、事件序列化、cost=None 诚实、多 run 不覆盖、重启保留） |
| Lint | `ruff check apps packages scripts tests` | **全部通过** |
| FastAPI 骨架 | `uvicorn apps.api.main:app` + curl | `/api/tasks` 返回真实库中 2 条任务记录（含 V4 协作任务）；`/api/employees/deepseek/deepseek-chat/health` 返回 `{"ok":true,"detail":"deepseek/deepseek-chat 可达"}`（经 API 的真实模型连通性测试） |
| 前端骨架 | `npm install` + `npm run build`（apps/web） | **构建通过**（tsc + vite build，141.28 kB JS / 7.14 kB CSS，0 漏洞） |
| Git | `git init` + 首个 commit | 已提交全部 M0 产物 |

## 4. 失败项

无。（首轮 V5 因 `data/` 目录未创建报 OperationalError，已修复为自动建目录并重跑通过——记录于此以示过程真实。）

## 5. 未测试项（如实声明）

1. **V2 第二供应商**：无 Key，未测。LiteLLM 多供应商能力有官方文档支撑【官方文档结论】，但本环境未实测
2. **V7 Codex CLI**：未安装未测；Adapter/CLI Runtime 为纸面设计 + 官方文档调研结论
3. **V8 CrewAI 对照**：未执行；LangGraph 选型主要依据调研 + V5 实测，缺 CrewAI 同任务对照数据
4. **并行任务、预算护栏、WebSocket 推送**：M0 范围外，未测
5. **前端与后端联调**：前端构建通过、后端接口实测通过，但浏览器端实际联调未做（需起双端服务，M1 进行）
6. **LiteLLM 故障回退（fallbacks）**：代码路径已实现，未做真实故障注入测试
7. **Windows Job Object 子进程树终止**：设计阶段，未测（CLI Runtime 依赖项）

## 6. 费用声明

本次 M0 验证 DeepSeek 实际调用 3 次（V1×2、V4 一次含 2 次模型调用、API health×1），合计消耗 < 0.001 美元（以 V1 单次 $0.0000072 为参照量级）。
