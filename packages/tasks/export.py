"""任务导出（M4 前置打磨）：聚合任务全生命周期数据，输出 JSON / Markdown。

设计要点：
- 数据与 /tasks/{id} 明细 + /timeline + /plan-revisions + /usage 同源，不发明新口径；
- Markdown 面向人工审阅与归档（agent_run 输出截断，工具/审批/时间线全量保留）；
- 密钥与敏感值沿用各 serialize 链路的既有脱敏，不在此重复处理。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from packages.execution.observability import runs_of_task, task_timeline, task_usage
from packages.tasks import service

_AGENT_OUTPUT_LIMIT = 2000


def build_export(session: Session, owner_id: str, task_id: str) -> dict:
    task = service.get_task(session, owner_id, task_id)
    data = service.serialize_task(task)
    data["children"] = [service.serialize_task(child) for child in service.children_of(session, task_id)]
    data["runs"] = runs_of_task(session, owner_id, task_id)
    data["timeline"] = task_timeline(session, owner_id, task_id)
    data["plan_revisions"] = service.plan_revisions_of(session, owner_id, task_id)
    data["usage"] = task_usage(session, owner_id, task_id)
    return data


def _cell(value) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _plan_table(data: dict) -> list[str]:
    steps = (data.get("plan") or {}).get("steps") or []
    if not steps:
        return ["（无计划，单步执行）"]
    lines = [
        "| # | 执行人 | 指令 | 交付物 | 依赖 |",
        "|---|---|---|---|---|",
    ]
    for index, step in enumerate(steps, start=1):
        lines.append(
            f"| {index} | {_cell(step.get('employee_name') or step.get('employee_id') or '—')} "
            f"| {_cell(step.get('instruction') or step.get('title') or '')} "
            f"| {_cell(step.get('deliverable') or '—')} "
            f"| {_cell(', '.join(step.get('depends_on') or []) or '—')} |"
        )
    return lines


def _usage_table(data: dict) -> list[str]:
    usage = data.get("usage") or {}
    lines = [
        f"- 模型调用：{usage.get('calls', 0)} 次；Token：{usage.get('total_tokens', 0)}"
        f"（入 {usage.get('total_prompt_tokens', 0)} / 出 {usage.get('total_completion_tokens', 0)}）",
        f"- 成本：${usage.get('total_cost_usd', 0)}"
        + (f"（另有 {usage.get('unknown_cost_records')} 条计价失败记录）" if usage.get("unknown_cost_records") else ""),
    ]
    by_model = usage.get("by_model") or []
    if by_model:
        lines += ["", "| 模型 | 调用 | Token | 成本 |", "|---|---|---|---|"]
        for row in by_model:
            tokens = f"{row.get('prompt_tokens', 0)}+{row.get('completion_tokens', 0)}"
            lines.append(
                f"| {_cell(row.get('model'))} | {row.get('calls', 0)} | {tokens} "
                f"| ${row.get('cost_usd', 0)} |"
            )
    return lines


def to_markdown(data: dict) -> str:
    """把 build_export 的结果渲染成中文 Markdown 报告。"""
    task_title = data.get("title") or data.get("id") or "任务"
    lines: list[str] = [f"# 任务报告：{task_title}", ""]

    meta = [
        ("任务 ID", data.get("id")),
        ("状态", data.get("state")),
        ("优先级 / 风险", f"{data.get('priority', '—')} / {data.get('risk_level', '—')}"),
        ("执行模式", data.get("execution_mode")),
        ("执行员工", (data.get("employees") or {}).get(data.get("assignee_employee_id") or "", {}).get("name")
         or data.get("assignee_employee_id") or "未派工"),
        ("审查员工", (data.get("employees") or {}).get(data.get("reviewer_employee_id") or "", {}).get("name")
         or data.get("reviewer_employee_id") or "本地用户"),
        ("预算", f"${data.get('budget_usd')}" if data.get("budget_usd") is not None else "公司默认"),
        ("创建 / 开始 / 结束", " / ".join(
            (data.get(key) or "—") for key in ("created_at", "started_at", "ended_at")
        )),
    ]
    lines += ["## 基本信息", ""]
    lines += [f"- **{label}**：{value}" for label, value in meta]
    if data.get("parent_task_id"):
        lines.append(f"- 父任务：`{data['parent_task_id']}`（深度 {data.get('depth', 0)}）")

    lines += ["", "## 目标", ""]
    if data.get("objective"):
        lines += [data["objective"], ""]
    if data.get("instruction"):
        lines += [f"**指令**：{data['instruction']}", ""]
    if data.get("deliverable"):
        lines += [f"**交付物**：{data['deliverable']}", ""]

    lines += ["## 计划", ""] + _plan_table(data)

    lines += ["", "## 执行记录", ""]
    runs = data.get("runs") or []
    if not runs:
        lines.append("（尚未执行）")
    for run in runs:
        lines.append(
            f"### Run #{run.get('run_no')}（{run.get('state')}，{run.get('mode')}，触发：{run.get('trigger')}）"
        )
        if run.get("error"):
            lines.append(f"- 错误：{run['error']}")
        for agent in run.get("agent_runs") or []:
            output = agent.get("output") or {}
            content = str(output.get("content") or "")[:_AGENT_OUTPUT_LIMIT]
            lines.append(
                f"- **{agent.get('employee_name') or agent.get('employee_id') or '—'}**"
                f"（{agent.get('model') or 'mock'}，{agent.get('state')}）：{content or '（无输出）'}"
            )
            if agent.get("error"):
                lines.append(f"  - 错误：{agent['error']}")
        lines.append("")

    lines += ["## 成本", ""] + _usage_table(data)

    lines += ["", "## 审批记录", ""]
    approvals = [
        item for item in data.get("timeline") or [] if item.get("kind") == "approval"
    ]
    if not approvals:
        lines.append("（无审批）")
    for item in approvals:
        lines.append(
            f"- {item.get('at')} · {item.get('gate')} → **{item.get('status')}**"
            f"（决定人：{item.get('decided_by') or '—'}）{('：' + item['comment']) if item.get('comment') else ''}"
        )

    lines += ["", "## 工具调用", ""]
    tool_calls = [
        item for item in data.get("timeline") or [] if item.get("kind") == "tool_call"
    ]
    if not tool_calls:
        lines.append("（无工具调用）")
    for item in tool_calls:
        lines.append(
            f"- {item.get('at')} · `{item.get('tool')}` → {item.get('status')}"
            + (f"（{item['error_code']}）" if item.get("error_code") else "")
            + (f" {item.get('duration_ms')}ms" if item.get("duration_ms") is not None else "")
        )

    lines += ["", "## 子任务", ""]
    children = data.get("children") or []
    if not children:
        lines.append("（无）")
    for child in children:
        lines.append(f"- [{child.get('state')}] {child.get('title')}（`{child.get('id')}`）")

    lines += ["", "## 时间线", ""]
    for item in data.get("timeline") or []:
        summary = str(item.get("summary") or "")[:160]
        lines.append(f"- {item.get('at')} `{item.get('type')}` {summary}".rstrip())

    lines.append("")
    return "\n".join(lines)
