"""M4-SOP：任务模板接口（沉淀/列表/详情/实例化/删除）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, get_actor, get_db
from packages.persistence.models import Task
from packages.shared.errors import DomainError
from packages.tasks import templates as template_service

router = APIRouter(tags=["templates"])


class TemplateCreate(BaseModel):
    task_id: str
    name: str
    description: str = ""


class InstantiateBody(BaseModel):
    title: str
    objective: str = ""
    assignee_employee_id: str | None = None
    budget_usd: float | None = None


@router.get("/companies/{company_id}/task-templates")
def list_templates_endpoint(company_id: str, db=Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return {"items": template_service.list_templates(db, actor.owner_id, company_id), "total": 0}


@router.get("/task-templates/{template_id}")
def get_template_endpoint(template_id: str, db=Depends(get_db), actor: ActorContext = Depends(get_actor)):
    return template_service.get_template(db, actor.owner_id, template_id)


@router.post("/companies/{company_id}/task-templates", status_code=201)
def create_template_endpoint(
    company_id: str,
    body: TemplateCreate,
    request: Request,
    db=Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    task = db.get(Task, body.task_id)
    if task is None or task.owner_id != actor.owner_id:
        raise DomainError("NOT_FOUND", f"任务不存在：{body.task_id}", 404)
    result = template_service.create_from_task(
        db, actor.owner_id, company_id=company_id, task=task,
        name=body.name, description=body.description,
    )
    audit_action(
        db, actor, request, action="template.create", target_type="task_template",
        target_id=result["id"], detail={"name": result["name"], "source_task_id": body.task_id},
    )
    return result


@router.post("/task-templates/{template_id}/instantiate", status_code=201)
def instantiate_endpoint(
    template_id: str,
    body: InstantiateBody,
    request: Request,
    db=Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    template, task = template_service.instantiate(
        db, actor.owner_id, template_id,
        title=body.title, objective=body.objective,
        assignee_employee_id=body.assignee_employee_id, budget_usd=body.budget_usd,
    )
    audit_action(
        db, actor, request, action="template.instantiate", target_type="task",
        target_id=task.id, detail={"template_id": template_id, "template_name": template.name},
    )
    from packages.tasks import service

    return service.serialize_task(task)


@router.delete("/task-templates/{template_id}", status_code=204)
def delete_template_endpoint(
    template_id: str, request: Request, db=Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    template_service.delete_template(db, actor.owner_id, template_id)
