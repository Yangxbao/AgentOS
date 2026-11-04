"""B5：权限、派工、审计接口（API-26..29、40..41、45）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, PageParams, get_actor, get_db
from apps.api.schemas.governance import AssignmentRequest, PermissionOverrideRequest
from packages.agent_core.capabilities import employee_capabilities
from packages.organization.employees import get_employee
from packages.permissions.assignment import get_decision, preview_assignment
from packages.permissions.audit import list_audit, serialize_audit, write_audit
from packages.permissions.effective import compute_effective_permissions, merge_overrides
from packages.shared.errors import DomainError

router = APIRouter(tags=["governance"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


@router.get("/employees/{employee_id}/effective-permissions")
def effective_permissions_endpoint(
    employee_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    return compute_effective_permissions(db, actor.owner_id, employee_id)


@router.put("/employees/{employee_id}/permission-overrides")
def permission_overrides_endpoint(
    employee_id: str,
    payload: PermissionOverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    try:
        result = merge_overrides(db, actor.owner_id, employee_id, payload.overrides)
    except DomainError as exc:
        write_audit(
            db, actor.owner_id, action="employee.permission_overrides.denied",
            target_type="employee", target_id=employee_id,
            detail={"overrides": payload.overrides, "code": exc.code}, request_id=_request_id(request),
        )
        raise
    write_audit(
        db, actor.owner_id, action="employee.permission_overrides.update",
        target_type="employee", target_id=employee_id,
        detail={"overrides": payload.overrides}, request_id=_request_id(request),
    )
    return result


@router.get("/employees/{employee_id}/capabilities")
def capabilities_endpoint(
    employee_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    employee = get_employee(db, actor.owner_id, employee_id)
    return employee_capabilities(db, employee)


@router.get("/employees/{employee_id}/audit")
def employee_audit_endpoint(
    employee_id: str,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = list_audit(
        db, actor.owner_id, target_id=employee_id, offset=params.offset, limit=params.page_size
    )
    return {"items": [serialize_audit(row) for row in rows], "total": total,
            "page": params.page, "page_size": params.page_size}


@router.post("/companies/{company_id}/assignments/preview")
def assignment_preview_endpoint(
    company_id: str,
    payload: AssignmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = preview_assignment(db, actor.owner_id, company_id, payload.model_dump())
    write_audit(
        db, actor.owner_id, action="assignment.preview", target_type="company", target_id=company_id,
        detail={"decision_id": result["decision_id"], "candidates": len(result["candidates"])},
        request_id=_request_id(request),
    )
    return result


@router.get("/assignments/{decision_id}")
def assignment_get_endpoint(
    decision_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    return get_decision(db, actor.owner_id, decision_id)


@router.get("/audit")
def audit_list_endpoint(
    actor_type: str | None = None,
    action: str | None = None,
    target_id: str | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = list_audit(
        db, actor.owner_id, actor_type=actor_type, action=action, target_id=target_id,
        offset=params.offset, limit=params.page_size,
    )
    return {"items": [serialize_audit(row) for row in rows], "total": total,
            "page": params.page, "page_size": params.page_size}
