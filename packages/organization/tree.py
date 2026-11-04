"""组织树组装：一次查询 + 内存组树，避免 N+1。

节点包含：部门基本信息、该部门岗位、子部门、员工占位（B2 尚无员工，employee_count=0）。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Company, Department, Position

from .common import get_or_404
from .departments import serialize_department
from .positions import serialize_position


def build_org_tree(session: Session, owner_id: str, company_id: str) -> dict:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    departments = list(
        session.execute(
            select(Department)
            .where(Department.company_id == company_id)
            .order_by(Department.depth, Department.sort_order, Department.name)
        ).scalars().all()
    )
    positions = list(
        session.execute(
            select(Position).where(Position.company_id == company_id).order_by(Position.name)
        ).scalars().all()
    )

    positions_by_department: dict[str | None, list[dict]] = {}
    for position in positions:
        positions_by_department.setdefault(position.department_id, []).append(serialize_position(position))

    nodes: dict[str, dict] = {}
    for department in departments:
        node = serialize_department(department)
        node["positions"] = positions_by_department.get(department.id, [])
        node["children"] = []
        node["employee_count"] = 0
        nodes[department.id] = node

    roots: list[dict] = []
    for department in departments:
        node = nodes[department.id]
        if department.parent_id and department.parent_id in nodes:
            nodes[department.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "status": company.status,
            "policy": company.policy,
        },
        "departments": roots,
        "unassigned_positions": positions_by_department.get(None, []),
    }
