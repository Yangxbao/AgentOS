"""M2-E：执行监控与成本查询（M2-18..21）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, get_actor, get_db
from packages.execution.observability import (
    agent_run_detail,
    monitor_summary,
    runs_of_task,
    task_timeline,
    task_usage,
    usage_summary,
)
from packages.persistence.models import TaskApproval
from packages.shared.errors import DomainError
from packages.tasks import service
from packages.tasks.approvals import serialize_approval

router = APIRouter(tags=["monitor"])


@router.get("/tasks/{task_id}/timeline")
def timeline_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    items = task_timeline(db, actor.owner_id, task_id)
    return {"items": items, "total": len(items)}


@router.get("/tasks/{task_id}/runs")
def task_runs_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return {"items": runs_of_task(db, actor.owner_id, task_id)}


@router.get("/tasks/{task_id}/usage")
def task_usage_endpoint(
    task_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return task_usage(db, actor.owner_id, task_id)


@router.get("/agent-runs/{agent_run_id}")
def agent_run_endpoint(
    agent_run_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return agent_run_detail(db, actor.owner_id, agent_run_id)


@router.get("/usage")
def usage_endpoint(
    company_id: str | None = None,
    task_id: str | None = None,
    employee_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return usage_summary(
        db, actor.owner_id, company_id=company_id, task_id=task_id,
        employee_id=employee_id, date_from=date_from, date_to=date_to,
    )


@router.get("/monitor/summary")
def monitor_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return monitor_summary(db, actor.owner_id, company_id)


@router.get("/workers")
def workers_endpoint(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """M3-D：在线 worker 视图（租约、心跳、队列深度）。"""
    from packages.execution.runner import TaskRunner

    return TaskRunner().workers_snapshot()


@router.get("/workers/stats")
def worker_stats_endpoint(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """M3-D：队列长度 / 运行中 / 租约中断 / 重启恢复统计。"""
    from sqlalchemy import func, select

    from packages.persistence.models import TaskRun

    def _count(*states):
        return int(db.execute(
            select(func.count()).select_from(TaskRun).where(TaskRun.state.in_(states))
        ).scalar_one() or 0)

    return {
        "queued": _count("queued"),
        "running": _count("running"),
        "interrupted": _count("interrupted"),
        "paused": _count("paused"),
        "failed": _count("failed"),
        "succeeded": _count("succeeded"),
    }


@router.get("/approvals/{approval_id}")
def approval_detail_endpoint(
    approval_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = db.get(TaskApproval, approval_id)
    if row is None or row.owner_id != actor.owner_id:
        raise DomainError("NOT_FOUND", f"审批不存在：{approval_id}", 404)
    data = serialize_approval(row)
    task = service.get_task(db, actor.owner_id, row.task_id)
    data["task"] = {"id": task.id, "title": task.title, "state": task.state}
    return data
