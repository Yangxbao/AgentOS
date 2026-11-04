"""三层权限：公司策略 ∩ 岗位默认 ∩ 员工覆盖（只许收窄）。

返回结构带来源链，前端权限面板直接消费。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import get_or_404
from packages.persistence.models import Company, Employee, EmployeePosition, Position
from packages.shared.errors import DomainError

SCOPE = ["none", "project_only", "company_readonly", "company_write"]
SHELL = ["deny", "approval_required", "allow_sandbox"]
NETWORK = ["deny", "allowlist", "allow_all"]
RISK = ["low", "medium", "high", "critical"]
ORDERED = {"workspace_scope": SCOPE, "shell": SHELL, "network": NETWORK, "max_risk_level": RISK}

DEFAULT_PERMISSIONS: dict[str, Any] = {
    "workspace_scope": "project_only",
    "file_ops": ["read"],
    "shell": "deny",
    "network": "deny",
    "max_risk_level": "medium",
    "tools": [],
    "budget_usd_per_task": None,
    "requires_approval": [
        "file_delete", "shell_exec", "network_upload",
        "system_config", "software_install", "service_deploy", "code_publish",
    ],
}


def _strictest(key: str, left: Any, right: Any) -> Any:
    if right is None:
        return left
    if left is None:
        return right
    if key in ORDERED:
        options = ORDERED[key]
        try:
            return left if options.index(left) <= options.index(right) else right
        except ValueError:
            return left
    if isinstance(left, list) and isinstance(right, list):
        if key == "requires_approval":
            return sorted(set(left) | set(right))
        return [item for item in left if item in right]
    if key == "budget_usd_per_task":
        try:
            return min(float(left), float(right))
        except (TypeError, ValueError):
            return left
    return left


def _permissive(key: str, left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    if key in ORDERED:
        options = ORDERED[key]
        try:
            return left if options.index(left) >= options.index(right) else right
        except ValueError:
            return left
    if isinstance(left, list) and isinstance(right, list):
        if key == "requires_approval":
            return sorted(set(left) | set(right))
        return sorted(set(left) | set(right))
    if key == "budget_usd_per_task":
        try:
            return max(float(left), float(right))
        except (TypeError, ValueError):
            return left
    return left


def _position_aggregate(positions: list[Position]) -> dict:
    aggregate: dict[str, Any] = {}
    for position in positions:
        for key, value in (position.default_permissions or {}).items():
            if key in aggregate:
                aggregate[key] = _permissive(key, aggregate[key], value)
            else:
                aggregate[key] = value
    return aggregate


def compute_effective_permissions(session: Session, owner_id: str, employee_id: str) -> dict:
    employee = get_or_404(session, Employee, employee_id, owner_id, "员工")
    company = get_or_404(session, Company, employee.company_id, owner_id, "公司")
    links = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
    ).scalars().all()
    positions = [session.get(Position, link.position_id) for link in links]
    positions = [p for p in positions if p is not None]

    company_base = {**DEFAULT_PERMISSIONS}
    company_base.update(company.policy.get("permissions", {}))
    position_layer = _position_aggregate(positions)
    employee_layer = employee.permission_profile or {}

    merged: dict[str, Any] = {}
    sources: dict[str, list[dict]] = {}
    for key in DEFAULT_PERMISSIONS:
        value = company_base.get(key)
        chain = [{"layer": "company", "value": value}]
        if key in position_layer:
            value = _strictest(key, value, position_layer[key])
            chain.append({"layer": "position", "value": position_layer[key]})
        if key in employee_layer:
            value = _strictest(key, value, employee_layer[key])
            chain.append({"layer": "employee", "value": employee_layer[key]})
        merged[key] = value
        sources[key] = chain
    return {"employee_id": employee.id, "permissions": merged, "sources": sources}


def merge_overrides(
    session: Session, owner_id: str, employee_id: str, overrides: dict
) -> dict:
    """员工覆盖只能收窄；任何放宽都拒绝（BR-13）。"""
    current = compute_effective_permissions(session, owner_id, employee_id)
    for key, value in overrides.items():
        if key not in DEFAULT_PERMISSIONS:
            raise DomainError("VALIDATION_ERROR", f"未知权限项：{key}", 422)
        original = current["permissions"].get(key)
        strict = _strictest(key, original, value)
        if strict != value and value != original:
            raise DomainError(
                "PERMISSION_WIDEN_DENIED",
                f"员工层不能放宽权限项 {key}（当前值 {original}）",
                403,
                {"key": key, "current": original, "requested": value},
            )
    employee = get_or_404(session, Employee, employee_id, owner_id, "员工")
    employee.permission_profile = {**(employee.permission_profile or {}), **overrides}
    session.commit()
    return compute_effective_permissions(session, owner_id, employee_id)
