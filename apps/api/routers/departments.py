"""部门接口 API-06..11。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, Page, PageParams, get_actor, get_db
from apps.api.schemas.org import DepartmentCreate, DepartmentMove, DepartmentOut, DepartmentUpdate
from packages.organization import (
    build_org_tree,
    create_department,
    delete_department,
    list_departments,
    move_department,
    update_department,
)
from packages.organization.departments import serialize_department

router = APIRouter(tags=["departments"])


@router.get("/companies/{company_id}/departments", response_model=Page[DepartmentOut])
def list_departments_endpoint(
    company_id: str,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows = list_departments(db, actor.owner_id, company_id)
    start = params.offset
    page_rows = rows[start:start + params.page_size]
    return {"items": [serialize_department(d) for d in page_rows], "total": len(rows),
            "page": params.page, "page_size": params.page_size}


@router.get("/companies/{company_id}/org-tree")
def org_tree_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return build_org_tree(db, actor.owner_id, company_id)


@router.post(
    "/companies/{company_id}/departments",
    response_model=DepartmentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_department_endpoint(
    company_id: str,
    payload: DepartmentCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    department = create_department(
        db, actor.owner_id, company_id,
        name=payload.name, parent_id=payload.parent_id, code=payload.code,
        description=payload.description, sort_order=payload.sort_order,
    )
    return serialize_department(department)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department_endpoint(
    department_id: str,
    payload: DepartmentUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    provided = payload.model_fields_set
    department = update_department(
        db, actor.owner_id, department_id,
        name=payload.name,
        parent_id=payload.parent_id,
        parent_id_provided="parent_id" in provided,
        code=payload.code,
        description=payload.description,
        sort_order=payload.sort_order,
        expected_updated_at=payload.expected_updated_at,
    )
    return serialize_department(department)


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_department_endpoint(
    department_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    delete_department(db, actor.owner_id, department_id)
    return None


@router.post("/departments/{department_id}/move", response_model=DepartmentOut)
def move_department_endpoint(
    department_id: str,
    payload: DepartmentMove,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    if payload.new_parent_id == department_id:
        raise HTTPException(status_code=409, detail="部门不能成为自己的上级")
    department = move_department(
        db, actor.owner_id, department_id,
        new_parent_id=payload.new_parent_id, new_index=payload.new_index,
    )
    return serialize_department(department)
