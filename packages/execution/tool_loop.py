"""工具循环（M3-A）：让 M2 的"单次模型调用"升级为"受控的多轮工具调用"。

约束：
- 只把**已授权**的工具 schema 发给模型（模型不知道未授权工具存在）；
- 每次工具调用都走 `invoke_tool` 唯一入口；
- 最多 `max_tool_calls` 次（默认 8），超限抛 `TOOL_LOOP_EXCEEDED`；
- 需要审批时把 messages / 待执行调用 / call_index 写入 checkpoint 并挂起，
  审批通过后从**同一条调用**继续，不重新调用模型生成同一个 tool_call。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from packages.permissions.effective import compute_effective_permissions
from packages.persistence.models import Company, Employee, Task, TaskRun, ToolCall
from packages.shared.errors import DomainError
from packages.shared.types import UsageReport
from packages.tools.context import ToolContext
from packages.tools.invoke import invoke_tool
from packages.tools.policy import effective_tool_policy, visible_tools
from packages.tools.registry import model_schemas

DEFAULT_MAX_TOOL_CALLS = 8


class RunSuspended(Exception):
    """任务因工具审批挂起（不是失败，不能走失败收尾）。"""

    def __init__(self, approval_id: str | None = None):
        super().__init__("run suspended for tool approval")
        self.approval_id = approval_id


@dataclass
class ToolLoopResult:
    content: str
    usage: UsageReport | None
    tool_calls: int
    messages: list[dict]


def build_tool_context(
    session: Session,
    *,
    owner_id: str,
    task: Task,
    run: TaskRun | None,
    employee: Employee,
    step_id: str,
    request_id: str = "-",
) -> ToolContext:
    company = session.get(Company, task.company_id or employee.company_id)
    tool_policy = effective_tool_policy(company)
    permissions = compute_effective_permissions(session, owner_id, employee.id)["permissions"]
    return ToolContext(
        session=session, owner_id=owner_id, company=company, employee=employee,
        task=task, run=run, step_id=step_id, request_id=request_id,
        tool_policy=tool_policy, permissions=permissions,
    )


def authorized_tools(ctx: ToolContext) -> list[str]:
    return visible_tools(ctx)


def _merge_usage(items: list[Any]) -> UsageReport | None:
    usage = [item for item in items if item is not None]
    if not usage:
        return None
    costs = [item.cost_usd for item in usage]
    total_cost = None if any(cost is None for cost in costs) else round(sum(costs), 8)
    return UsageReport(
        model=usage[-1].model,
        prompt_tokens=sum(item.prompt_tokens for item in usage),
        completion_tokens=sum(item.completion_tokens for item in usage),
        cost_usd=total_cost,
        latency_ms=sum(item.latency_ms for item in usage),
    )


def _tool_message(call_id: str, name: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def _parse_arguments(raw: str) -> tuple[dict, str | None]:
    if not raw or not str(raw).strip():
        return {}, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"JSON 解析失败：{exc.msg}"
    if not isinstance(parsed, dict):
        return {}, "工具参数必须是 JSON 对象"
    return parsed, None


async def run_tool_loop(
    *,
    session: Session,
    task: Task,
    run: TaskRun,
    step: dict,
    employee: Employee,
    adapter: Any,
    system_prompt: str,
    instruction: str,
    checkpoint: dict,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> ToolLoopResult:
    ctx = build_tool_context(
        session, owner_id=task.owner_id, task=task, run=run, employee=employee,
        step_id=step["id"],
    )
    tools = authorized_tools(ctx)
    if not tools:
        raise DomainError(
            "TOOL_NOT_GRANTED", "员工没有可用的工具，不能进入工具循环", 403,
            {"employee_id": employee.id},
        )
    schemas = model_schemas(tools)
    max_tool_calls = max(1, min(int(max_tool_calls or DEFAULT_MAX_TOOL_CALLS), 20))

    state = checkpoint.get("tool_state") or {}
    resuming = bool(state) and state.get("step_id") == step["id"] and state.get("pending")
    usage_items: list[Any] = []
    call_index = 0
    iteration = 0

    if resuming:
        messages = list(state.get("messages") or [])
        call_index = int(state.get("call_index") or 0)
        iteration = int(state.get("iteration") or 0)
        pending = state["pending"]
        row = session.get(ToolCall, pending.get("tool_call_id") or "")
        if row is None:
            raise DomainError("TOOL_APPROVAL_REJECTED", "待执行的工具调用记录已丢失", 409)
        if row.status != "approved":
            raise DomainError(
                "TOOL_APPROVAL_REJECTED",
                f"工具调用未被批准（{row.status}），步骤终止",
                403, {"tool_call_id": row.id, "status": row.status},
            )
        ctx.approved = True
        ctx.tool_call_id = row.id
        outcome = await invoke_tool(
            ctx, row.tool_name, pending.get("args") or {}, call_index=call_index
        )
        ctx.approved = False
        ctx.tool_call_id = None
        messages.append(_tool_message(pending.get("call_id") or "call", row.tool_name, outcome.to_message()))
        call_index += 1
        iteration += 1
        checkpoint.pop("tool_state", None)
    else:
        messages = [{"role": "system", "content": system_prompt}]
        user_content = instruction if not step.get("input") else instruction
        messages.append({"role": "user", "content": user_content})

    while True:
        if call_index >= max_tool_calls:
            raise DomainError(
                "TOOL_LOOP_EXCEEDED",
                f"工具调用次数达到上限 {max_tool_calls}，已终止",
                409, {"max_tool_calls": max_tool_calls, "tool_calls": call_index},
            )
        response = await adapter.chat(messages, tools=schemas, tool_choice="auto")
        usage_items.append(response.get("usage"))
        calls = response.get("tool_calls") or []
        assistant_message = response.get("message") or {
            "role": "assistant", "content": response.get("content") or "",
        }
        if not calls:
            return ToolLoopResult(
                content=response.get("content") or "",
                usage=_merge_usage(usage_items),
                tool_calls=call_index,
                messages=messages,
            )

        messages.append({
            "role": "assistant",
            "content": assistant_message.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            if call_index >= max_tool_calls:
                raise DomainError(
                    "TOOL_LOOP_EXCEEDED",
                    f"工具调用次数达到上限 {max_tool_calls}，已终止",
                    409, {"max_tool_calls": max_tool_calls, "tool_calls": call_index},
                )
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            args, error = _parse_arguments(function.get("arguments") or "{}")
            call_id = str(call.get("id") or f"call_{call_index}")
            if error:
                messages.append(_tool_message(
                    call_id, name or "unknown",
                    f'<untrusted_tool_result>\n{{"status": "failed", "error": '
                    f'{{"code": "TOOL_ARGS_INVALID", "message": "{error}"}}}}\n</untrusted_tool_result>',
                ))
                call_index += 1
                continue

            ctx.call_index = call_index
            outcome = await invoke_tool(ctx, name, args, call_index=call_index)
            ctx.approved = False
            ctx.tool_call_id = None
            if outcome.suspended:
                checkpoint["tool_state"] = {
                    "step_id": step["id"],
                    "messages": messages,
                    "iteration": iteration,
                    "call_index": call_index,
                    "pending": {
                        "tool_call_id": outcome.tool_call_id,
                        "call_id": call_id,
                        "name": name,
                        "args": args,
                    },
                    "approval_id": outcome.approval_id,
                }
                raise RunSuspended(outcome.approval_id)

            messages.append(_tool_message(call_id, name, outcome.to_message()))
            call_index += 1

        iteration += 1
