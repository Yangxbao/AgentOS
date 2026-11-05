"""员工接口 API-17..24（写操作全部落审计）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, PageParams, get_actor, get_db
from apps.api.schemas.people import EmployeeCreate, EmployeeUpdate, ModelBindingUpdate
from packages.organization import employees as service
from packages.organization.common import iso_utc

router = APIRouter(tags=["employees"])

# 审计比对字段：只记录真正变化的项，避免把整份档案写进日志
TRACKED_FIELDS = (
    "name", "title", "avatar", "bio", "personality",
    "department_id", "reports_to", "tools_allowed", "permission_profile", "status",
)


def _snapshot(employee) -> dict:
    return {key: getattr(employee, key) for key in TRACKED_FIELDS}


@router.get("/companies/{company_id}/employees")
def list_employees_endpoint(
    company_id: str,
    status_filter: str | None = None,
    department_id: str | None = None,
    q: str | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = service.list_employees(
        db, actor.owner_id, company_id, status=status_filter, department_id=department_id,
        q=q, offset=params.offset, limit=params.page_size,
    )
    return {
        "items": [service.serialize_employee(db, e) for e in rows],
        "total": total, "page": params.page, "page_size": params.page_size,
    }


@router.post("/companies/{company_id}/employees", status_code=status.HTTP_201_CREATED)
def create_employee_endpoint(
    company_id: str,
    payload: EmployeeCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = service.create_employee(
        db, actor.owner_id, company_id,
        name=payload.name, primary_model_id=payload.primary_model_id,
        fallback_model_id=payload.fallback_model_id, department_id=payload.department_id,
        title=payload.title, avatar=payload.avatar, bio=payload.bio,
        personality=payload.personality, reports_to=payload.reports_to,
        adapter_type=payload.adapter_type, cli_profile=payload.cli_profile,
        tools_allowed=payload.tools_allowed, permission_profile=payload.permission_profile,
        positions=[p.model_dump() for p in payload.positions],
    )
    data = service.serialize_employee(db, employee)
    audit_action(
        db, actor, request,
        action="employee.create", target_type="employee", target_id=employee.id,
        detail={
            "name": employee.name,
            "department_id": employee.department_id,
            "reports_to": employee.reports_to,
            "primary_model_id": employee.primary_model_id,
            "fallback_model_id": employee.fallback_model_id,
            "positions": [item["position_id"] for item in data["positions"]],
        },
    )
    return data


@router.get("/employees/{employee_id}")
def get_employee_endpoint(
    employee_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = service.get_employee(db, actor.owner_id, employee_id)
    data = service.serialize_employee(db, employee)
    data["model_history"] = [
        {
            "from_model_id": log.from_model_id,
            "to_model_id": log.to_model_id,
            "slot": log.slot,
            "reason": log.reason,
            "at": iso_utc(log.created_at),
        }
        for log in service.switch_logs(db, actor.owner_id, employee_id)
    ]
    return data


@router.patch("/employees/{employee_id}")
def update_employee_endpoint(
    employee_id: str,
    payload: EmployeeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    provided = payload.model_fields_set
    before = _snapshot(service.get_employee(db, actor.owner_id, employee_id))
    employee = service.update_employee(
        db, actor.owner_id, employee_id,
        name=payload.name, title=payload.title, avatar=payload.avatar, bio=payload.bio,
        personality=payload.personality,
        department_id=payload.department_id, department_id_provided="department_id" in provided,
        reports_to=payload.reports_to, reports_to_provided="reports_to" in provided,
        tools_allowed=payload.tools_allowed, permission_profile=payload.permission_profile,
        positions=[p.model_dump() for p in payload.positions] if payload.positions is not None else None,
        expected_updated_at=payload.expected_updated_at,
    )
    after = _snapshot(employee)
    changed = [key for key in TRACKED_FIELDS if before[key] != after[key]]
    audit_action(
        db, actor, request,
        action="employee.update", target_type="employee", target_id=employee.id,
        detail={
            "changed": changed,
            "before": {key: before[key] for key in changed},
            "after": {key: after[key] for key in changed},
        },
    )
    return service.serialize_employee(db, employee)


@router.post("/employees/{employee_id}/enable")
def enable_employee_endpoint(
    employee_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = service.set_status(db, actor.owner_id, employee_id, "active")
    audit_action(
        db, actor, request,
        action="employee.enable", target_type="employee", target_id=employee.id,
        detail={"status": employee.status},
    )
    return service.serialize_employee(db, employee)


@router.post("/employees/{employee_id}/disable")
def disable_employee_endpoint(
    employee_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = service.set_status(db, actor.owner_id, employee_id, "disabled")
    audit_action(
        db, actor, request,
        action="employee.disable", target_type="employee", target_id=employee.id,
        detail={"status": employee.status},
    )
    return service.serialize_employee(db, employee)


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee_endpoint(
    employee_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = service.get_employee(db, actor.owner_id, employee_id)
    name = employee.name
    service.delete_employee(db, actor.owner_id, employee_id)
    audit_action(
        db, actor, request,
        action="employee.delete", target_type="employee", target_id=employee_id,
        detail={"name": name, "soft_deleted": True},
    )
    return None


@router.put("/employees/{employee_id}/model-binding")
def update_model_binding_endpoint(
    employee_id: str,
    payload: ModelBindingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    before = service.get_employee(db, actor.owner_id, employee_id)
    old_primary = before.primary_model_id
    old_fallback = before.fallback_model_id
    employee, warnings = service.bind_models(
        db, actor.owner_id, employee_id,
        primary_model_id=payload.primary_model_id,
        fallback_model_id=payload.fallback_model_id,
        reason=payload.reason, actor_id=actor.actor_id,
    )
    audit_action(
        db, actor, request,
        action="employee.model_binding.update", target_type="employee", target_id=employee.id,
        detail={
            "primary_model_id": {"from": old_primary, "to": employee.primary_model_id},
            "fallback_model_id": {"from": old_fallback, "to": employee.fallback_model_id},
            "reason": payload.reason,
            "warnings": warnings,
        },
    )
    return {
        "employee_id": employee.id,
        "primary_model_id": employee.primary_model_id,
        "fallback_model_id": employee.fallback_model_id,
        "history_preserved": True,
        "warnings": warnings,
    }
