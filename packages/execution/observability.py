"""可观测性（M2-E）：时间线、Agent 执行详情、成本聚合、监控摘要。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import (
    AgentHandoff,
    AgentRun,
    Company,
    Employee,
    Task,
    TaskApproval,
    TaskEvent,
    TaskRun,
    ToolCall,
    UsageRecord,
)
from packages.shared.errors import DomainError
from packages.tools.policy import global_tools_enabled


def _task(session: Session, owner_id: str, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None or task.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"任务不存在：{task_id}", 404)
    return task


def serialize_run(run: TaskRun) -> dict:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "run_no": run.run_no,
        "trigger": run.trigger,
        "state": run.state,
        "mode": run.mode,
        "error": run.error,
        "worker_id": run.worker_id,
        "resumed_from_run_id": run.resumed_from_run_id,
        "approved_by": run.approved_by,
        "checkpoint": run.checkpoint or {},
        "started_at": iso_utc(run.started_at),
        "ended_at": iso_utc(run.ended_at),
        "heartbeat_at": iso_utc(run.heartbeat_at),
    }


def serialize_agent_run(row: AgentRun) -> dict:
    return {
        "id": row.id,
        "task_run_id": row.task_run_id,
        "employee_id": row.employee_id,
        "employee_name": row.employee_key,
        "role": row.role,
        "adapter_type": row.adapter_type,
        "model": row.model,
        "model_connection_id": row.model_connection_id,
        "step_id": row.step_id,
        "prompt_version": row.prompt_version,
        "state": row.state,
        "error": row.error,
        "input": row.input_payload,
        "output": row.output_payload,
        "external_ref": row.external_ref,
        "started_at": iso_utc(row.started_at or row.created_at),
        "ended_at": iso_utc(row.ended_at),
    }


def runs_of_task(session: Session, owner_id: str, task_id: str) -> list[dict]:
    _task(session, owner_id, task_id)
    runs = session.execute(
        select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.run_no)
    ).scalars().all()
    payload = []
    for run in runs:
        agents = session.execute(
            select(AgentRun).where(AgentRun.task_run_id == run.id).order_by(AgentRun.created_at)
        ).scalars().all()
        item = serialize_run(run)
        item["agent_runs"] = [serialize_agent_run(row) for row in agents]
        payload.append(item)
    return payload


def agent_run_detail(session: Session, owner_id: str, agent_run_id: str) -> dict:
    row = session.get(AgentRun, agent_run_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"执行记录不存在：{agent_run_id}", 404)
    data = serialize_agent_run(row)
    usage = session.execute(
        select(UsageRecord).where(UsageRecord.agent_run_id == row.id)
    ).scalars().all()
    data["usage"] = [
        {
            "model": item.model,
            "prompt_tokens": item.prompt_tokens,
            "completion_tokens": item.completion_tokens,
            "cost_usd": item.cost_usd,
            "latency_ms": item.latency_ms,
            "billable": item.billable,
        }
        for item in usage
    ]
    return data


def task_timeline(session: Session, owner_id: str, task_id: str) -> list[dict]:
    _task(session, owner_id, task_id)
    items: list[tuple[datetime, dict]] = []

    def ts(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    for event in session.execute(
        select(TaskEvent).where(TaskEvent.task_id == task_id)
    ).scalars().all():
        items.append((ts(event.ts), {
            "kind": "event", "type": event.type, "at": iso_utc(event.ts),
            "task_run_id": event.task_run_id, "payload": event.payload,
        }))
    for run in session.execute(
        select(AgentRun).join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .where(TaskRun.task_id == task_id)
    ).scalars().all():
        items.append((ts(run.started_at or run.created_at), {
            "kind": "agent_run", "type": "agent.run", "at": iso_utc(run.started_at or run.created_at),
            "agent_run_id": run.id, "step_id": run.step_id,
            "employee_id": run.employee_id, "employee_name": run.employee_key,
            "model": run.model, "state": run.state,
            "summary": (run.output_payload or {}).get("content", "")[:300],
        }))
    for approval in session.execute(
        select(TaskApproval).where(TaskApproval.task_id == task_id)
    ).scalars().all():
        items.append((ts(approval.created_at), {
            "kind": "approval", "type": f"approval.{approval.status}", "at": iso_utc(approval.created_at),
            "approval_id": approval.id, "gate": approval.gate, "status": approval.status,
            "decided_by": approval.decided_by, "comment": approval.comment,
        }))
    for call in session.execute(
        select(ToolCall).where(ToolCall.task_id == task_id)
    ).scalars().all():
        items.append((ts(call.created_at), {
            "kind": "tool_call", "type": f"tool.{call.status}",
            "at": iso_utc(call.ended_at or call.created_at),
            "tool_call_id": call.id, "tool": call.tool_name,
            "risk": call.risk_level, "status": call.status,
            "step_id": call.step_id, "employee_id": call.employee_id,
            "error_code": call.error_code, "duration_ms": call.duration_ms,
            "approval_id": call.approval_id,
            "summary": (call.output_summary or {}).get("path")
            or (call.output_summary or {}).get("url") or "",
        }))
    for handoff in session.execute(
        select(AgentHandoff).where(AgentHandoff.task_id == task_id)
    ).scalars().all():
        items.append((ts(handoff.created_at), {
            "kind": "handoff", "type": "agent.handoff", "at": iso_utc(handoff.created_at),
            "step_id": handoff.step_id, "from": handoff.from_agent_run_id,
            "to": handoff.to_agent_run_id, "summary": handoff.summary[:200],
        }))
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


def task_usage(session: Session, owner_id: str, task_id: str) -> dict:
    _task(session, owner_id, task_id)
    return usage_summary(session, owner_id, task_id=task_id)


def _parse_dt(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError("VALIDATION_ERROR", "时间参数必须是 ISO-8601", 422) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end and parsed.hour == 0 and parsed.minute == 0 and len(value) <= 10:
        parsed = parsed + timedelta(days=1)
    return parsed


def usage_summary(
    session: Session,
    owner_id: str,
    *,
    company_id: str | None = None,
    task_id: str | None = None,
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    stmt = (
        select(UsageRecord, AgentRun, TaskRun)
        .join(AgentRun, AgentRun.id == UsageRecord.agent_run_id)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .where(UsageRecord.owner_id == owner_id)
    )
    if company_id:
        stmt = stmt.where(Task.company_id == company_id)
    if task_id:
        stmt = stmt.where(TaskRun.task_id == task_id)
    if employee_id:
        stmt = stmt.where(UsageRecord.employee_id == employee_id)
    start, end = _parse_dt(date_from), _parse_dt(date_to, end=True)
    if start:
        stmt = stmt.where(UsageRecord.created_at >= start)
    if end:
        stmt = stmt.where(UsageRecord.created_at < end)

    rows = session.execute(stmt).all()
    by_employee: dict[str, dict] = defaultdict(lambda: {
        "employee_id": "", "employee_name": "", "prompt_tokens": 0,
        "completion_tokens": 0, "cost_usd": 0.0, "calls": 0,
    })
    by_model: dict[str, dict] = defaultdict(lambda: {
        "model": "", "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "calls": 0,
    })
    by_day: dict[str, dict] = defaultdict(lambda: {"date": "", "cost_usd": 0.0, "calls": 0})
    total_prompt = total_completion = 0
    total_cost = 0.0
    unknown_cost = 0
    records = []

    names = {
        employee.id: employee.name
        for employee in session.execute(select(Employee)).scalars().all()
    }
    for usage, agent_run, _task_run in rows:
        cost = usage.cost_usd
        if cost is None:
            unknown_cost += 1
            cost_value = 0.0
        else:
            cost_value = float(cost)
        total_prompt += usage.prompt_tokens
        total_completion += usage.completion_tokens
        total_cost += cost_value
        employee_key = usage.employee_id or usage.employee_key
        bucket = by_employee[employee_key]
        bucket["employee_id"] = employee_key
        bucket["employee_name"] = names.get(employee_key, usage.employee_key)
        bucket["prompt_tokens"] += usage.prompt_tokens
        bucket["completion_tokens"] += usage.completion_tokens
        bucket["cost_usd"] = round(bucket["cost_usd"] + cost_value, 8)
        bucket["calls"] += 1
        model_bucket = by_model[usage.model]
        model_bucket["model"] = usage.model
        model_bucket["prompt_tokens"] += usage.prompt_tokens
        model_bucket["completion_tokens"] += usage.completion_tokens
        model_bucket["cost_usd"] = round(model_bucket["cost_usd"] + cost_value, 8)
        model_bucket["calls"] += 1
        day = (usage.created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        by_day[day]["date"] = day
        by_day[day]["cost_usd"] = round(by_day[day]["cost_usd"] + cost_value, 8)
        by_day[day]["calls"] += 1
        records.append({
            "agent_run_id": agent_run.id,
            "employee_id": usage.employee_id,
            "employee_name": names.get(usage.employee_id or "", usage.employee_key),
            "model": usage.model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost_usd": usage.cost_usd,
            "latency_ms": usage.latency_ms,
            "billable": usage.billable,
            "created_at": iso_utc(usage.created_at),
        })

    records.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return {
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": round(total_cost, 8),
        "unknown_cost_records": unknown_cost,
        "calls": len(rows),
        "by_employee": sorted(by_employee.values(), key=lambda item: -item["cost_usd"]),
        "by_model": sorted(by_model.values(), key=lambda item: -item["cost_usd"]),
        "by_day": sorted(by_day.values(), key=lambda item: item["date"]),
        "records": records[:200],
    }


def monitor_summary(session: Session, owner_id: str, company_id: str) -> dict:
    tasks = session.execute(
        select(Task).where(
            Task.owner_id == owner_id,
            Task.company_id == company_id,
            Task.parent_task_id.is_(None),  # 只统计根任务；子任务计入父任务进度
        )
    ).scalars().all()
    states: dict[str, int] = defaultdict(int)
    for task in tasks:
        states[task.state] += 1

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_usage = usage_summary(
        session, owner_id, company_id=company_id, date_from=today.isoformat()
    )
    pending = session.execute(
        select(TaskApproval)
        .join(Task, Task.id == TaskApproval.task_id)
        .where(
            TaskApproval.owner_id == owner_id,
            TaskApproval.status == "pending",
            Task.company_id == company_id,
        )
    ).scalars().all()
    active_runs = session.execute(
        select(TaskRun)
        .join(Task, Task.id == TaskRun.task_id)
        .where(
            TaskRun.owner_id == owner_id,
            TaskRun.state.in_(("queued", "running")),
            Task.company_id == company_id,
        )
    ).scalars().all()
    recent_agents = session.execute(
        select(AgentRun)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .where(AgentRun.owner_id == owner_id, Task.company_id == company_id)
        .order_by(AgentRun.created_at.desc()).limit(10)
    ).scalars().all()

    return {
        "company_id": company_id,
        "task_total": len(tasks),
        "states": dict(sorted(states.items())),
        "active_runs": len(active_runs),
        "pending_approvals": len(pending),
        "today_cost_usd": today_usage["total_cost_usd"],
        "today_calls": today_usage["calls"],
        "failed_tasks": sum(1 for task in tasks if task.state == "failed"),
        "recent_agent_runs": [serialize_agent_run(row) for row in recent_agents],
        # M3-E：工具调用统计 / 拒绝原因 Top N / 预算使用率 / 全局开关状态
        "tool_execution": {"enabled": global_tools_enabled()},
        "tools": _tool_stats(session, owner_id, company_id),
        "budgets": _budget_watch(session, owner_id, company_id),
    }


def _tool_stats(session: Session, owner_id: str, company_id: str) -> dict:
    rows = session.execute(
        select(ToolCall.status, ToolCall.error_code, func.count())
        .join(Task, Task.id == ToolCall.task_id)
        .where(ToolCall.owner_id == owner_id, Task.company_id == company_id)
        .group_by(ToolCall.status, ToolCall.error_code)
    ).all()
    by_status: dict[str, int] = defaultdict(int)
    denials: dict[str, int] = defaultdict(int)
    total = 0
    for status, error_code, count in rows:
        total += int(count)
        by_status[status] += int(count)
        if status == "denied":
            denials[error_code or "UNKNOWN"] += int(count)
    denials_top = sorted(
        ({"code": code, "count": count} for code, count in denials.items()),
        key=lambda item: (-item["count"], item["code"]),
    )[:5]
    return {
        "total": total,
        "by_status": dict(sorted(by_status.items())),
        "denials_top": denials_top,
    }


def _spent_cost(session: Session, task_id: str) -> float:
    total = session.execute(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
        .join(AgentRun, AgentRun.id == UsageRecord.agent_run_id)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .where(TaskRun.task_id == task_id)
    ).scalar_one()
    return round(float(total or 0.0), 8)


def _budget_watch(session: Session, owner_id: str, company_id: str, limit: int = 10) -> dict:
    """非终态任务的预算使用率：上限取 task.budget_usd，缺省回退公司默认预算。"""
    company = session.get(Company, company_id)
    default_usd = (company.policy or {}).get("default_budget_usd") if company else None
    try:
        default_usd = float(default_usd) if default_usd is not None else None
    except (TypeError, ValueError):
        default_usd = None

    tasks = session.execute(
        select(Task).where(
            Task.owner_id == owner_id,
            Task.company_id == company_id,
            Task.parent_task_id.is_(None),
            Task.state.not_in(("succeeded", "cancelled", "skipped")),
        )
    ).scalars().all()
    items = []
    for task in tasks:
        cap = task.budget_usd if task.budget_usd is not None else default_usd
        if cap is None or float(cap) <= 0:
            continue
        spent = _spent_cost(session, task.id)
        items.append({
            "task_id": task.id,
            "title": task.title,
            "state": task.state,
            "budget_usd": float(cap),
            "spent_usd": spent,
            "ratio": round(spent / float(cap), 4),
        })
    items.sort(key=lambda item: (-item["ratio"], item["task_id"]))
    return {"default_budget_usd": default_usd, "watching": items[:limit]}
