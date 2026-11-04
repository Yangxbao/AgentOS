"""岗位服务（B2）：职责模板 + 默认权限 + 审查资格（can_review）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Company, Department, Position
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .common import check_version, ensure_unique_name, get_or_404, iso_utc, require


def serialize_position(position: Position) -> dict:
    return {
        "id": position.id,
        "company_id": position.company_id,
        "department_id": position.department_id,
        "name": position.name,
        "level": position.level,
        "is_managerial": position.is_managerial,
        "can_review": position.can_review,
        "review_capability_tags": position.review_capability_tags,
        "responsibilities": position.responsibilities,
        "default_permissions": position.default_permissions,
        "created_at": iso_utc(position.created_at),
        "updated_at": iso_utc(position.updated_at),
    }


def _ensure_company_active(session: Session, owner_id: str, company_id: str) -> Company:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ARCHIVED", "公司已归档，不能修改岗位", 409)
    return company


def _ensure_department(session: Session, owner_id: str, company_id: str, department_id: str | None) -> None:
    if department_id is None:
        return
    department = get_or_404(session, Department, department_id, owner_id, "部门")
    if department.company_id != company_id:
        raise DomainError("BR_POSITION_DEPARTMENT_COMPANY_MISMATCH", "岗位所属部门必须属于同一公司", 409)


def create_position(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str,
    department_id: str | None = None,
    level: str = "",
    is_managerial: bool = False,
    can_review: bool = False,
    review_capability_tags: list[str] | None = None,
    responsibilities: str = "",
    default_permissions: dict | None = None,
) -> Position:
    _ensure_company_active(session, owner_id, company_id)
    clean = name.strip()
    require(bool(clean), "VALIDATION_ERROR", "岗位名称不能为空", 422)
    ensure_unique_name(
        session, Position, owner_id, clean, company_id=company_id,
        code="BR_POSITION_NAME_TAKEN", entity_label="岗位名称",
    )
    _ensure_department(session, owner_id, company_id, department_id)

    position = Position(
        id=new_id(),
        owner_id=owner_id,
        company_id=company_id,
        department_id=department_id,
        name=clean,
        level=level,
        is_managerial=is_managerial,
        can_review=can_review,
        review_capability_tags=review_capability_tags or [],
        responsibilities=responsibilities,
        default_permissions=default_permissions or {},
    )
    session.add(position)
    session.commit()
    session.refresh(position)
    return position


def get_position(session: Session, owner_id: str, position_id: str) -> Position:
    return get_or_404(session, Position, position_id, owner_id, "岗位")


def update_position(
    session: Session,
    owner_id: str,
    position_id: str,
    *,
    name: str | None = None,
    department_id: str | None = None,
    department_id_provided: bool = False,
    level: str | None = None,
    is_managerial: bool | None = None,
    can_review: bool | None = None,
    review_capability_tags: list[str] | None = None,
    responsibilities: str | None = None,
    default_permissions: dict | None = None,
    expected_updated_at: str | None = None,
) -> Position:
    position = get_position(session, owner_id, position_id)
    _ensure_company_active(session, owner_id, position.company_id)
    check_version(expected_updated_at, position.updated_at, "岗位")

    if name is not None:
        clean = name.strip()
        require(bool(clean), "VALIDATION_ERROR", "岗位名称不能为空", 422)
        ensure_unique_name(
            session, Position, owner_id, clean, company_id=position.company_id,
            exclude_id=position.id, code="BR_POSITION_NAME_TAKEN", entity_label="岗位名称",
        )
        position.name = clean
    if department_id_provided:
        _ensure_department(session, owner_id, position.company_id, department_id)
        position.department_id = department_id
    if level is not None:
        position.level = level
    if is_managerial is not None:
        position.is_managerial = is_managerial
    if can_review is not None:
        position.can_review = can_review
    if review_capability_tags is not None:
        position.review_capability_tags = review_capability_tags
    if responsibilities is not None:
        position.responsibilities = responsibilities
    if default_permissions is not None:
        position.default_permissions = {**position.default_permissions, **default_permissions}

    session.commit()
    session.refresh(position)
    return position


def delete_position(session: Session, owner_id: str, position_id: str) -> None:
    position = get_position(session, owner_id, position_id)
    # 员工-岗位引用检查在 B3 引入 employee_position 后补充（BR 待接）
    session.delete(position)
    session.commit()


def list_positions(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    department_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Position], int]:
    _ensure_company_active(session, owner_id, company_id)
    stmt = select(Position).where(Position.company_id == company_id)
    if department_id is not None:
        stmt = stmt.where(Position.department_id == department_id)
    total = len(session.execute(stmt).scalars().all())
    rows = session.execute(
        stmt.order_by(Position.name).offset(offset).limit(limit)
    ).scalars().all()
    return list(rows), total
