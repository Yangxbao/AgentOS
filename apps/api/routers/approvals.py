"""M2-D：人工审批接口（M2-15..17）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, PageParams, get_actor, get_db
from apps.api.schemas.tasks import ApprovalDecisionRequest
from packages.persistence.models import Task, TaskApproval
from packages.tasks import service
from packages.tasks.approvals import decide, serialize_approval

router = APIRouter(tags=["approvals"])


def _kick(request: Request) -> None:
    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.kick()


@router.get("/tasks/{task_id}/approvals")
def list_task_approvals_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    service.get_task(db, actor.owner_id, task_id)
    rows = db.execute(
        select(TaskApproval)
        .where(TaskApproval.task_id == task_id)
        .order_by(TaskApproval.created_at.desc())
    ).scalars().all()
    return [serialize_approval(row) for row in rows]


@router.get("/approvals")
def list_approvals_endpoint(
    status_filter: str | None = None,
    company_id: str | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    stmt = select(TaskApproval).where(TaskApproval.owner_id == actor.owner_id)
    if status_filter:
        stmt = stmt.where(TaskApproval.status == status_filter)
    rows = db.execute(stmt.order_by(TaskApproval.created_at.desc())).scalars().all()
    tasks = {
        task.id: task
        for task in db.execute(
            select(Task).where(Task.id.in_({row.task_id for row in rows}))
        ).scalars().all()
    } if rows else {}
    if company_id:
        rows = [row for row in rows if (tasks.get(row.task_id) and tasks[row.task_id].company_id == company_id)]
    total = len(rows)
    page = rows[params.offset: params.offset + params.page_size]
    return {
        "items": [
            {**serialize_approval(row), "task_title": (tasks.get(row.task_id).title if tasks.get(row.task_id) else "")}
            for row in page
        ],
        "total": total, "page": params.page, "page_size": params.page_size,
    }


@router.post("/approvals/{approval_id}/decision")
def decide_endpoint(
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = decide(
        db, actor.owner_id, approval_id,
        decision=payload.decision, comment=payload.comment,
        rewind_step_id=payload.rewind_step_id, actor_id=actor.actor_id,
    )
    audit_action(
        db, actor, request, action="approval.decision",
        target_type="task_approval", target_id=approval_id,
        detail={
            "decision": payload.decision,
            "comment": payload.comment[:500],
            "task_id": result["approval"]["task_id"],
            "rewind_step_id": result["approval"].get("rewind_step_id"),
        },
    )
    if result.get("run_id"):
        _kick(request)
    return result
