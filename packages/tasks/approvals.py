"""人工审批（M2-D）：挂起、批准、驳回、指定回退步骤。

规则：
- 只有 pending 可决策，重复决策 409；
- 审批人若指定为某员工，必须 can_review 且 ≠ 执行人（创建时校验）；本地人工用户可直接决策；
- 批准 → 入队新 run（after_run 则直接收尾，不重复执行）；
- 驳回 → rework_required，按 rewind_step_id 重置该步及其下游，已完成的上游步骤保留。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import Employee, Task, TaskApproval, TaskRun, ToolCall
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from . import state as st
from .service import _task, emit

DECISIONS = {"approve", "reject", "request_changes"}
STATUS_MAP = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}


def serialize_approval(row: TaskApproval) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_run_id": row.task_run_id,
        "gate": row.gate,
        "status": row.status,
        "requested_by": row.requested_by,
        "reviewer_employee_id": row.reviewer_employee_id,
        "decided_by": row.decided_by,
        "comment": row.comment,
        "rewind_step_id": row.rewind_step_id,
        "tool_call_id": row.tool_call_id,
        "context": row.context,
        "created_at": iso_utc(row.created_at),
        "decided_at": iso_utc(row.decided_at),
    }


def create_approval(
    session: Session,
    task: Task,
    run: TaskRun | None,
    *,
    gate: str = "before_run",
    requested_by: str = "local",
    context: dict | None = None,
) -> TaskApproval:
    row = TaskApproval(
        id=new_id(), owner_id=task.owner_id, task_id=task.id,
        task_run_id=run.id if run else None, gate=gate, status="pending",
        requested_by=requested_by, reviewer_employee_id=task.reviewer_employee_id,
        context=context or {
            "title": task.title,
            "assignee_employee_id": task.assignee_employee_id,
            "risk_level": task.risk_level,
            "steps": [step["id"] for step in (task.plan or {}).get("steps", [])],
        },
    )
    session.add(row)
    session.flush()
    return row


def _plan_steps(task: Task) -> list[dict]:
    return list((task.plan or {}).get("steps") or [])


def _descendant_steps(steps: list[dict], root: str) -> set[str]:
    affected = {root}
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step["id"] in affected:
                continue
            if affected & set(step.get("depends_on") or []):
                affected.add(step["id"])
                changed = True
    return affected


def apply_rewind(session: Session, task: Task, rewind_step_id: str | None) -> dict:
    """把回退点及其下游从检查点移除；返回被重置的步骤。"""
    steps = _plan_steps(task)
    if steps:
        known = {step["id"] for step in steps}
        target = rewind_step_id or steps[0]["id"]
        if target not in known:
            raise DomainError(
                "VALIDATION_ERROR", f"回退步骤不存在：{target}", 422, {"steps": sorted(known)}
            )
        reset = _descendant_steps(steps, target)
    else:
        # 单员工任务：固定步骤 id 为 s1
        target = rewind_step_id or "s1"
        reset = {target}

    last = session.execute(
        select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.run_no.desc())
    ).scalars().first()
    if last is not None:
        checkpoint = dict(last.checkpoint or {})
        checkpoint["completed_steps"] = [
            sid for sid in checkpoint.get("completed_steps", []) if sid not in reset
        ]
        checkpoint["outputs"] = {
            sid: value for sid, value in (checkpoint.get("outputs") or {}).items()
            if sid not in reset
        }
        checkpoint["rewind_to"] = target
        last.checkpoint = checkpoint

    for child in session.execute(
        select(Task).where(Task.parent_task_id == task.id)
    ).scalars().all():
        if (child.plan or {}).get("step_id") in reset:
            child.state = "pending"
            child.result = {}
            child.ended_at = None

    return {"reset_steps": sorted(reset), "rewind_to": target}


def decide(
    session: Session,
    owner_id: str,
    approval_id: str,
    *,
    decision: str,
    comment: str = "",
    rewind_step_id: str | None = None,
    actor_id: str = "local",
) -> dict:
    if decision not in DECISIONS:
        raise DomainError("VALIDATION_ERROR", "decision 必须是 approve/reject/request_changes", 422)
    row = session.get(TaskApproval, approval_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"审批不存在：{approval_id}", 404)
    if row.status != "pending":
        raise DomainError(
            "APPROVAL_NOT_PENDING", f"该审批已处理（{row.status}），不能重复决策", 409,
            {"status": row.status},
        )
    task = _task(session, owner_id, row.task_id)

    tool_call = session.get(ToolCall, row.tool_call_id) if row.tool_call_id else None
    if row.reviewer_employee_id:
        reviewer = session.get(Employee, row.reviewer_employee_id)
        executor_id = (
            tool_call.employee_id if tool_call is not None else task.assignee_employee_id
        )
        if reviewer is not None and reviewer.id == executor_id:
            raise DomainError("APPROVAL_REVIEWER_INVALID", "审批人不能是执行人本人", 409)

    now = datetime.now(timezone.utc)
    row.status = STATUS_MAP[decision]
    row.decided_by = actor_id
    row.decided_at = now
    row.comment = comment

    if decision == "approve":
        emit(session, task, row.task_run_id, "approval.approved", {
            "approval_id": row.id, "gate": row.gate, "tool_call_id": row.tool_call_id,
        })
        if row.gate == "tool_call" and tool_call is not None:
            tool_call.status = "approved"
            tool_call.ended_at = None
            emit(session, task, row.task_run_id, "tool.approved", {
                "tool_call_id": tool_call.id, "tool": tool_call.tool_name,
            })
            from .service import enqueue_run

            run = enqueue_run(
                session, owner_id, task.id, trigger="approval", approved_by=actor_id
            )
            return {
                "approval": serialize_approval(row), "state": task.state, "run_id": run.id,
            }
        if row.gate == "after_run":
            task.state = "succeeded"
            task.ended_at = now
            task.result = {**(task.result or {}), "approved_by": actor_id}
            task.version = (task.version or 1) + 1
            run = session.get(TaskRun, row.task_run_id) if row.task_run_id else None
            if run is not None:
                run.state = "succeeded"
                run.ended_at = now
                run.approved_by = actor_id
            emit(session, task, row.task_run_id, "task.succeeded", {"after_run_approval": True})
            session.commit()
            return {"approval": serialize_approval(row), "state": task.state, "run_id": None}

        from .service import enqueue_run

        run = enqueue_run(
            session, owner_id, task.id, trigger="approval", approved_by=actor_id
        )
        return {"approval": serialize_approval(row), "state": task.state, "run_id": run.id}

    # 工具调用被驳回：结束该调用，任务失败（可重试），不进入返工回退
    if row.gate == "tool_call" and tool_call is not None:
        tool_call.status = "denied"
        tool_call.error_code = "TOOL_APPROVAL_REJECTED"
        tool_call.error_message = (comment or "人工驳回该工具调用")[:500]
        tool_call.ended_at = now
        task.state = "failed"
        task.ended_at = now
        task.result = {
            **(task.result or {}),
            "error": {"code": "TOOL_APPROVAL_REJECTED", "message": comment or "人工驳回该工具调用"},
        }
        task.version = (task.version or 1) + 1
        run = session.get(TaskRun, row.task_run_id) if row.task_run_id else None
        if run is not None:
            run.state = "failed"
            run.error = "TOOL_APPROVAL_REJECTED: 人工驳回工具调用"
            run.ended_at = now
        emit(session, task, row.task_run_id, "tool.approval_rejected", {
            "approval_id": row.id, "tool_call_id": tool_call.id,
            "tool": tool_call.tool_name, "comment": comment,
        })
        session.commit()
        return {
            "approval": serialize_approval(row), "state": task.state, "run_id": None,
        }

    # 驳回 / 要求修改
    if task.rework_count >= task.max_rework:
        session.rollback()
        raise DomainError(
            "TASK_REWORK_LIMIT", f"已达到最大返工次数 {task.max_rework}", 409,
            {"rework_count": task.rework_count, "max_rework": task.max_rework},
        )
    st.ensure_transition(task.state, "rework_required")
    rewind = apply_rewind(session, task, rewind_step_id)
    row.rewind_step_id = rewind.get("rewind_to")
    task.state = "rework_required"
    task.rework_count += 1
    task.version = (task.version or 1) + 1
    task.cancel_requested = False
    task.pause_requested = False
    emit(session, task, row.task_run_id, "approval.rejected", {
        "approval_id": row.id, "decision": decision, "comment": comment,
        "rewind": rewind,
    })
    session.commit()
    return {
        "approval": serialize_approval(row),
        "state": task.state,
        "run_id": None,
        "rewind": rewind,
    }
