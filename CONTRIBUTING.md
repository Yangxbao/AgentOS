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
