"""任务模板服务（M4-SOP）：把跑通的任务计划沉淀为可复用模板，一键实例化新任务。

这是"客户拥有一整个公司"的关键能力：公司把验证过的交付流程（如星舟官网
9 步流水线）沉淀为 SOP，下一个客户下单时一键实例化——公司资产可复用。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Task, TaskTemplate
from packages.shared.errors import DomainError
from packages.shared.types import new_id


def _serialize(template: TaskTemplate) -> dict:
    plan = template.plan or {}
    return {
        "id": template.id,
        "company_id": template.company_id,
        "name": template.name,
        "description": template.description,
        "steps": plan.get("steps") or [],
        "step_count": len(plan.get("steps") or []),
        "source_task_id": template.source_task_id,
        "source_task_title": template.source_task_title,
        "usage_count": template.usage_count,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


def list_templates(session: Session, owner_id: str, company_id: str) -> list[dict]:
    rows = session.execute(
        select(TaskTemplate)
        .where(TaskTemplate.owner_id == owner_id, TaskTemplate.company_id == company_id)
        .order_by(TaskTemplate.updated_at.desc())
    ).scalars().all()
    return [_serialize(row) for row in rows]


def get_template(session: Session, owner_id: str, template_id: str) -> dict:
    row = session.get(TaskTemplate, template_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"模板不存在：{template_id}", 404)
    return _serialize(row)


def create_from_task(
    session: Session,
    owner_id: str,
    *,
    company_id: str,
    task: Task,
    name: str,
    description: str = "",
) -> dict:
    """从已完成的任务抽取计划存为模板（只沉淀计划与交付物，不带执行状态）。"""
    plan = task.plan or {}
    steps = plan.get("steps") or []
    if not steps:
        raise DomainError(
            "TASK_PLAN_INVALID", "该任务没有执行计划（单步任务无法沉淀为模板）", 422,
        )
    template = TaskTemplate(
        id=new_id(), owner_id=owner_id, company_id=company_id,
        name=name.strip() or f"{task.title} 模板",
        description=description.strip(),
        plan={"steps": steps},
        source_task_id=task.id, source_task_title=task.title or "",
    )
    session.add(template)
    session.commit()
    return _serialize(template)


def delete_template(session: Session, owner_id: str, template_id: str) -> None:
    row = session.get(TaskTemplate, template_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"模板不存在：{template_id}", 404)
    session.delete(row)
    session.commit()


def instantiate(
    session: Session,
    owner_id: str,
    template_id: str,
    *,
    title: str,
    objective: str = "",
    assignee_employee_id: str | None = None,
    budget_usd: float | None = None,
) -> tuple[TaskTemplate, Task]:
    """从模板实例化新任务：走 create_task + set_plan 标准路径（员工/工具/计划校验全生效）。

    步骤级 employee_id 沿用模板（同公司内复用）；根任务执行人取模板第一步员工，
    可由 assignee_employee_id 覆盖。
    """
    from packages.tasks import service

    row = session.get(TaskTemplate, template_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"模板不存在：{template_id}", 404)
    steps = (row.plan or {}).get("steps") or []
    first_employee = next(
        (str(step.get("employee_id")) for step in steps if step.get("employee_id")), None
    )
    payload = {
        "title": (title or "").strip() or f"{row.name} 实例",
        "objective": objective or row.description,
        "instruction": objective or row.description,
        "assignee_employee_id": assignee_employee_id or first_employee,
        "budget_usd": budget_usd,
    }
    task = service.create_task(session, owner_id, row.company_id, payload)
    if steps:
        service.set_plan(
            session, owner_id, task.id,
            {"steps": steps, "max_parallel": (row.plan or {}).get("max_parallel", 4)},
        )
    row.usage_count = (row.usage_count or 0) + 1
    session.commit()
    session.refresh(task)
    return row, task
