"""任务计划（M2-C）：校验、拓扑波次、子任务映射。

计划是“谁在什么时候做什么”的显式声明；不允许 Agent 自行无限拆分。
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from packages.persistence.models import Company, Employee
from packages.shared.errors import DomainError

MAX_STEPS = 20
MAX_DEPTH = 3
MAX_PARALLEL = 8
STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")


def _employee(session: Session, owner_id: str, company_id: str, employee_id: str, label: str) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.owner_id != owner_id or employee.deleted_at is not None:
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}不存在：{employee_id}", 422)
    if employee.company_id != company_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}必须属于同一公司", 422)
    if employee.status != "active":
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}不是在职状态：{employee.name}", 422)
    return employee


def normalize_plan(session: Session, owner_id: str, task) -> dict:
    """校验并规范化任务计划；空计划表示单员工单步执行。"""
    raw = task.plan or {}
    steps = raw.get("steps") or []
    if not steps:
        return {"version": 1, "steps": [], "max_parallel": 1}

    if len(steps) > MAX_STEPS:
        raise DomainError("TASK_PLAN_INVALID", f"步骤数不能超过 {MAX_STEPS}", 422)
    # M3-B：深度上限由后端强制（任务级 max_depth 可在 1..4 内配置，默认 3）
    max_depth = getattr(task, "max_depth", None) or MAX_DEPTH
    max_depth = max(1, min(int(max_depth), 4))
    if task.depth + 1 > max_depth:
        raise DomainError(
            "TASK_DEPTH_EXCEEDED", f"任务层级不能超过 {max_depth} 层", 409,
            {"depth": task.depth, "max_depth": max_depth},
        )

    company = session.get(Company, task.company_id)
    if company is None or company.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"公司不存在：{task.company_id}", 404)

    normalized: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(steps):
        step_id = str(item.get("id") or f"s{index + 1}")
        if not STEP_ID_PATTERN.match(step_id):
            raise DomainError("TASK_PLAN_INVALID", f"步骤 id 非法：{step_id}", 422)
        if step_id in seen:
            raise DomainError("TASK_PLAN_INVALID", f"步骤 id 重复：{step_id}", 422)
        seen.add(step_id)
        # M3-B 动态分配：步骤可省略 employee_id，按能力/工具/风险自动选人并记录 decision
        auto_assigned = False
        decision_id: str | None = None
        employee_id = item.get("employee_id")
        if not employee_id:
            from packages.permissions.assignment import preview_assignment

            preview = preview_assignment(session, owner_id, task.company_id, {
                "risk_level": getattr(task, "risk_level", "low") or "low",
                "required_tools": list(item.get("tools") or []),
                "context": {"step_id": step_id, "plan_auto_assign": True},
            })
            candidates = preview.get("candidates") or []
            if not candidates:
                raise DomainError(
                    "TASK_PLAN_INVALID",
                    f"步骤 {step_id} 未指定员工且无可自动分配的候选（需能力/工具匹配）",
                    422, {"step_id": step_id, "excluded": preview.get("excluded") or []},
                )
            employee_id = candidates[0]["employee_id"]
            auto_assigned = True
            decision_id = preview.get("decision_id")
        employee = _employee(session, owner_id, task.company_id, employee_id, "执行员工")
        instruction = str(item.get("instruction") or "").strip()
        if not instruction:
            raise DomainError("TASK_PLAN_INVALID", f"步骤 {step_id} 的执行指令不能为空", 422)
        depends = item.get("depends_on") or []
        if not isinstance(depends, list) or any(not isinstance(dep, str) for dep in depends):
            raise DomainError("TASK_PLAN_INVALID", f"步骤 {step_id} 的 depends_on 必须是字符串数组", 422)
        tools = item.get("tools") or []
        if not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools):
            raise DomainError("TASK_PLAN_INVALID", f"步骤 {step_id} 的 tools 必须是字符串数组", 422)
        denied = sorted(set(tools) - set(employee.tools_allowed or []))
        if denied:
            raise DomainError(
                "TASK_PLAN_INVALID",
                f"步骤 {step_id} 要求的工具未授权给 {employee.name}：{','.join(denied)}",
                422,
                {"step_id": step_id, "denied": denied},
            )
        # 视觉/超时扩展字段：透传给执行器（images → 步骤级图片注入；timeout_s → 步骤级超时）
        images = item.get("images") or []
        if not isinstance(images, list) or any(not isinstance(i, dict) for i in images):
            raise DomainError(
                "TASK_PLAN_INVALID",
                f"步骤 {step_id} 的 images 必须是对象数组（每项含 workspace_id/path）",
                422,
            )
        timeout_s = item.get("timeout_s")
        if timeout_s is not None:
            try:
                timeout_s = max(0.05, min(float(timeout_s), 3600.0))
            except (TypeError, ValueError):
                timeout_s = None
        normalized.append({
            "id": step_id,
            "title": str(item.get("title") or "").strip(),
            "employee_id": employee.id,
            "employee_name": employee.name,
            "auto_assigned": auto_assigned,
            "assignment_decision_id": decision_id,
            "instruction": instruction,
            "deliverable": str(item.get("deliverable") or "").strip(),
            "depends_on": list(dict.fromkeys(depends)),
            "tools": tools,
            "images": images,
            "timeout_s": timeout_s,
        })

    known = {step["id"] for step in normalized}
    for step in normalized:
        for dep in step["depends_on"]:
            if dep == step["id"]:
                raise DomainError("TASK_PLAN_INVALID", f"步骤 {step['id']} 不能依赖自己", 422)
            if dep not in known:
                raise DomainError(
                    "TASK_PLAN_INVALID", f"步骤 {step['id']} 依赖不存在的步骤：{dep}", 422
                )

    topological_waves(normalized)  # 有环会抛 TASK_PLAN_CYCLE

    max_parallel = raw.get("max_parallel", 4)
    if not isinstance(max_parallel, int) or not 1 <= max_parallel <= MAX_PARALLEL:
        raise DomainError("TASK_PLAN_INVALID", f"max_parallel 必须是 1–{MAX_PARALLEL}", 422)

    return {"version": 1, "steps": normalized, "max_parallel": max_parallel}


def topological_waves(steps: list[dict]) -> list[list[dict]]:
    """Kahn 分层：同一波次内无依赖，可并行。"""
    by_id = {step["id"]: step for step in steps}
    remaining = {step["id"]: set(step.get("depends_on") or []) for step in steps}
    waves: list[list[dict]] = []
    while remaining:
        ready = sorted([sid for sid, deps in remaining.items() if not deps])
        if not ready:
            raise DomainError(
                "TASK_PLAN_CYCLE", "步骤依赖存在环，无法调度", 409,
                {"remaining": sorted(remaining)},
            )
        waves.append([by_id[sid] for sid in ready])
        for sid in ready:
            remaining.pop(sid)
        for deps in remaining.values():
            deps.difference_update(ready)
    return waves


def step_map(task) -> dict[str, dict]:
    return {step["id"]: step for step in (task.plan or {}).get("steps", [])}
