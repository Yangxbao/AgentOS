"""部门服务（B2）：树结构、深度上限、成环校验、删除保护。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Company, Department, Position
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .common import check_version, ensure_unique_name, get_or_404, iso_utc, require

MAX_DEPTH_LEVELS = 8  # depth 0..7，最多 8 层


def serialize_department(department: Department) -> dict:
    return {
        "id": department.id,
        "company_id": department.company_id,
        "parent_id": department.parent_id,
        "name": department.name,
        "code": department.code,
        "description": department.description,
        "sort_order": department.sort_order,
        "depth": department.depth,
        "created_at": iso_utc(department.created_at),
        "updated_at": iso_utc(department.updated_at),
    }


def _company(session: Session, owner_id: str, company_id: str) -> Company:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ARCHIVED", "公司已归档，不能修改其组织架构", 409)
    return company


def _departments_of(session: Session, company_id: str) -> list[Department]:
    return list(
        session.execute(
            select(Department).where(Department.company_id == company_id)
        ).scalars().all()
    )


def _descendant_ids(departments: list[Department], root_id: str) -> set[str]:
    children: dict[str | None, list[str]] = {}
    for dept in departments:
        children.setdefault(dept.parent_id, []).append(dept.id)
    result: set[str] = set()
    stack = [root_id]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def _subtree_depth_ok(departments: list[Department], root_id: str, root_new_depth: int) -> bool:
    children: dict[str | None, list[str]] = {}
    for dept in departments:
        children.setdefault(dept.parent_id, []).append(dept.id)
    max_relative = 0
    stack = [(root_id, 0)]
    while stack:
        current, relative = stack.pop()
        max_relative = max(max_relative, relative)
        for child in children.get(current, []):
            stack.append((child, relative + 1))
    return root_new_depth + max_relative <= MAX_DEPTH_LEVELS - 1


def _apply_subtree_depth(departments: list[Department], root: Department, root_depth: int) -> None:
    children: dict[str | None, list[Department]] = {}
    for dept in departments:
        children.setdefault(dept.parent_id, []).append(dept)
    root.depth = root_depth
    stack = [(root, root_depth)]
    while stack:
        current, depth = stack.pop()
        for child in children.get(current.id, []):
            child.depth = depth + 1
            stack.append((child, depth + 1))


def _validate_parent(
    session: Session,
    owner_id: str,
    company_id: str,
    parent_id: str | None,
    self_id: str | None = None,
) -> Department | None:
    if parent_id is None:
        return None
    parent = get_or_404(session, Department, parent_id, owner_id, "上级部门")
    if parent.company_id != company_id:
        raise DomainError("BR_DEPARTMENT_PARENT_COMPANY_MISMATCH", "上级部门必须属于同一公司", 409)
    if self_id:
        require(parent.id != self_id, "BR_DEPARTMENT_CYCLE", "部门不能成为自己的上级", 409)
        siblings = _departments_of(session, company_id)
        if parent.id in _descendant_ids(siblings, self_id):
            raise DomainError("BR_DEPARTMENT_CYCLE", "不能把部门移动到自己的子部门下（会形成环）", 409)
    return parent


def create_department(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str,
    parent_id: str | None = None,
    code: str = "",
    description: str = "",
    sort_order: int = 0,
) -> Department:
    _company(session, owner_id, company_id)
    clean = name.strip()
    require(bool(clean), "VALIDATION_ERROR", "部门名称不能为空", 422)
    ensure_unique_name(
        session, Department, owner_id, clean, company_id=company_id,
        code="BR_DEPARTMENT_NAME_TAKEN", entity_label="部门名称",
    )
    parent = _validate_parent(session, owner_id, company_id, parent_id)
    depth = (parent.depth + 1) if parent else 0
    if depth > MAX_DEPTH_LEVELS - 1:
        raise DomainError("BR_DEPARTMENT_MAX_DEPTH", f"部门最多 {MAX_DEPTH_LEVELS} 层，已超出", 409)

    department = Department(
        id=new_id(),
        owner_id=owner_id,
        company_id=company_id,
        parent_id=parent.id if parent else None,
        name=clean,
        code=code,
        description=description,
        sort_order=sort_order,
        depth=depth,
    )
    session.add(department)
    session.commit()
    session.refresh(department)
    return department


def update_department(
    session: Session,
    owner_id: str,
    department_id: str,
    *,
    name: str | None = None,
    parent_id: str | None = None,
    parent_id_provided: bool = False,
    code: str | None = None,
    description: str | None = None,
    sort_order: int | None = None,
    expected_updated_at: str | None = None,
) -> Department:
    department = get_or_404(session, Department, department_id, owner_id, "部门")
    check_version(expected_updated_at, department.updated_at, "部门")

    if name is not None:
        clean = name.strip()
        require(bool(clean), "VALIDATION_ERROR", "部门名称不能为空", 422)
        ensure_unique_name(
            session, Department, owner_id, clean, company_id=department.company_id,
            exclude_id=department.id, code="BR_DEPARTMENT_NAME_TAKEN", entity_label="部门名称",
        )
        department.name = clean
    if code is not None:
        department.code = code
    if description is not None:
        department.description = description
    if sort_order is not None:
        department.sort_order = sort_order

    if parent_id_provided and parent_id != department.parent_id:
        parent = _validate_parent(
            session, owner_id, department.company_id, parent_id, self_id=department.id
        )
        new_depth = (parent.depth + 1) if parent else 0
        siblings = _departments_of(session, department.company_id)
        if not _subtree_depth_ok(siblings, department.id, new_depth):
            raise DomainError("BR_DEPARTMENT_MAX_DEPTH", f"移动后超过 {MAX_DEPTH_LEVELS} 层", 409)
        department.parent_id = parent.id if parent else None
        _apply_subtree_depth(siblings, department, new_depth)

    session.commit()
    session.refresh(department)
    return department


def move_department(
    session: Session,
    owner_id: str,
    department_id: str,
    *,
    new_parent_id: str | None,
    new_index: int = 0,
) -> Department:
    return update_department(
        session,
        owner_id,
        department_id,
        parent_id=new_parent_id,
        parent_id_provided=True,
        sort_order=new_index,
    )


def delete_department(session: Session, owner_id: str, department_id: str) -> None:
    department = get_or_404(session, Department, department_id, owner_id, "部门")
    child = session.execute(
        select(Department).where(Department.parent_id == department.id)
    ).first()
    if child is not None:
        raise DomainError(
            "BR_DEPARTMENT_HAS_CHILDREN",
            "部门下还有子部门，请先移动或删除子部门",
            409,
        )
    positions = session.execute(
        select(Position).where(Position.department_id == department.id)
    ).scalars().all()
    if positions:
        raise DomainError(
            "BR_DEPARTMENT_HAS_POSITIONS",
            f"部门下还有 {len(positions)} 个岗位，请先迁移或删除",
            409,
            {"position_ids": [p.id for p in positions]},
        )
    session.delete(department)
    session.commit()


def list_departments(session: Session, owner_id: str, company_id: str) -> list[Department]:
    _company(session, owner_id, company_id)
    return list(
        session.execute(
            select(Department)
            .where(Department.company_id == company_id)
            .order_by(Department.depth, Department.sort_order, Department.name)
        ).scalars().all()
    )
