"""公司接口 API-01..05。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, Page, PageParams, get_actor, get_db
from apps.api.schemas.org import CompanyCreate, CompanyOut, CompanyUpdate
from packages.organization import (
    archive_company,
    create_company,
    get_company,
    list_companies,
    update_company,
)
from packages.organization.companies import serialize_company

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyOut])
def list_companies_endpoint(
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    rows, total = list_companies(db, actor.owner_id, params.offset, params.page_size)
    return {"items": [serialize_company(c) for c in rows], "total": total,
            "page": params.page, "page_size": params.page_size}


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company_endpoint(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    company = create_company(
        db, actor.owner_id, name=payload.name, description=payload.description, policy=payload.policy
    )
    return serialize_company(company)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return serialize_company(get_company(db, actor.owner_id, company_id))


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company_endpoint(
    company_id: str,
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    company = update_company(
        db, actor.owner_id, company_id,
        name=payload.name, description=payload.description, policy=payload.policy,
        expected_updated_at=payload.expected_updated_at,
    )
    return serialize_company(company)


@router.post("/{company_id}/archive", response_model=CompanyOut)
def archive_company_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return serialize_company(archive_company(db, actor.owner_id, company_id))
