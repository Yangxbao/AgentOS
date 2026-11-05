"""执行前权限闸门（M2-B）：不通过就不调模型。

与 M1 一致：风险等级、工具授权、预算、模型可用性全部来自真实配置，
不做“执行时放宽”的例外。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from packages.model_gateway import catalog
from packages.model_gateway.credentials import has_credential
from packages.permissions.effective import compute_effective_permissions
from packages.persistence.models import Employee, ModelConnection, Task
from packages.shared.errors import DomainError

RISK_ORDER = ["low", "medium", "high", "critical"]
COST_ESTIMATE = {"local": 0.0, "budget": 0.01, "middle": 0.03, "premium": 0.08}


def steps_of(task: Task) -> list[dict]:
    steps = list((task.plan or {}).get("steps") or [])
    if steps:
        return steps
    return [{
        "id": "s1",
        "employee_id": task.assignee_employee_id,
        "instruction": task.instruction or task.objective,
        "tools": list((task.context or {}).get("required_tools") or []),
    }]


def _required_tools(task: Task, employee_id: str) -> set[str]:
    return {
        tool
        for step in steps_of(task)
        if step.get("employee_id") == employee_id
        for tool in (step.get("tools") or [])
    }


def _estimated_cost(model: str, task: Task, employee_id: str) -> float:
    info = catalog.model_info(model)
    tier = info.cost_tier if info is not None else "middle"
    per_call = COST_ESTIMATE.get(tier, 0.03)
    count = sum(1 for step in steps_of(task) if step.get("employee_id") == employee_id)
    return round(per_call * max(1, count), 4)


def check_execution(
    session: Session, task: Task, employee: Employee, connection: ModelConnection | None, mode: str
) -> dict:
    if employee.deleted_at is not None or employee.status != "active":
        raise DomainError(
            "EXECUTION_PERMISSION_DENIED", "执行员工不是在职状态", 403,
            {"employee_id": employee.id, "state": employee.status},
        )
    if task.company_id and employee.company_id != task.company_id:
        raise DomainError("EXECUTION_PERMISSION_DENIED", "执行员工不属于任务所在公司", 403)

    permissions = compute_effective_permissions(session, employee.owner_id, employee.id)["permissions"]
    max_risk = permissions.get("max_risk_level", "medium")
    if RISK_ORDER.index(task.risk_level) > RISK_ORDER.index(max_risk):
        raise DomainError(
            "EXECUTION_PERMISSION_DENIED",
            f"任务风险等级 {task.risk_level} 超出员工授权上限 {max_risk}",
            403,
            {"risk_level": task.risk_level, "max_risk_level": max_risk},
        )

    required = _required_tools(task, employee.id)
    allowed = set(employee.tools_allowed or [])
    denied = sorted(required - allowed)
    if denied:
        raise DomainError(
            "EXECUTION_PERMISSION_DENIED", f"员工未获授权使用工具：{','.join(denied)}", 403,
            {"denied": denied},
        )

    if mode == "real":
        if connection is None or not connection.enabled or not has_credential(connection.api_key_ref):
            raise DomainError(
                "EXECUTION_MODEL_UNAVAILABLE", "模型连接不可用或凭据缺失", 409,
                {"employee_id": employee.id},
            )
        estimated = _estimated_cost(connection.model, task, employee.id)
        if task.budget_usd is not None and estimated > float(task.budget_usd):
            raise DomainError(
                "EXECUTION_BUDGET_EXCEEDED",
                f"预计成本 {estimated} 超过任务预算 {task.budget_usd}", 409,
                {"estimated_usd": estimated, "budget_usd": task.budget_usd},
            )
    else:
        estimated = 0.0

    return {
        "permissions": {
            "max_risk_level": max_risk,
            "file_ops": permissions.get("file_ops"),
            "shell": permissions.get("shell"),
            "network": permissions.get("network"),
        },
        "required_tools": sorted(required),
        "estimated_usd": estimated,
    }
