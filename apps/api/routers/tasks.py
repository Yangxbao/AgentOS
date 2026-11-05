"""M2-A：任务中心接口（M2-01..14）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, PageParams, get_actor, get_db
from apps.api.schemas.tasks import (
    DecomposeRequest,
    ReplanRequest,
    TaskCreate,
    TaskPlanInput,
    TaskUpdate,
)
from packages.execution.observability import runs_of_task, task_usage
from packages.persistence.models import Employee, TaskApproval
from packages.shared.errors import DomainError
from packages.tasks import service
from packages.tasks import state as task_state
from packages.tasks.approvals import serialize_approval
from packages.tasks.decompose import decompose_task

router = APIRouter(tags=["tasks"])


def _kick(request: Request) -> None:
    runner = getattr(request.app.state, "runner", None)
    if runner is not None:
        runner.kick()


def _employees_map(session: Session, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = session.execute(select(Employee).where(Employee.id.in_(ids))).scalars().all()
    return {
        row.id: {"id": row.id, "name": row.name, "title": row.title, "status": row.status}
        for row in rows
    }


def _task_detail(session: Session, owner_id: str, task) -> dict:
    children = service.children_of(session, task.id)
    data = service.serialize_task(task, children_count=len(children))
    data["children"] = [service.serialize_task(child) for child in children]
    ids = {task.assignee_employee_id, task.reviewer_employee_id}
    ids.update(child.assignee_employee_id for child in children)
    data["employees"] = _employees_map(session, {item for item in ids if item})
    runs = runs_of_task(session, owner_id, task.id)
    data["runs"] = runs[-5:]
    data["active_run"] = next(
        (run for run in runs if run["state"] in ("queued", "running")), None
    )
    approvals = session.execute(
        select(TaskApproval)
        .where(TaskApproval.task_id == task.id)
        .order_by(TaskApproval.created_at.desc())
    ).scalars().all()
    data["approvals"] = [serialize_approval(row) for row in approvals]
    data["pending_approvals"] = [
        serialize_approval(row) for row in approvals if row.status == "pending"
    ]
    data["usage"] = task_usage(session, owner_id, task.id)
    data["allowed_transitions"] = task_state.allowed_targets(task.state)
    return data


@router.post(
    "/companies/{company_id}/tasks",
    status_code=status.HTTP_201_CREATED,
)
def create_task_endpoint(
    company_id: str,
    payload: TaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    task = service.create_task(db, actor.owner_id, company_id, payload.model_dump())
    audit_action(
        db, actor, request, action="task.create", target_type="task", target_id=task.id,
        detail={
            "title": task.title,
            "assignee_employee_id": task.assignee_employee_id,
            "priority": task.priority,
            "risk_level": task.risk_level,
            "approval_required": task.approval_required,
        },
    )
    return service.serialize_task(task)


@router.get("/companies/{company_id}/tasks")
def list_tasks_endpoint(
    company_id: str,
    state: str | None = None,
    assignee_employee_id: str | None = None,
    department_id: str | None = None,
    parent_task_id: str | None = None,
    roots_only: bool = True,
    q: str | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = service.list_tasks(
        db, actor.owner_id, company_id, state=state,
        assignee_employee_id=assignee_employee_id, department_id=department_id,
        parent_task_id=parent_task_id, roots_only=roots_only, q=q,
        offset=params.offset, limit=params.page_size,
    )
    employees = _employees_map(db, {row.assignee_employee_id for row in rows if row.assignee_employee_id})
    items = []
    for row in rows:
        item = service.serialize_task(row)
        item["assignee_name"] = (employees.get(row.assignee_employee_id) or {}).get("name", "")
        items.append(item)
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}


@router.get("/tasks/{task_id}")
def get_task_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    task = service.get_task(db, actor.owner_id, task_id)
    return _task_detail(db, actor.owner_id, task)


@router.patch("/tasks/{task_id}")
def update_task_endpoint(
    task_id: str,
    payload: TaskUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    data = payload.model_dump(exclude_unset=True)
    expected = data.pop("expected_version", None)
    task = service.update_task(db, actor.owner_id, task_id, data, expected_version=expected)
    audit_action(
        db, actor, request, action="task.update", target_type="task", target_id=task.id,
        detail={"fields": sorted(data.keys())},
    )
    return service.serialize_task(task)


@router.put("/tasks/{task_id}/plan")
def set_plan_endpoint(
    task_id: str,
    payload: TaskPlanInput,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    plan = {"steps": [step.model_dump() for step in payload.steps],
            "max_parallel": payload.max_parallel}
    task = service.set_plan(db, actor.owner_id, task_id, plan)
    audit_action(
        db, actor, request, action="task.plan.update", target_type="task", target_id=task.id,
        detail={"steps": [step["id"] for step in (task.plan or {}).get("steps", [])]},
    )
    return _task_detail(db, actor.owner_id, task)


@router.post("/tasks/{task_id}/replan")
def replan_endpoint(
    task_id: str,
    payload: ReplanRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """M3-B：失败/待返工任务重规划（≤3 次），只重置失败步骤及其下游。"""
    result = service.replan(
        db, actor.owner_id, task_id,
        steps=[step.model_dump() for step in payload.steps],
        reason=payload.reason, failed_step_id=payload.failed_step_id,
    )
    audit_action(
        db, actor, request, action="task.replan", target_type="task", target_id=task_id,
        detail={
            "revision": result["plan_revision"],
            "replan_count": result["replan_count"],
            "failed_step_id": payload.failed_step_id,
        },
    )
    _kick(request)
    return result


@router.get("/tasks/{task_id}/plan-revisions")
def plan_revisions_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    items = service.plan_revisions_of(db, actor.owner_id, task_id)
    return {"items": items, "total": len(items)}


@router.post("/tasks/{task_id}/decompose")
async def decompose_endpoint(
    task_id: str,
    payload: DecomposeRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    task = service.get_task(db, actor.owner_id, task_id)
    manager_id = payload.manager_employee_id or task.assignee_employee_id
    if not manager_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", "任务没有执行员工，无法自动拆分", 422)
    manager = db.get(Employee, manager_id)
    if manager is None:
        raise DomainError("TASK_ASSIGNEE_INVALID", f"管理者不存在：{manager_id}", 422)
    result = await decompose_task(db, actor.owner_id, task, manager, payload.max_steps)
    audit_action(
        db, actor, request, action="task.decompose", target_type="task", target_id=task.id,
        detail={"steps": result["steps"], "manager_employee_id": manager.id},
    )
    refreshed = service.get_task(db, actor.owner_id, task_id)
    return {"decompose": result, "task": _task_detail(db, actor.owner_id, refreshed)}


@router.post("/tasks/{task_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_task_endpoint(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    run = service.enqueue_run(db, actor.owner_id, task_id, trigger="manual")
    audit_action(
        db, actor, request, action="task.run", target_type="task", target_id=task_id,
        detail={"run_id": run.id, "run_no": run.run_no, "mode": run.mode},
    )
    _kick(request)
    return {"run_id": run.id, "run_no": run.run_no, "state": run.state, "mode": run.mode}


@router.post("/tasks/{task_id}/pause")
def pause_task_endpoint(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = service.pause_task(db, actor.owner_id, task_id)
    audit_action(
        db, actor, request, action="task.pause", target_type="task", target_id=task_id,
        detail=result,
    )
    return result


@router.post("/tasks/{task_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_task_endpoint(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    run = service.resume_task(db, actor.owner_id, task_id)
    audit_action(
        db, actor, request, action="task.resume", target_type="task", target_id=task_id,
        detail={"run_id": run.id, "run_no": run.run_no},
    )
    _kick(request)
    return {"run_id": run.id, "run_no": run.run_no, "state": run.state}


@router.post("/tasks/{task_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_task_endpoint(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    run = service.retry_task(db, actor.owner_id, task_id)
    audit_action(
        db, actor, request, action="task.retry", target_type="task", target_id=task_id,
        detail={"run_id": run.id, "run_no": run.run_no},
    )
    _kick(request)
    return {"run_id": run.id, "run_no": run.run_no, "state": run.state}


@router.post("/tasks/{task_id}/cancel")
def cancel_task_endpoint(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = service.cancel_task(db, actor.owner_id, task_id)
    audit_action(
        db, actor, request, action="task.cancel", target_type="task", target_id=task_id,
        detail=result,
    )
    return result
