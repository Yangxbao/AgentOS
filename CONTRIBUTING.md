# 贡献指南

感谢关注 AgentOS！项目处于 M0 早期阶段。

## 基本原则

1. **先分析，再实施**；先阅读现有代码，再修改
2. 小步提交，每个功能配测试
3. 不用假数据冒充真实功能；不隐藏失败的测试
4. 安全红线（见 docs/architecture/SECURITY_MODEL.md）不可违背
5. 文档与代码同步更新；结论区分"已验证事实 / 官方文档结论 / 设计建议 / 未验证假设"

## 开发环境

- Python 3.11+ / Node 18+
- `pip install -r requirements.txt` + `pip install -r requirements-dev.txt`
- 测试：`pytest tests/`
- 代码风格：ruff（配置见 pyproject.toml）

## 提交

- 提交信息：`type(scope): description`，type ∈ feat/fix/docs/test/refactor/chore
- PR 需通过 CI（lint + test）

## 第三方代码

不得将许可证不兼容的第三方代码直接复制进本仓库；依赖通过包管理引入。

---

## 🤝 欢迎加入共创

AgentOS 的目标是**让每个人都能拥有并经营自己的 AI 公司**——这一个人跑不完，每一个 PR 都有意义。

### 适合新贡献者的方向（good first issue）

| 方向 | 说明 | 上手点 |
|---|---|---|
| UI 中文化补全 | 把残留的技术文案换成用户语言 | `apps/web/src/pages/` |
| 错误提示优化 | 错误码 → 用户语言的映射表扩充 | `apps/web/src/pages/TaskDetailPage.tsx` |
| 组织图交互 | 节点样式、拖拽、导出图片 | `apps/web/src/pages/OrgPage.tsx` |
| 新工具扩展 | 在五层权限框架内增加工具族（表格/图表/数据库只读查询） | `packages/tools/registry.py` |
| 文档与翻译 | 用户手册、教程、英文 README | `docs/` |

### 三条铁律（不可协商）

1. **每个功能配测试**——测试必须真实执行，不允许为变绿删断言
2. **不用假数据冒充真实功能**——Mock 与真实调用必须可区分（`billable=false`）
3. **安全红线不可违背**——见 [docs/architecture/SECURITY_MODEL.md](docs/architecture/SECURITY_MODEL.md)：不加 Shell 执行路径、不放宽五层权限、密钥不落库

### 提交流程

1. Fork → 建 feature 分支
2. 开发（领域层不依赖 FastAPI；路由层不写业务逻辑；注释中文、标识符英文）
3. `pytest tests/ -q` + `ruff check apps packages scripts tests migrations` + `cd apps/web && npm run build` 全绿
4. PR 描述写清楚：改了什么 / 为什么 / 怎么验证

> 每个功能都源自真实实验暴露的问题——欢迎带着你的实验数据来提 issue。
