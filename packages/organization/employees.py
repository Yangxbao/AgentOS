"""员工服务（B3）：身份与模型解耦、汇报链校验、软删除、模型切换审计。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.model_gateway import catalog
from packages.persistence.models import (
    Company,
    Department,
    Employee,
    EmployeePosition,
    ModelConnection,
    ModelSwitchLog,
    Position,
)
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .common import check_version, get_or_404, iso_utc, require

MAX_REPORT_CHAIN = 20


def _company(session: Session, owner_id: str, company_id: str) -> Company:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ARCHIVED", "公司已归档，不能修改员工", 409)
    return company


def _validate_department(session: Session, owner_id: str, company_id: str, department_id: str | None) -> None:
    if department_id is None:
        return
    department = get_or_404(session, Department, department_id, owner_id, "部门")
    if department.company_id != company_id:
        raise DomainError("BR_EMPLOYEE_DEPARTMENT_COMPANY_MISMATCH", "员工部门必须属于同一公司", 409)


def _validate_model(session: Session, owner_id: str, company_id: str, model_id: str, label: str) -> ModelConnection:
    conn = get_or_404(session, ModelConnection, model_id, owner_id, label)
    if conn.company_id != company_id:
        raise DomainError("BR_EMPLOYEE_MODEL_COMPANY_MISMATCH", "模型连接必须属于同一公司", 409)
    return conn


def _reports_chain(session: Session, employee: Employee) -> list[Employee]:
    chain: list[Employee] = []
    seen: set[str] = set()
    current = employee.reports_to
    while current and len(chain) < MAX_REPORT_CHAIN + 1:
        if current in seen:
            raise DomainError("BR_REPORT_CYCLE", "汇报关系存在环", 409)
        seen.add(current)
        manager = session.get(Employee, current)
        if manager is None:
            break
        chain.append(manager)
        current = manager.reports_to
    return chain


def _validate_reports_to(
    session: Session, owner_id: str, company_id: str, employee: Employee | None, reports_to: str | None
) -> None:
    if not reports_to:
        return
    if employee is not None and reports_to == employee.id:
        raise DomainError("BR_REPORT_SELF", "员工不能汇报给自己", 409)
    manager = get_or_404(session, Employee, reports_to, owner_id, "汇报对象")
    if manager.company_id != company_id:
        raise DomainError("BR_REPORT_COMPANY_MISMATCH", "汇报对象必须属于同一公司", 409)
    if manager.status != "active":
        raise DomainError("BR_REPORT_INACTIVE", "汇报对象必须是在职员工", 409)
    if employee is not None:
        # 成环：新上级的所有上级中不能出现自己
        current: str | None = manager.id
        seen: set[str] = set()
        depth = 0
        while current and depth <= MAX_REPORT_CHAIN:
            if current == employee.id:
                raise DomainError("BR_REPORT_CYCLE", "汇报关系不得成环", 409)
            if current in seen:
                break
            seen.add(current)
            row = session.get(Employee, current)
            current = row.reports_to if row else None
            depth += 1
        if depth > MAX_REPORT_CHAIN:
            raise DomainError("BR_REPORT_CHAIN_TOO_LONG", f"汇报链不得超过 {MAX_REPORT_CHAIN} 层", 409)


def _validate_positions(
    session: Session, owner_id: str, company_id: str, employee_id: str, positions: list[dict]
) -> None:
    if not positions:
        return
    primaries = [p for p in positions if p.get("is_primary")]
    if len(primaries) > 1:
        raise DomainError("VALIDATION_ERROR", "只能有一个主岗", 422)
    seen: set[str] = set()
    for item in positions:
        position_id = item["position_id"]
        if position_id in seen:
            raise DomainError("VALIDATION_ERROR", f"岗位重复：{position_id}", 422)
        seen.add(position_id)
        position = get_or_404(session, Position, position_id, owner_id, "岗位")
        if position.company_id != company_id:
            raise DomainError("BR_EMPLOYEE_POSITION_COMPANY_MISMATCH", "岗位必须属于同一公司", 409)
        session.merge(EmployeePosition(
            employee_id=employee_id,
            position_id=position_id,
            is_primary=bool(item.get("is_primary")),
            department_id=item.get("department_id") or position.department_id,
        ))


def serialize_employee(session: Session, employee: Employee) -> dict:
    rows = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
    ).scalars().all()
    positions = []
    for row in rows:
        position = session.get(Position, row.position_id)
        positions.append({
            "position_id": row.position_id,
            "name": position.name if position else "",
            "is_primary": row.is_primary,
            "department_id": row.department_id,
        })
    primary = session.get(ModelConnection, employee.primary_model_id)
    fallback = session.get(ModelConnection, employee.fallback_model_id) if employee.fallback_model_id else None
    from .connections import connection_health, serialize_connection

    health, health_source = (None, "unknown")
    if primary:
        health, health_source = connection_health(session, primary)
    return {
        "id": employee.id,
        "company_id": employee.company_id,
        "department_id": employee.department_id,
        "name": employee.name,
        "avatar": employee.avatar,
        "title": employee.title,
        "bio": employee.bio,
        "personality": employee.personality,
        "status": employee.status,
        "reports_to": employee.reports_to,
        "primary_model_id": employee.primary_model_id,
        "fallback_model_id": employee.fallback_model_id,
        "adapter_type": employee.adapter_type,
        "cli_profile": employee.cli_profile,
        "tools_allowed": employee.tools_allowed,
        "permission_profile": employee.permission_profile,
        "capabilities_declared": employee.capabilities_declared,
        "prompt_active_version": employee.prompt_active_version,
        "positions": positions,
        "model": {
            "primary": serialize_connection(primary) if primary else None,
            "fallback": serialize_connection(fallback) if fallback else None,
            "health": health,
            "health_source": health_source,
        },
        "deleted_at": iso_utc(employee.deleted_at),
        "created_at": iso_utc(employee.created_at),
        "updated_at": iso_utc(employee.updated_at),
    }


def _validate_tools_allowed(tools_allowed: list[str] | None) -> list[str]:
    """员工工具白名单必须来自真实工具注册中心；非法名称写库前拒绝（422）。

    白名单只是五层权限的第 4 层之一，此处校验的是"名称合法"，不等于"可执行"。
    """
    if not tools_allowed:
        return []
    from packages.tools.registry import REGISTRY

    unknown = sorted(set(tools_allowed) - set(REGISTRY))
    if unknown:
        raise DomainError(
            "VALIDATION_ERROR",
            f"未注册的工具名称：{', '.join(unknown)}",
            422, {"unknown": unknown},
        )
    return sorted(set(tools_allowed))


def create_employee(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str,
    primary_model_id: str,
    fallback_model_id: str | None = None,
    department_id: str | None = None,
    title: str = "",
    avatar: str = "",
    bio: str = "",
    personality: str = "",
    reports_to: str | None = None,
    adapter_type: str = "api",
    cli_profile: dict | None = None,
    tools_allowed: list[str] | None = None,
    permission_profile: dict | None = None,
    positions: list[dict] | None = None,
) -> Employee:
    _company(session, owner_id, company_id)
    clean = name.strip()
    require(bool(clean), "VALIDATION_ERROR", "员工姓名不能为空", 422)
    existing = session.execute(
        select(Employee).where(
            Employee.company_id == company_id, Employee.name == clean, Employee.deleted_at.is_(None)
        )
    ).first()
    if existing is not None:
        raise DomainError("BR_EMPLOYEE_NAME_TAKEN", f"同公司已有员工：{clean}", 409)

    _validate_department(session, owner_id, company_id, department_id)
    _validate_model(session, owner_id, company_id, primary_model_id, "主模型连接")
    if fallback_model_id:
        _validate_model(session, owner_id, company_id, fallback_model_id, "备用模型连接")
        if fallback_model_id == primary_model_id:
            raise DomainError("VALIDATION_ERROR", "主模型与备用模型不能相同", 422)

    employee = Employee(
        id=new_id(), owner_id=owner_id, company_id=company_id, department_id=department_id,
        name=clean, avatar=avatar, title=title, bio=bio, personality=personality,
        status="active", reports_to=None, primary_model_id=primary_model_id,
        fallback_model_id=fallback_model_id, adapter_type=adapter_type, cli_profile=cli_profile,
        tools_allowed=_validate_tools_allowed(tools_allowed),
        permission_profile=permission_profile or {},
        capabilities_declared={}, prompt_active_version=None,
    )
    session.add(employee)
    session.flush()
    _validate_reports_to(session, owner_id, company_id, employee, reports_to)
    employee.reports_to = reports_to
    _validate_positions(session, owner_id, company_id, employee.id, positions or [])
    session.commit()
    session.refresh(employee)
    return employee


def list_employees(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    status: str | None = None,
    department_id: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Employee], int]:
    _company(session, owner_id, company_id)
    stmt = select(Employee).where(Employee.company_id == company_id, Employee.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Employee.status == status)
    if department_id:
        stmt = stmt.where(Employee.department_id == department_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Employee.name.like(like) | Employee.title.like(like))
    total = len(session.execute(stmt).scalars().all())
    rows = session.execute(stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit)).scalars().all()
    return list(rows), total


def get_employee(session: Session, owner_id: str, employee_id: str) -> Employee:
    employee = get_or_404(session, Employee, employee_id, owner_id, "员工")
    if employee.deleted_at is not None:
        raise DomainError("NOT_FOUND", f"员工不存在：{employee_id}", 404)
    return employee


def update_employee(
    session: Session,
    owner_id: str,
    employee_id: str,
    *,
    name: str | None = None,
    title: str | None = None,
    avatar: str | None = None,
    bio: str | None = None,
    personality: str | None = None,
    department_id: str | None = None,
    department_id_provided: bool = False,
    reports_to: str | None = None,
    reports_to_provided: bool = False,
    tools_allowed: list[str] | None = None,
    permission_profile: dict | None = None,
    positions: list[dict] | None = None,
    expected_updated_at: str | None = None,
) -> Employee:
    employee = get_employee(session, owner_id, employee_id)
    _company(session, owner_id, employee.company_id)
    check_version(expected_updated_at, employee.updated_at, "员工")

    if name is not None:
        clean = name.strip()
        require(bool(clean), "VALIDATION_ERROR", "员工姓名不能为空", 422)
        dup = session.execute(
            select(Employee).where(
                Employee.company_id == employee.company_id, Employee.name == clean,
                Employee.deleted_at.is_(None), Employee.id != employee.id,
            )
        ).first()
        if dup is not None:
            raise DomainError("BR_EMPLOYEE_NAME_TAKEN", f"同公司已有员工：{clean}", 409)
        employee.name = clean
    if title is not None:
        employee.title = title
    if avatar is not None:
        employee.avatar = avatar
    if bio is not None:
        employee.bio = bio
    if personality is not None:
        employee.personality = personality
    if department_id_provided:
        _validate_department(session, owner_id, employee.company_id, department_id)
        employee.department_id = department_id
    if reports_to_provided:
        _validate_reports_to(session, owner_id, employee.company_id, employee, reports_to)
        employee.reports_to = reports_to
    if tools_allowed is not None:
        employee.tools_allowed = _validate_tools_allowed(tools_allowed)
    if permission_profile is not None:
        employee.permission_profile = {**employee.permission_profile, **permission_profile}
    if positions is not None:
        session.execute(
            EmployeePosition.__table__.delete().where(EmployeePosition.employee_id == employee.id)
        )
        _validate_positions(session, owner_id, employee.company_id, employee.id, positions)

    session.commit()
    session.refresh(employee)
    return employee


def set_status(session: Session, owner_id: str, employee_id: str, status: str) -> Employee:
    employee = get_employee(session, owner_id, employee_id)
    require(status in ("active", "disabled"), "VALIDATION_ERROR", "状态只能是 active 或 disabled", 422)
    employee.status = status
    session.commit()
    session.refresh(employee)
    return employee


def delete_employee(session: Session, owner_id: str, employee_id: str) -> None:
    employee = get_employee(session, owner_id, employee_id)
    reports = session.execute(
        select(Employee).where(
            Employee.reports_to == employee.id, Employee.deleted_at.is_(None), Employee.status == "active"
        )
    ).scalars().all()
    if reports:
        raise DomainError(
            "BR_EMPLOYEE_HAS_REPORTS",
            f"仍有 {len(reports)} 名在职员工汇报给该员工，请先调整汇报关系",
            409,
            {"employee_ids": [e.id for e in reports]},
        )
    employee.deleted_at = datetime.now(timezone.utc)
    employee.status = "archived"
    session.commit()


def bind_models(
    session: Session,
    owner_id: str,
    employee_id: str,
    *,
    primary_model_id: str,
    fallback_model_id: str | None,
    reason: str = "",
    actor_id: str = "local",
) -> tuple[Employee, list[str]]:
    employee = get_employee(session, owner_id, employee_id)
    _company(session, owner_id, employee.company_id)
    old_primary = employee.primary_model_id
    new_primary = _validate_model(session, owner_id, employee.company_id, primary_model_id, "主模型连接")
    if fallback_model_id:
        _validate_model(session, owner_id, employee.company_id, fallback_model_id, "备用模型连接")
        if fallback_model_id == primary_model_id:
            raise DomainError("VALIDATION_ERROR", "主模型与备用模型不能相同", 422)

    warnings: list[str] = []
    old_connection = session.get(ModelConnection, old_primary) if old_primary else None
    old_info = catalog.capabilities_of(old_connection.model if old_connection else "")
    new_info = catalog.capabilities_of(new_primary.model)
    if old_info.get("known") and new_info.get("known"):
        if old_info.get("structured_output") and not new_info.get("structured_output"):
            warnings.append("新模型不支持 structured_output，结构化审查任务将无法派发给该员工")
        if old_info.get("tool_calling") and not new_info.get("tool_calling"):
            warnings.append("新模型不支持 tool_calling，工具类任务将无法派发给该员工")
        if (old_info.get("context_window") or 0) > (new_info.get("context_window") or 0):
            warnings.append(
                f"新模型上下文窗口更小（{new_info.get('context_window')} < {old_info.get('context_window')}）"
            )
    elif not new_info.get("known"):
        warnings.append("新模型不在本地目录中，能力差异无法预判")

    now = datetime.now(timezone.utc)
    if old_primary != primary_model_id:
        session.add(ModelSwitchLog(
            id=new_id(), owner_id=owner_id, employee_id=employee.id,
            from_model_id=old_primary, to_model_id=primary_model_id, slot="primary",
            actor_type="user", actor_id=actor_id, reason=reason,
        ))
    if employee.fallback_model_id != fallback_model_id:
        session.add(ModelSwitchLog(
            id=new_id(), owner_id=owner_id, employee_id=employee.id,
            from_model_id=employee.fallback_model_id, to_model_id=fallback_model_id, slot="fallback",
            actor_type="user", actor_id=actor_id, reason=reason,
        ))
    employee.primary_model_id = primary_model_id
    employee.fallback_model_id = fallback_model_id
    employee.updated_at = now
    session.commit()
    session.refresh(employee)
    return employee, warnings


def switch_logs(session: Session, owner_id: str, employee_id: str, limit: int = 20) -> list[ModelSwitchLog]:
    get_employee(session, owner_id, employee_id)
    return list(session.execute(
        select(ModelSwitchLog)
        .where(ModelSwitchLog.employee_id == employee_id)
        .order_by(ModelSwitchLog.created_at.desc())
        .limit(limit)
    ).scalars().all())
