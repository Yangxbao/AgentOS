"""岗位接口 API-12..16。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, Page, PageParams, get_actor, get_db
from apps.api.schemas.org import PositionCreate, PositionOut, PositionUpdate
from packages.organization import (
    create_position,
    delete_position,
    get_position,
    list_positions,
    update_position,
)
from packages.organization.positions import serialize_position

router = APIRouter(tags=["positions"])


@router.get("/companies/{company_id}/positions", response_model=Page[PositionOut])
def list_positions_endpoint(
    company_id: str,
    department_id: str | None = None,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = list_positions(
        db, actor.owner_id, company_id,
        department_id=department_id, offset=params.offset, limit=params.page_size,
    )
    return {"items": [serialize_position(p) for p in rows], "total": total,
            "page": params.page, "page_size": params.page_size}


@router.post(
    "/companies/{company_id}/positions",
    response_model=PositionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_position_endpoint(
    company_id: str,
    payload: PositionCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    position = create_position(
        db, actor.owner_id, company_id,
        name=payload.name, department_id=payload.department_id, level=payload.level,
        is_managerial=payload.is_managerial, can_review=payload.can_review,
        review_capability_tags=payload.review_capability_tags,
        responsibilities=payload.responsibilities, default_permissions=payload.default_permissions,
    )
    return serialize_position(position)


@router.get("/positions/{position_id}", response_model=PositionOut)
def get_position_endpoint(
    position_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return serialize_position(get_position(db, actor.owner_id, position_id))


@router.patch("/positions/{position_id}", response_model=PositionOut)
def update_position_endpoint(
    position_id: str,
    payload: PositionUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    provided = payload.model_fields_set
    position = update_position(
        db, actor.owner_id, position_id,
        name=payload.name,
        department_id=payload.department_id,
        department_id_provided="department_id" in provided,
        level=payload.level,
        is_managerial=payload.is_managerial,
        can_review=payload.can_review,
        review_capability_tags=payload.review_capability_tags,
        responsibilities=payload.responsibilities,
        default_permissions=payload.default_permissions,
        expected_updated_at=payload.expected_updated_at,
    )
    return serialize_position(position)


@router.delete("/positions/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position_endpoint(
    position_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    delete_position(db, actor.owner_id, position_id)
    return None
