# CLI Runtime 设计

> v0.1｜2026-11-05｜packages/cli-runtime
> 核心约束（红线）：CLI 必须经官方允许接口接入；受控子进程或官方 SDK；禁止拼接用户输入进 shell 命令；禁止默认允许任意终端命令

## 1. 职责

把 Codex / Claude Code / Gemini CLI / Copilot SDK / 自定义 CLI 包装为 AgentAdapter 实现：
1. 进程生命周期管理（spawn / 监控 / 终止）
2. 事件协议解析（JSONL 优先）
3. 沙箱与审批档位映射
4. 会话持久化引用（external_ref）

## 2. 进程模型【设计】

```
CLIProcess
├─ 启动: subprocess.Popen(argv: list[str], shell=False, creationflags=CREATE_NEW_PROCESS_GROUP|CREATE_SUSPENDED?)
│   - argv 数组传参，永不经过 cmd/sh
│   - cwd = 用户授权的工作空间根（越界拒绝）
│   - env = 白名单环境变量（PATH/SystemRoot + CLI 必需的认证变量），不继承全部环境
│   - Windows Job Object：限制子进程树，kill 时整树终止，防止孤儿进程【未验证，M0/M2 实测】
├─ 通信: stdout=PIPE(JSONL 事件) / stderr=PIPE(进度诊断) / stdin=PIPE(仅协议需要时)
├─ 监控: 看门狗（超时、输出速率异常=疑似死循环、内存上限）
└─ 终止: interrupt → 先发 CLI 官方中断（如有）→ TerminateJobObject 兜底
```

## 3. CLI 描述符（自定义 CLI 接入契约）

```yaml
# cli_registry/codex.yaml 示例
kind: codex
binary: codex
version_probe: ["--version"]
auth_probe: ["exec", "--help"]        # 官方探测方式
exec:
  argv: ["exec", "--json", "-C", "{workspace}"]
  prompt_via: argv_tail               # argv_tail | stdin
  sandbox_flag: ["--sandbox", "{level}"]
events:
  format: jsonl
  mapping:
    started: "thread.started"
    completed: "turn.completed"
    failed: "turn.failed"
usage:
  from_event: "turn.completed"
capabilities:
  streaming: true
  session_resume: true
  approval_hook: false     # exec 模式不可交互 → 前置授权策略
```

新 CLI = 一个描述符 + （必要时）一个 Python 适配类。描述符由管理员审核后启用——**用户自定义 CLI 视为不可信执行体，默认 read-only 沙箱**。

## 4. 沙箱档位映射【设计，依据 codex 三档模型【已验证】】

| AgentOS 权限档 | Codex | Copilot | 自定义 CLI |
|---|---|---|---|
| L0 只读分析 | read-only | 工具白名单只读集 | 默认 |
| L1 工作空间可写（审批后） | workspace-write | permission handler 逐项批 | 需审批计划 |
| L2 受限网络 | workspace-write + network_access | 同左 | 默认禁止 |
| L3 完全访问 | danger-full-access | 不提供 | **AgentOS 永不自动授予，仅用户显式单次批准** |

## 5. 防失控措施

1. **输出速率看门狗**：事件频率超阈值 → 判定异常循环 → interrupt + 人工介入（红线 14/15）
2. **时长上限**：单次 agent_run 硬上限（默认 30min，可配）
3. **Token/成本上限**：usage 事件累计超 task 预算 → cancel → task 置 over_budget
4. **命令审查**：CLI 欲执行的 shell 命令（Codex `item.command_execution` 事件可见）经规则匹配，高危命令（rm -rf、格式化、注册表、Defender 操作等黑名单 + 未白名单）→ 转审批
5. **日志脱敏**：事件落库前正则脱敏 `sk-*`、Bearer token、常见 key 模式（红线 9）

## 6. M0 验证项

| 项 | 方法 | 状态 |
|---|---|---|
| 描述符驱动 spawn codex exec | 需用户安装 Codex + 授权 | ⚠️ 被阻塞 |
| JSONL 解析 → 统一 AgentEvent | 可用录制的样例 JSONL 做单元测试（不等安装） | 待执行 |
| 子进程终止树 | 用 ping/长眠进程实测 Job Object | 待执行 |
