"""管理者自动拆分任务（M2-C）：LLM 生成计划 → 严格校验 → 建子任务。

诚实性：规划本身是一次真实模型调用，记录为 `task_run.trigger=plan` + `agent_run.step_id=decompose`，
成本进入 usage_record；解析/校验失败不伪造计划。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.agent_core.adapter import collect_final
from packages.persistence.models import (
    AgentRun,
    Employee,
    EmployeePosition,
    Position,
    Task,
    TaskRun,
    UsageRecord,
)
from packages.shared.errors import DomainError
from packages.shared.types import AgentTask, new_id

from .plan import MAX_STEPS, normalize_plan
from .service import emit, employee_can_review, resolve_mode, set_plan

PLAN_SYSTEM = (
    "你是任务规划者。你只输出 JSON，不输出解释、不加代码块标记。"
    "拆分要求：步骤之间有明确上下游；每步只做一件事；"
    "员工必须从给定清单里选，且其岗位能力要匹配。"
)


def _managerial(session: Session, employee: Employee) -> bool:
    links = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
    ).scalars().all()
    for link in links:
        position = session.get(Position, link.position_id)
        if position is not None and position.is_managerial:
            return True
    return False


def _candidates(session: Session, task: Task) -> list[Employee]:
    return list(session.execute(
        select(Employee).where(
            Employee.company_id == task.company_id,
            Employee.status == "active",
            Employee.deleted_at.is_(None),
        ).order_by(Employee.name)
    ).scalars().all())


def _build_prompt(session: Session, task: Task, employees: list[Employee], max_steps: int) -> str:
    lines = [
        f"任务标题：{task.title}",
        f"任务目标：{task.objective or task.instruction or task.title}",
    ]
    if task.deliverable:
        lines.append(f"交付标准：{task.deliverable}")
    lines.append("")
    lines.append("可用员工：")
    for employee in employees:
        links = session.execute(
            select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
        ).scalars().all()
        tags: set[str] = set(employee.tools_allowed or [])
        for link in links:
            position = session.get(Position, link.position_id)
            if position is not None:
                tags.update(position.review_capability_tags or [])
        suffix = f"｜能力：{','.join(sorted(tags))}" if tags else ""
        lines.append(f"- {employee.id} = {employee.name}（{employee.title or '员工'}）{suffix}")
    lines.append("")
    lines.append(
        f"请拆成 2–{max_steps} 个步骤，输出 JSON："
        '{"steps":[{"id":"s1","title":"短语","employee_id":"员工id",'
        '"instruction":"该员工要做的具体事情","depends_on":["上游步骤id"]}]}'
    )
    lines.append("依赖必须指向已有步骤，且不能成环；第一步 depends_on 为空。")
    return "\n".join(lines)


def _parse_plan(text: str) -> dict:
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        raise DomainError(
            "DECOMPOSE_PARSE_FAILED", "模型输出不是合法 JSON，未生成计划", 422,
            {"raw": text[:500]},
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise DomainError("DECOMPOSE_PARSE_FAILED", "模型输出缺少 steps 数组", 422)
    return data


async def decompose_task(
    session: Session,
    owner_id: str,
    task: Task,
    manager: Employee,
    max_steps: int = 4,
) -> dict:
    from packages.execution.adapter_factory import build_adapter
    from packages.execution.guard import check_execution

    if manager.owner_id != owner_id or manager.company_id != task.company_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", "管理者必须属于任务所在公司", 422)
    if manager.status != "active" or manager.deleted_at is not None:
        raise DomainError("TASK_ASSIGNEE_INVALID", "管理者不是在职状态", 422)
    if not _managerial(session, manager) and not employee_can_review(session, manager):
        raise DomainError(
            "TASK_ASSIGNEE_INVALID", "自动拆分需要管理岗（is_managerial）或审查资格", 403,
            {"employee_id": manager.id},
        )
    if task.state != "draft":
        raise DomainError("TASK_NOT_EDITABLE", "只有草稿任务可以自动拆分", 409)

    mode = resolve_mode(task)
    bundle = build_adapter(session, manager, mode)
    from packages.persistence.models import ModelConnection

    connection = session.get(ModelConnection, bundle.connection_id) if bundle.connection_id else None
    check_execution(session, task, manager, connection, mode)

    employees = _candidates(session, task)
    prompt = _build_prompt(session, task, employees, min(max_steps, MAX_STEPS))

    run_no = int(session.execute(
        select(func.max(TaskRun.run_no)).where(TaskRun.task_id == task.id)
    ).scalar_one() or 0) + 1
    run = TaskRun(
        id=new_id(), owner_id=owner_id, task_id=task.id, run_no=run_no,
        trigger="plan", state="running", mode=mode, checkpoint={},
    )
    session.add(run)
    session.flush()
    started = datetime.now(timezone.utc)

    handle = await bundle.adapter.execute(
        AgentTask(instruction=prompt, input="", task_id=f"{task.id}:decompose"),
        system_prompt=PLAN_SYSTEM,
    )
    result = await collect_final(bundle.adapter, handle)
    await bundle.adapter.close()
    ended = datetime.now(timezone.utc)

    agent_run = AgentRun(
        id=new_id(), owner_id=owner_id, task_run_id=run.id,
        employee_key=manager.name or manager.id, employee_id=manager.id,
        role=manager.title or "", adapter_type=getattr(bundle.adapter, "adapter_type", "api"),
        model=bundle.model,
        input_payload={"instruction": prompt[:4000], "manager": manager.id, "mode": mode},
        output_payload={"content": (result["content"] or "")[:8000]},
        state="succeeded" if result["ok"] else "failed", error=result["error"],
        external_ref=handle.external_ref, step_id="decompose",
        model_connection_id=bundle.connection_id, started_at=started, ended_at=ended,
    )
    session.add(agent_run)
    session.flush()
    usage = result.get("usage")
    if usage is not None:
        session.add(UsageRecord(
            owner_id=owner_id, agent_run_id=agent_run.id,
            employee_key=manager.name or manager.id, employee_id=manager.id,
            model=usage.model, prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=0.0 if mode == "mock" else usage.cost_usd,
            latency_ms=usage.latency_ms, billable=mode == "real", created_at=ended,
        ))
    run.ended_at = ended
    run.checkpoint = {"completed_steps": ["decompose"], "outputs": {}}

    if not result["ok"]:
        run.state = "failed"
        run.error = (result["error"] or "decompose failed")[:500]
        emit(session, task, run.id, "decompose.failed", {"error": run.error})
        session.commit()
        raise DomainError(
            "DECOMPOSE_FAILED", f"规划调用失败：{result['error'] or '未知错误'}", 502
        )

    try:
        parsed = _parse_plan(result["content"])
        # 用轻量代理校验，避免把非法计划写进 task.plan 再回滚掉已记录的用量
        from types import SimpleNamespace

        normalize_plan(
            session, owner_id,
            SimpleNamespace(
                plan=parsed, depth=task.depth, company_id=task.company_id,
                id=task.id, assignee_employee_id=task.assignee_employee_id,
            ),
        )
    except DomainError as exc:
        run.state = "failed"
        run.error = f"{exc.code}: {exc.message}"[:500]
        emit(session, task, run.id, "decompose.failed", {"code": exc.code, "message": exc.message})
        session.commit()
        raise

    run.state = "succeeded"
    emit(session, task, run.id, "decompose.succeeded", {
        "steps": len(parsed["steps"]), "agent_run_id": agent_run.id,
    })
    session.commit()

    task = set_plan(session, owner_id, task.id, parsed)
    return {
        "task_id": task.id,
        "steps": [step["id"] for step in (task.plan or {}).get("steps", [])],
        "plan_run_id": run.id,
        "agent_run_id": agent_run.id,
        "mode": mode,
    }
