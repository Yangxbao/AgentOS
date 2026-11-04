"""有效能力 = Adapter 能力 ∩ 模型能力 ∩ 授权能力（B5）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.model_gateway import catalog
from packages.model_gateway.credentials import has_credential
from packages.persistence.models import Employee, EmployeePosition, ModelConnection, Position

ADAPTER_CAPS = {
    "streaming": True,
    "interruptible": False,
    "structured_output": True,
    "tool_calling": True,
    "file_ops": False,
    "approval_hook": False,
    "session_resume": False,
    "usage_report": True,
}


def employee_capabilities(session: Session, employee: Employee) -> dict:
    connection = session.get(ModelConnection, employee.primary_model_id)
    model_info = catalog.capabilities_of(connection.model if connection else "")
    links = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
    ).scalars().all()
    tags: set[str] = set()
    for link in links:
        position = session.get(Position, link.position_id)
        if position:
            tags.update(position.review_capability_tags or [])
    tags.update(employee.tools_allowed or [])

    effective: dict[str, bool | None] = {}
    for key in ("streaming", "structured_output", "tool_calling", "file_ops", "usage_report"):
        adapter_ok = ADAPTER_CAPS.get(key, False)
        model_value = model_info.get(key)
        if model_value is None:
            effective[key] = None if not model_info.get("known") else False
        else:
            effective[key] = bool(adapter_ok and model_value)

    return {
        "employee_id": employee.id,
        "adapter": ADAPTER_CAPS,
        "model": model_info,
        "authorized_tools": employee.tools_allowed or [],
        "domain_tags": sorted(tags),
        "model_available": bool(
            connection and connection.enabled and has_credential(connection.api_key_ref)
        ),
        "effective": effective,
        "limitation": "domain_tags 复用岗位 review_capability_tags；M2 将独立建模 position.capability_tags",
    }
