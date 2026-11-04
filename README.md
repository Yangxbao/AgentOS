# AgentOS

**AI 数字员工协作操作系统** — 像经营一家真实公司一样，组建、管理并交付成果的 AI 团队。

不是多 AI 群聊工具。每个 AI 员工有自己的身份、岗位、能力、职责和权限；不同 AI 可以协作也可以互相质疑；开发员必须接受测试员的独立验证；**用户始终拥有最终控制权**。

> 当前状态：**M0 — 技术调研与最小技术验证**（见 [M0_FINAL_HANDOFF.md](M0_FINAL_HANDOFF.md)）

## 特性（按里程碑推进）

- 🏢 **AI 公司组织**：自定义公司/部门/岗位/上下级，可视化组织图
- 👤 **AI 员工中心**：员工与模型解耦，主备模型、工具授权、绩效评估
- 🔌 **多模型接入**：API（LiteLLM 统一 100+ 供应商）+ CLI（Codex / Copilot 等官方接口）
- 📋 **任务调度**：CEO 拆解任务、依赖 DAG、暂停/恢复/取消/重试、人工接管
- 🔍 **AI 监督**：独立审查、跨模型交叉审查、结构化审查报告、自动返工
- ✅ **人工审批**：高危操作逐项审批，Agent 永不自批
- 💰 **成本绩效**：按员工归因 Token/费用/通过率
- 🏠 **本地优先**：Windows 本地完整运行，云端为可选增强

## 文档

| 类别 | 入口 |
|---|---|
| 产品 | [docs/product/PRD.md](docs/product/PRD.md) · [功能矩阵](docs/product/FEATURE_MATRIX.md) |
| 调研 | [竞品分析](docs/research/COMPETITOR_ANALYSIS.md) · [技术对比](docs/research/TECHNOLOGY_COMPARISON.md) · [选型决策](docs/research/PROJECT_SELECTION.md) |
| 架构 | [系统架构](docs/architecture/SYSTEM_ARCHITECTURE.md) · [数据库](docs/architecture/DATABASE_DESIGN.md) · [Agent Adapter](docs/architecture/AGENT_ADAPTER.md) · [CLI Runtime](docs/architecture/CLI_RUNTIME.md) · [安全模型](docs/architecture/SECURITY_MODEL.md) · [本地-云端](docs/architecture/LOCAL_CLOUD_ARCHITECTURE.md) |
| M1 计划 | [M1_PLAN_HANDOFF.md](M1_PLAN_HANDOFF.md)（单文档：PRD/数据模型/API/前端/解耦/派工/安全/分批验收全在此） |
| 开发 | [路线图](docs/development/ROADMAP.md) · [里程碑验收](docs/development/MILESTONE_ACCEPTANCE.md) · [ADR](docs/decisions/ADR_INDEX.md) |
| 测试 | [M0 测试报告](docs/testing/M0_TEST_REPORT.md) |

## 快速开始（M0 骨架）

```bash
# 后端
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # 填入 DEEPSEEK_API_KEY
uvicorn apps.api.main:app --reload --port 8000

# 前端
cd apps/web && npm install && npm run dev

# M0 技术验证
python scripts/m0_verify.py
```

## 许可证

[MIT](LICENSE)
