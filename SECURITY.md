# 安全政策

## 报告漏洞

请勿通过公开 Issue 报告安全漏洞。请通过 GitHub 的 Private Vulnerability Reporting 或项目 Discussion 中提供的联系方式私下报告。我们会在 72 小时内响应。

## 支持版本

| 版本 | 支持状态 |
|---|---|
| M0（开发中） | 尚未发布，仅最新 main 分支 |

## 安全设计基线

AgentOS 处理用户密钥、文件系统与终端命令，安全模型见 [docs/architecture/SECURITY_MODEL.md](docs/architecture/SECURITY_MODEL.md)。核心红线包括：默认最小权限、高危操作人工审批、密钥不明文落日志、Agent 永不自批、本地文件默认不上传云端。
