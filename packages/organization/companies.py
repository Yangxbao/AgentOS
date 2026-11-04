"""公司服务（B2）。

策略默认值：最小权限、要求跨模型审查、禁止下级审查上级（见 M1_PLAN_HANDOFF.md §11）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Company
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .common import check_version, ensure_unique_name, get_or_404, iso_utc, require

DEFAULT_POLICY: dict[str, Any] = {
    "max_risk_level": "medium",
    "allowed_providers": [],
    "default_budget_usd": None,
    "require_cross_model_review": True,
    "review_policy": {"allow_subordinate_review": False, "prefer_cross_model": True},
}


def serialize_company(company: Company) -> dict:
    return {
        "id": company.id,
        "name": company.name,
        "description": company.description,
        "policy": company.policy,
        "status": company.status,
        "created_at": iso_utc(company.created_at),
        "updated_at": iso_utc(company.updated_at),
    }


def create_company(
    session: Session,
    owner_id: str,
    *,
    name: str,
    description: str = "",
    policy: dict | None = None,
) -> Company:
    clean = name.strip()
    require(bool(clean), "VALIDATION_ERROR", "公司名称不能为空", 422)
    ensure_unique_name(
        session, Company, owner_id, clean,
        code="BR_COMPANY_NAME_TAKEN", entity_label="公司名称",
    )
    company = Company(
        id=new_id(),
        owner_id=owner_id,
        name=clean,
        description=description,
        policy={**DEFAULT_POLICY, **(policy or {})},
        status="active",
    )
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def list_companies(session: Session, owner_id: str, offset: int, limit: int) -> tuple[list[Company], int]:
    base = select(Company).where(Company.owner_id == owner_id)
    total = len(session.execute(base).scalars().all())
    rows = session.execute(
        base.order_by(Company.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return list(rows), total


def get_company(session: Session, owner_id: str, company_id: str) -> Company:
    return get_or_404(session, Company, company_id, owner_id, "公司")


def update_company(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    policy: dict | None = None,
    expected_updated_at: str | None = None,
) -> Company:
    company = get_company(session, owner_id, company_id)
    check_version(expected_updated_at, company.updated_at, "公司")
    if name is not None:
        clean = name.strip()
        require(bool(clean), "VALIDATION_ERROR", "公司名称不能为空", 422)
        ensure_unique_name(
            session, Company, owner_id, clean, exclude_id=company.id,
            code="BR_COMPANY_NAME_TAKEN", entity_label="公司名称",
        )
        company.name = clean
    if description is not None:
        company.description = description
    if policy is not None:
        merged = {**company.policy, **policy}
        merged["review_policy"] = {**company.policy.get("review_policy", {}), **policy.get("review_policy", {})}
        company.policy = merged
    session.commit()
    session.refresh(company)
    return company


def archive_company(session: Session, owner_id: str, company_id: str) -> Company:
    company = get_company(session, owner_id, company_id)
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ALREADY_ARCHIVED", "公司已归档", 409)
    company.status = "archived"
    session.commit()
    session.refresh(company)
    return company
