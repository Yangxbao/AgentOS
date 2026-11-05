"""工作区与授权（M3-A）。

规则：
- 根路径必须是已存在的绝对目录，且不能是盘符根/用户主目录/系统目录；
- 默认根 `data/workspaces/<slug>`（项目内，便于备份与清理）；
- 归档只改状态，不删磁盘文件；
- 授权撤销立即生效（每次工具调用现查，不缓存）；
- 有效写权限 = grant.access == write 且 workspace.mode == read_write。
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.db import REPO_ROOT
from packages.persistence.models import Company, Employee, EmployeeWorkspaceGrant, Workspace
from packages.shared.errors import DomainError

WORKSPACE_ROOT = REPO_ROOT / "data" / "workspaces"
ACCESS_LEVELS = ("read", "write")
MODES = ("read_only", "read_write")


def _forbidden_roots() -> set[str]:
    """禁止作为工作区根目录的位置（系统盘根/系统目录/用户主目录）。"""
    blocked: set[str] = set()
    home = Path.home()
    for candidate in (
        home,
        home.parent,
        Path("C:/Windows"),
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/ProgramData"),
        REPO_ROOT,  # 整个仓库不能作为工作区根（会暴露 data/ 与 .env）
    ):
        try:
            blocked.add(os.path.normcase(str(candidate.resolve())))
        except OSError:
            continue
    return blocked


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:48] or f"ws-{uuid.uuid4().hex[:6]}"


def validate_root(root: str, *, must_exist: bool = True) -> Path:
    if not root or not isinstance(root, str):
        raise DomainError("WORKSPACE_INVALID_ROOT", "root_path 必填", 422)
    path = Path(root)
    if not path.is_absolute():
        raise DomainError("WORKSPACE_INVALID_ROOT", "root_path 必须是绝对路径", 422)
    if path.parent == path:
        raise DomainError("WORKSPACE_INVALID_ROOT", "不允许把盘符根目录设为工作区", 422)
    if must_exist and not path.is_dir():
        raise DomainError("WORKSPACE_INVALID_ROOT", "root_path 必须是已存在的目录", 422)
    resolved = path.resolve()
    if os.path.normcase(str(resolved)) in _forbidden_roots():
        raise DomainError(
            "WORKSPACE_INVALID_ROOT", "该目录不允许作为工作区（系统目录/用户主目录/仓库根）", 422
        )
    return resolved


def serialize_workspace(row: Workspace, grants: list[dict] | None = None) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "name": row.name,
        "slug": row.slug,
        "root_path": row.root_path,
        "mode": row.mode,
        "status": row.status,
        "description": row.description,
        "created_by": row.created_by,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
        "grants": grants or [],
    }


def _company(session: Session, owner_id: str, company_id: str) -> Company:
    company = session.get(Company, company_id)
    if company is None or company.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"公司不存在：{company_id}", 404)
    return company


def create_workspace(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str,
    root_path: str | None = None,
    mode: str = "read_write",
    description: str = "",
    created_by: str = "local",
) -> Workspace:
    _company(session, owner_id, company_id)
    name = (name or "").strip()
    if not name:
        raise DomainError("VALIDATION_ERROR", "工作区名称不能为空", 422)
    if mode not in MODES:
        raise DomainError("VALIDATION_ERROR", f"mode 必须是 {MODES}", 422)

    duplicate = session.execute(
        select(Workspace).where(Workspace.company_id == company_id, Workspace.name == name)
    ).scalars().first()
    if duplicate is not None:
        raise DomainError("WORKSPACE_NAME_TAKEN", f"工作区名称已存在：{name}", 409)

    slug = _slugify(name)
    existing_slugs = {
        row.slug for row in session.execute(
            select(Workspace).where(Workspace.company_id == company_id)
        ).scalars().all()
    }
    base_slug, counter = slug, 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{counter}"
        counter += 1

    if root_path:
        resolved = validate_root(root_path)
    else:
        resolved = (WORKSPACE_ROOT / slug)
        resolved.mkdir(parents=True, exist_ok=True)
        resolved = validate_root(str(resolved))

    row = Workspace(
        id=uuid.uuid4().hex[:24], owner_id=owner_id, company_id=company_id,
        name=name, slug=slug, root_path=str(resolved), mode=mode,
        description=description, created_by=created_by,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def get_workspace(session: Session, owner_id: str, workspace_id: str) -> Workspace:
    row = session.get(Workspace, workspace_id)
    if row is None or row.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"工作区不存在：{workspace_id}", 404)
    return row


def list_workspaces(
    session: Session, owner_id: str, company_id: str, *, include_archived: bool = True
) -> list[Workspace]:
    stmt = select(Workspace).where(
        Workspace.owner_id == owner_id, Workspace.company_id == company_id
    )
    if not include_archived:
        stmt = stmt.where(Workspace.status == "active")
    return list(session.execute(stmt.order_by(Workspace.created_at)).scalars().all())


def update_workspace(
    session: Session, owner_id: str, workspace_id: str, *, name: str | None = None,
    description: str | None = None, mode: str | None = None,
) -> Workspace:
    row = get_workspace(session, owner_id, workspace_id)
    if row.status == "archived":
        raise DomainError("WORKSPACE_ARCHIVED", "已归档的工作区不能修改", 409)
    if name is not None:
        name = name.strip()
        if not name:
            raise DomainError("VALIDATION_ERROR", "工作区名称不能为空", 422)
        duplicate = session.execute(
            select(Workspace).where(
                Workspace.company_id == row.company_id,
                Workspace.name == name,
                Workspace.id != row.id,
            )
        ).scalars().first()
        if duplicate is not None:
            raise DomainError("WORKSPACE_NAME_TAKEN", f"工作区名称已存在：{name}", 409)
        row.name = name
    if description is not None:
        row.description = description
    if mode is not None:
        if mode not in MODES:
            raise DomainError("VALIDATION_ERROR", f"mode 必须是 {MODES}", 422)
        row.mode = mode
    session.commit()
    session.refresh(row)
    return row


def archive_workspace(session: Session, owner_id: str, workspace_id: str) -> Workspace:
    row = get_workspace(session, owner_id, workspace_id)
    if row.status != "archived":
        row.status = "archived"
        session.commit()
        session.refresh(row)
    return row


def grant_access(
    session: Session, owner_id: str, workspace_id: str, *,
    employee_id: str, access: str, granted_by: str = "local",
) -> EmployeeWorkspaceGrant:
    workspace = get_workspace(session, owner_id, workspace_id)
    if workspace.status == "archived":
        raise DomainError("WORKSPACE_ARCHIVED", "已归档的工作区不能授权", 409)
    if access not in ACCESS_LEVELS:
        raise DomainError("VALIDATION_ERROR", f"access 必须是 {ACCESS_LEVELS}", 422)
    employee = session.get(Employee, employee_id)
    if employee is None or employee.owner_id != owner_id or employee.deleted_at is not None:
        raise DomainError("NOT_FOUND", f"员工不存在：{employee_id}", 404)
    if employee.company_id != workspace.company_id:
        raise DomainError("WORKSPACE_COMPANY_MISMATCH", "员工与工作区不属于同一公司", 422)

    row = session.execute(
        select(EmployeeWorkspaceGrant).where(
            EmployeeWorkspaceGrant.employee_id == employee_id,
            EmployeeWorkspaceGrant.workspace_id == workspace_id,
        )
    ).scalars().first()
    if row is None:
        row = EmployeeWorkspaceGrant(
            id=uuid.uuid4().hex[:24], owner_id=owner_id, employee_id=employee_id,
            workspace_id=workspace_id, access=access, granted_by=granted_by,
        )
        session.add(row)
    else:
        row.access = access
        row.granted_by = granted_by
    session.commit()
    session.refresh(row)
    return row


def revoke_access(
    session: Session, owner_id: str, workspace_id: str, employee_id: str
) -> None:
    get_workspace(session, owner_id, workspace_id)
    row = session.execute(
        select(EmployeeWorkspaceGrant).where(
            EmployeeWorkspaceGrant.owner_id == owner_id,
            EmployeeWorkspaceGrant.workspace_id == workspace_id,
            EmployeeWorkspaceGrant.employee_id == employee_id,
        )
    ).scalars().first()
    if row is None:
        raise DomainError("NOT_FOUND", "该员工没有此工作区的授权", 404)
    session.delete(row)
    session.commit()


def list_grants(session: Session, owner_id: str, workspace_id: str) -> list[dict]:
    rows = session.execute(
        select(EmployeeWorkspaceGrant).where(
            EmployeeWorkspaceGrant.owner_id == owner_id,
            EmployeeWorkspaceGrant.workspace_id == workspace_id,
        )
    ).scalars().all()
    result = []
    for row in rows:
        employee = session.get(Employee, row.employee_id)
        result.append({
            "employee_id": row.employee_id,
            "employee_name": employee.name if employee else "(已删除)",
            "access": row.access,
            "granted_by": row.granted_by,
            "granted_at": iso_utc(row.granted_at),
        })
    return result


def resolve_grant(
    session: Session, owner_id: str, employee_id: str, workspace_id: str, need: str = "read"
) -> tuple[Workspace, EmployeeWorkspaceGrant]:
    """读取员工对工作区的有效权限；无授权/已归档/只读都抛明确错误。"""
    workspace = session.get(Workspace, workspace_id)
    if workspace is None or workspace.owner_id != owner_id:
        raise DomainError("WORKSPACE_NOT_GRANTED", "工作区不存在或未授权", 403)
    if workspace.status != "active":
        raise DomainError("WORKSPACE_ARCHIVED", "工作区已归档，工具不可访问", 403)
    grant = session.execute(
        select(EmployeeWorkspaceGrant).where(
            EmployeeWorkspaceGrant.employee_id == employee_id,
            EmployeeWorkspaceGrant.workspace_id == workspace_id,
        )
    ).scalars().first()
    if grant is None:
        raise DomainError(
            "WORKSPACE_NOT_GRANTED", "员工没有被授权访问该工作区", 403,
            {"workspace_id": workspace_id, "employee_id": employee_id},
        )
    if need == "write":
        if workspace.mode == "read_only":
            raise DomainError("WORKSPACE_READ_ONLY", "工作区是只读模式", 403)
        if grant.access != "write":
            raise DomainError("WORKSPACE_READ_ONLY", "员工对该工作区只有读权限", 403)
    return workspace, grant
