"""任务中心领域服务（M2-A）：创建/编辑/列表/计划/入队/暂停/恢复/取消。

边界：本模块不执行模型调用；执行只由 packages.execution 负责。
所有状态迁移走 state.ensure_transition，非法迁移返回 409。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import (
    Company,
    Department,
    Employee,
    EmployeePosition,
    Position,
    Task,
    TaskApproval,
    TaskEvent,
    TaskRun,
)
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from . import state as st
from .plan import normalize_plan

PRIORITIES = {"low", "normal", "high", "urgent"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
MODES = {"auto", "real", "mock"}
APPROVAL_STAGES = {"before_run", "after_run"}
MAX_ACTIVE_RUN = ("queued", "running")


def _company(session: Session, owner_id: str, company_id: str) -> Company:
    company = session.get(Company, company_id)
    if company is None or company.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"公司不存在：{company_id}", 404)
    return company


def _task(session: Session, owner_id: str, task_id: str) -> Task:
    task = session.get(Task, task_id)
    if task is None or task.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"任务不存在：{task_id}", 404)
    return task


def _employee(session: Session, owner_id: str, company_id: str, employee_id: str, label: str) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.owner_id != owner_id or employee.deleted_at is not None:
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}不存在：{employee_id}", 422)
    if employee.company_id != company_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}必须属于同一公司", 422)
    if employee.status != "active":
        raise DomainError("TASK_ASSIGNEE_INVALID", f"{label}不是在职状态", 422)
    return employee


def _department(session: Session, owner_id: str, company_id: str, department_id: str | None) -> None:
    if department_id is None:
        return
    department = session.get(Department, department_id)
    if department is None or department.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"部门不存在：{department_id}", 404)
    if department.company_id != company_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", "部门必须属于同一公司", 422)


def employee_can_review(session: Session, employee: Employee) -> bool:
    links = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
    ).scalars().all()
    for link in links:
        position = session.get(Position, link.position_id)
        if position is not None and position.can_review:
            return True
    return False


def emit(session: Session, task: Task, run_id: str | None, type_: str, payload: dict | None = None) -> None:
    session.add(TaskEvent(task_id=task.id, task_run_id=run_id, type=type_, payload=payload or {}))


def _parse_due(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError("VALIDATION_ERROR", "due_at 必须是 ISO-8601 时间", 422) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _check_version(task: Task, expected_version: int | None) -> None:
    if expected_version is None:
        return
    if int(expected_version) != int(task.version):
        raise DomainError(
            "CONFLICT_STALE", "任务已被其他操作修改，请刷新后重试", 409,
            {"expected": expected_version, "actual": task.version},
        )


def _validate_choice(value: str, allowed: set[str], field: str) -> str:
    if value not in allowed:
        raise DomainError("VALIDATION_ERROR", f"{field} 必须是 {'/'.join(sorted(allowed))}", 422)
    return value


def _touch(task: Task) -> None:
    task.version = (task.version or 1) + 1


def serialize_task(task: Task, children_count: int = 0) -> dict:
    return {
        "id": task.id,
        "company_id": task.company_id,
        "department_id": task.department_id,
        "parent_task_id": task.parent_task_id,
        "root_task_id": task.root_task_id,
        "depth": task.depth,
        "title": task.title,
        "objective": task.objective,
        "instruction": task.instruction,
        "deliverable": task.deliverable,
        "priority": task.priority,
        "risk_level": task.risk_level,
        "state": task.state,
        "assignee_employee_id": task.assignee_employee_id,
        "reviewer_employee_id": task.reviewer_employee_id,
        "approval_required": task.approval_required,
        "approval_stage": task.approval_stage,
        "budget_usd": task.budget_usd,
        "execution_mode": task.execution_mode,
        "due_at": iso_utc(task.due_at),
        "plan": task.plan or {"version": 1, "steps": [], "max_parallel": 1},
        "result": task.result or {},
        "context": task.context or {},
        "rework_count": task.rework_count,
        "max_rework": task.max_rework,
        "plan_revision": task.plan_revision,
        "replan_count": task.replan_count,
        "max_depth": task.max_depth,
        "max_total_steps": task.max_total_steps,
        "cancel_requested": task.cancel_requested,
        "pause_requested": task.pause_requested,
        "children_count": children_count,
        "version": task.version,
        "started_at": iso_utc(task.started_at),
        "ended_at": iso_utc(task.ended_at),
        "created_at": iso_utc(task.created_at),
        "updated_at": iso_utc(task.updated_at),
    }


def create_task(session: Session, owner_id: str, company_id: str, data: dict) -> Task:
    company = _company(session, owner_id, company_id)
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ARCHIVED", "公司已归档，不能创建任务", 409)

    title = str(data.get("title") or "").strip()
    if not title:
        raise DomainError("VALIDATION_ERROR", "任务标题不能为空", 422)
    if len(title) > 200:
        raise DomainError("VALIDATION_ERROR", "任务标题不能超过 200 字", 422)

    assignee_id = data.get("assignee_employee_id")
    if not assignee_id:
        raise DomainError("TASK_ASSIGNEE_INVALID", "必须指定执行员工", 422)
    assignee = _employee(session, owner_id, company_id, assignee_id, "执行员工")

    department_id = data.get("department_id") or assignee.department_id
    _department(session, owner_id, company_id, department_id)

    reviewer_id = data.get("reviewer_employee_id")
    if reviewer_id:
        reviewer = _employee(session, owner_id, company_id, reviewer_id, "审核员工")
        if reviewer.id == assignee.id:
            raise DomainError("TASK_ASSIGNEE_INVALID", "审核人不能是执行人本人", 422)
        if not employee_can_review(session, reviewer):
            raise DomainError("APPROVAL_REVIEWER_INVALID", "审核员工不具备 can_review 审查资格", 422)

    priority = _validate_choice(str(data.get("priority") or "normal"), PRIORITIES, "priority")
    risk = _validate_choice(str(data.get("risk_level") or "low"), RISK_LEVELS, "risk_level")
    mode = _validate_choice(str(data.get("execution_mode") or "auto"), MODES, "execution_mode")
    stage = _validate_choice(
        str(data.get("approval_stage") or "before_run"), APPROVAL_STAGES, "approval_stage"
    )

    task = Task(
        id=new_id(), owner_id=owner_id, company_id=company_id,
        department_id=department_id, title=title,
        objective=str(data.get("objective") or ""),
        instruction=str(data.get("instruction") or ""),
        deliverable=str(data.get("deliverable") or ""),
        state="draft", priority=priority, risk_level=risk,
        assignee_employee_id=assignee.id, reviewer_employee_id=reviewer_id,
        approval_required=bool(data.get("approval_required")),
        approval_stage=stage, budget_usd=data.get("budget_usd"),
        execution_mode=mode, context=data.get("context") or {},
        plan={}, result={}, depth=0, version=1, created_by=owner_id,
        due_at=_parse_due(data.get("due_at")),
        max_rework=int(data.get("max_rework") or 3),
    )
    task.root_task_id = task.id
    session.add(task)
    session.flush()
    emit(session, task, None, "task.created", {
        "title": task.title, "assignee_employee_id": task.assignee_employee_id,
        "priority": task.priority, "risk_level": task.risk_level,
    })
    session.commit()
    session.refresh(task)
    return task


def update_task(
    session: Session, owner_id: str, task_id: str, data: dict, expected_version: int | None = None
) -> Task:
    task = _task(session, owner_id, task_id)
    if task.parent_task_id:
        raise DomainError("TASK_NOT_EDITABLE", "子任务由父任务计划管理，不能单独编辑", 409)
    if task.state not in st.EDITABLE_STATES:
        raise DomainError(
            "TASK_NOT_EDITABLE", "只有草稿状态的任务可以编辑", 409, {"state": task.state}
        )
    _check_version(task, expected_version)

    if "title" in data and data["title"] is not None:
        title = str(data["title"]).strip()
        if not title:
            raise DomainError("VALIDATION_ERROR", "任务标题不能为空", 422)
        task.title = title[:200]
    if data.get("objective") is not None:
        task.objective = str(data["objective"])
    if data.get("instruction") is not None:
        task.instruction = str(data["instruction"])
    if data.get("deliverable") is not None:
        task.deliverable = str(data["deliverable"])
    if data.get("priority") is not None:
        task.priority = _validate_choice(str(data["priority"]), PRIORITIES, "priority")
    if data.get("risk_level") is not None:
        task.risk_level = _validate_choice(str(data["risk_level"]), RISK_LEVELS, "risk_level")
    if data.get("execution_mode") is not None:
        task.execution_mode = _validate_choice(str(data["execution_mode"]), MODES, "execution_mode")
    if data.get("approval_stage") is not None:
        task.approval_stage = _validate_choice(
            str(data["approval_stage"]), APPROVAL_STAGES, "approval_stage"
        )
    if data.get("approval_required") is not None:
        task.approval_required = bool(data["approval_required"])
    if data.get("budget_usd") is not None:
        task.budget_usd = float(data["budget_usd"])
    if data.get("due_at") is not None:
        task.due_at = _parse_due(data["due_at"])
    if data.get("context") is not None:
        task.context = data["context"]
    if data.get("assignee_employee_id"):
        employee = _employee(
            session, owner_id, task.company_id, data["assignee_employee_id"], "执行员工"
        )
        task.assignee_employee_id = employee.id
        if not data.get("department_id"):
            task.department_id = employee.department_id
    if data.get("department_id") is not None:
        _department(session, owner_id, task.company_id, data["department_id"])
        task.department_id = data["department_id"]
    if data.get("reviewer_employee_id") is not None:
        reviewer_id = data["reviewer_employee_id"] or None
        if reviewer_id:
            reviewer = _employee(session, owner_id, task.company_id, reviewer_id, "审核员工")
            if reviewer.id == task.assignee_employee_id:
                raise DomainError("TASK_ASSIGNEE_INVALID", "审核人不能是执行人本人", 422)
            if not employee_can_review(session, reviewer):
                raise DomainError(
                    "APPROVAL_REVIEWER_INVALID", "审核员工不具备 can_review 审查资格", 422
                )
        task.reviewer_employee_id = reviewer_id
    if data.get("max_rework") is not None:
        task.max_rework = max(0, int(data["max_rework"]))

    _touch(task)
    emit(session, task, None, "task.updated", {"fields": sorted(data.keys())})
    session.commit()
    session.refresh(task)
    return task


def get_task(session: Session, owner_id: str, task_id: str) -> Task:
    return _task(session, owner_id, task_id)


def list_tasks(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    state: str | None = None,
    assignee_employee_id: str | None = None,
    department_id: str | None = None,
    parent_task_id: str | None = None,
    roots_only: bool = True,
    q: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[Task], int]:
    _company(session, owner_id, company_id)
    stmt = select(Task).where(Task.owner_id == owner_id, Task.company_id == company_id)
    if roots_only and parent_task_id is None:
        stmt = stmt.where(Task.parent_task_id.is_(None))
    if parent_task_id:
        stmt = stmt.where(Task.parent_task_id == parent_task_id)
    if state:
        stmt = stmt.where(Task.state == state)
    if assignee_employee_id:
        stmt = stmt.where(Task.assignee_employee_id == assignee_employee_id)
    if department_id:
        stmt = stmt.where(Task.department_id == department_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Task.title.like(like) | Task.objective.like(like))
    total = len(session.execute(stmt).scalars().all())
    rows = session.execute(
        stmt.order_by(Task.created_at.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return list(rows), total


def children_of(session: Session, task_id: str) -> list[Task]:
    return list(session.execute(
        select(Task).where(Task.parent_task_id == task_id).order_by(Task.created_at)
    ).scalars().all())


def _delete_child_subtree(session: Session, child: Task) -> None:
    """删除一个未执行的子任务及其全部后代（递归计划的子树）。"""
    for grandchild in children_of(session, child.id):
        _delete_child_subtree(session, grandchild)
    session.delete(child)


def _tree_step_total(
    session: Session,
    node: Task,
    *,
    rewrite_task_id: str | None = None,
    rewrite_steps: int = 0,
) -> int:
    """整棵任务树的总步骤数；被重写的节点按新计划计（其旧后代将被删除，不下钻）。"""
    if node.id == rewrite_task_id:
        return rewrite_steps
    total = len((node.plan or {}).get("steps") or [])
    for child in children_of(session, node.id):
        total += _tree_step_total(
            session, child, rewrite_task_id=rewrite_task_id, rewrite_steps=rewrite_steps,
        )
    return total


def _ancestor_root(session: Session, task: Task) -> Task:
    current = task
    for _ in range(32):
        if not current.parent_task_id:
            return current
        current = session.get(Task, current.parent_task_id) or current
        if not current.parent_task_id:
            return current
    return current


def _tree_step_count(session: Session, task: Task) -> int:
    """任务树当前的总步骤数（含各层子任务的计划步骤）。"""
    total = len((task.plan or {}).get("steps") or [])
    for child in children_of(session, task.id):
        if (child.plan or {}).get("steps"):
            total += _tree_step_count(session, child)
    return total


def _make_step_child(session: Session, owner_id: str, task: Task, step: dict) -> Task:
    employee = session.get(Employee, step["employee_id"])
    return Task(
        id=new_id(), owner_id=owner_id, company_id=task.company_id,
        department_id=employee.department_id if employee else task.department_id,
        parent_task_id=task.id, root_task_id=task.root_task_id or task.id,
        depth=task.depth + 1, title=step["title"] or step["instruction"][:60],
        objective=step["instruction"], instruction=step["instruction"],
        deliverable=step["deliverable"], state="pending", priority=task.priority,
        risk_level=task.risk_level, assignee_employee_id=step["employee_id"],
        reviewer_employee_id=None, execution_mode=task.execution_mode,
        plan={"step_id": step["id"]}, result={}, context={}, version=1,
        created_by=owner_id,
    )


def set_plan(session: Session, owner_id: str, task_id: str, plan: dict) -> Task:
    """设置任务计划。M3-B 起允许**未执行的子任务**（state=pending）设计划形成任务树。"""
    task = _task(session, owner_id, task_id)
    if task.parent_task_id:
        if task.state != "pending":
            raise DomainError(
                "TASK_NOT_EDITABLE", "子任务只有在待调度（pending）状态才能设置计划", 409,
                {"state": task.state},
            )
    elif task.state not in st.EDITABLE_STATES:
        raise DomainError("TASK_NOT_EDITABLE", "只有草稿状态可以设置计划", 409, {"state": task.state})

    # 先取子任务的 step_id 关联标记（父执行器靠它建立子任务映射），再覆盖计划；
    # M3-B 起子任务自己的计划与该标记共存于同一个 plan JSON。
    step_marker = (task.plan or {}).get("step_id") if task.parent_task_id else None
    task.plan = plan or {}
    normalized = normalize_plan(session, owner_id, task)
    if step_marker:
        normalized = {"step_id": step_marker, **normalized}
    task.plan = normalized

    # M3-B：整棵任务树的总步骤上限（后端强制，防递归失控扩张）。
    # 被重写的任务按新计划计；其旧后代将被删除，不计入。
    root = _ancestor_root(session, task)
    total = _tree_step_total(
        session, root, rewrite_task_id=task.id,
        rewrite_steps=len(normalized["steps"]),
    )
    cap = int(task.max_total_steps or 50)
    if total > cap:
        raise DomainError(
            "TASK_STEP_BUDGET_EXCEEDED",
            f"任务树总步骤数 {total} 超过上限 {cap}", 409,
            {"total_steps": total, "max_total_steps": cap},
        )

    existing = children_of(session, task.id)
    for child in existing:
        has_run = session.execute(
            select(func.count()).select_from(TaskRun).where(TaskRun.task_id == child.id)
        ).scalar_one()
        if has_run:
            raise DomainError(
                "TASK_NOT_EDITABLE", "已有子任务执行过，不能替换计划；请新建任务", 409
            )
    for child in existing:
        _delete_child_subtree(session, child)
    session.flush()

    for step in normalized["steps"]:
        session.add(_make_step_child(session, owner_id, task, step))

    _record_plan_revision(session, owner_id, task, reason="set_plan")
    _touch(task)
    emit(session, task, None, "task.plan.updated", {
        "steps": [s["id"] for s in normalized["steps"]],
        "revision": task.plan_revision,
        "auto_assigned": [s["id"] for s in normalized["steps"] if s.get("auto_assigned")],
    })
    session.commit()
    session.refresh(task)
    return task


def _plan_descendants(session: Session, task: Task) -> list[Task]:
    """任务树全部后代（含多层）。"""
    result: list[Task] = []
    for child in children_of(session, task.id):
        result.append(child)
        result.extend(_plan_descendants(session, child))
    return result


def _record_plan_revision(
    session: Session, owner_id: str, task: Task, *,
    reason: str = "", failed_step_id: str | None = None, bump: bool = False,
) -> None:
    """写一条计划版本快照；replan 时版本号 +1。"""
    from packages.persistence.models import TaskPlanRevision

    if bump:
        task.plan_revision = (task.plan_revision or 1) + 1
    session.add(TaskPlanRevision(
        id=new_id(), owner_id=owner_id, task_id=task.id,
        revision=task.plan_revision or 1, plan=task.plan or {},
        reason=reason[:500], failed_step_id=failed_step_id, created_by=owner_id,
    ))


def replan(
    session: Session,
    owner_id: str,
    task_id: str,
    *,
    steps: list[dict],
    reason: str = "",
    failed_step_id: str | None = None,
) -> dict:
    """M3-B 重规划：只重置失败步骤及其下游，上游产出保留；超 3 次拒绝。"""
    from .approvals import apply_rewind

    task = _task(session, owner_id, task_id)
    if task.parent_task_id:
        raise DomainError("TASK_NOT_EDITABLE", "子任务由父任务计划管理，请对根任务重规划", 409)
    if task.state not in ("failed", "rework_required"):
        raise DomainError(
            "TASK_NOT_EDITABLE", "只有失败/待返工状态可以重规划", 409, {"state": task.state},
        )
    if task.replan_count >= 3:
        raise DomainError(
            "TASK_REPLAN_LIMIT", "已达到最大重规划次数 3，请人工介入", 409,
            {"replan_count": task.replan_count},
        )
    if not isinstance(steps, list) or not steps:
        raise DomainError("VALIDATION_ERROR", "steps 必须是非空数组", 422)

    old_plan = task.plan or {}
    new_plan = {
        "version": (old_plan.get("version") or 1) + 1,
        "steps": steps,
        "max_parallel": old_plan.get("max_parallel", 4),
    }
    task.plan = new_plan
    normalized = normalize_plan(session, owner_id, task)
    task.plan = normalized

    known = {step["id"] for step in normalized["steps"]}
    if failed_step_id and failed_step_id not in known:
        raise DomainError(
            "VALIDATION_ERROR", f"failed_step_id 不在新计划中：{failed_step_id}", 422,
            {"steps": sorted(known)},
        )

    # 失败步骤及下游从检查点剔除（上游产出保留）；随后按新计划重建子任务
    rewind = apply_rewind(session, task, failed_step_id)

    for child in children_of(session, task.id):
        child_step_id = (child.plan or {}).get("step_id")
        if child_step_id in known:
            continue
        has_run = session.execute(
            select(func.count()).select_from(TaskRun).where(TaskRun.task_id == child.id)
        ).scalar_one()
        if has_run:
            child.state = "cancelled"
            child.ended_at = child.ended_at or datetime.now(timezone.utc)
        else:
            _delete_child_subtree(session, child)
    session.flush()
    for step in normalized["steps"]:
        # 按 step_id 标记复用既有子任务（子任务可能带有自己的递归计划，不能按 JSON 全等匹配）
        existing = next(
            (c for c in children_of(session, task.id)
             if (c.plan or {}).get("step_id") == step["id"]),
            None,
        )
        if existing is not None:
            continue
        session.add(_make_step_child(session, owner_id, task, step))

    task.replan_count = (task.replan_count or 0) + 1
    _record_plan_revision(
        session, owner_id, task, reason=reason or "replan",
        failed_step_id=failed_step_id, bump=True,
    )
    _touch(task)
    emit(session, task, None, "task.replanned", {
        "revision": task.plan_revision, "replan_count": task.replan_count,
        "failed_step_id": failed_step_id, "rewind": rewind,
        "steps": [s["id"] for s in normalized["steps"]],
    })
    session.commit()
    session.refresh(task)
    return {
        "task_id": task.id, "state": task.state,
        "plan_revision": task.plan_revision, "replan_count": task.replan_count,
        "rewind": rewind,
    }


def plan_revisions_of(session: Session, owner_id: str, task_id: str) -> list[dict]:
    from packages.persistence.models import TaskPlanRevision

    task = _task(session, owner_id, task_id)
    rows = session.execute(
        select(TaskPlanRevision).where(TaskPlanRevision.task_id == task.id)
        .order_by(TaskPlanRevision.revision)
    ).scalars().all()
    return [{
        "id": row.id, "revision": row.revision, "plan": row.plan,
        "reason": row.reason, "failed_step_id": row.failed_step_id,
        "created_by": row.created_by, "created_at": iso_utc(row.created_at),
        "steps": [s.get("id") for s in (row.plan or {}).get("steps", [])],
    } for row in rows]


def resolve_mode(task: Task) -> str:
    if task.execution_mode in ("real", "mock"):
        return task.execution_mode
    env_mode = os.environ.get("AGENTOS_MODEL_MODE", "").strip().lower()
    return "mock" if env_mode == "mock" else "real"


def _active_run(session: Session, task_id: str) -> TaskRun | None:
    return session.execute(
        select(TaskRun).where(TaskRun.task_id == task_id, TaskRun.state.in_(MAX_ACTIVE_RUN))
    ).scalars().first()


def _latest_checkpoint(session: Session, task_id: str) -> tuple[dict, str | None]:
    last = session.execute(
        select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.run_no.desc())
    ).scalars().first()
    if last is None:
        return {}, None
    return (last.checkpoint or {}), last.id


def enqueue_run(
    session: Session,
    owner_id: str,
    task_id: str,
    *,
    trigger: str = "manual",
    approved_by: str | None = None,
) -> TaskRun:
    task = _task(session, owner_id, task_id)
    if task.parent_task_id and trigger != "approval":
        # M3-B：子任务由父任务计划调度；唯一例外是工具审批通过后的恢复执行
        raise DomainError("TASK_NOT_EDITABLE", "子任务由父任务计划调度，不能单独运行", 409)
    if _active_run(session, task.id) is not None:
        raise DomainError("TASK_ACTIVE_RUN_EXISTS", "该任务已有排队或运行中的执行", 409)
    allowed_states = set(st.RUNNABLE_STATES)
    if approved_by or trigger in ("resume", "approval"):
        allowed_states.add("awaiting_approval")
    if task.state not in allowed_states:
        raise DomainError(
            "TASK_ILLEGAL_TRANSITION", f"任务当前状态 {task.state} 不能开始执行", 409,
            {"from": task.state, "to": "queued", "allowed": st.allowed_targets(task.state)},
        )

    st.ensure_transition(task.state, "queued")
    checkpoint, previous_run_id = _latest_checkpoint(session, task.id)
    if task.state == "draft":
        checkpoint, previous_run_id = {}, None

    run_no = session.execute(
        select(func.max(TaskRun.run_no)).where(TaskRun.task_id == task.id)
    ).scalar_one() or 0
    run = TaskRun(
        id=new_id(), owner_id=owner_id, task_id=task.id, run_no=int(run_no) + 1,
        trigger=trigger, state="queued", mode=resolve_mode(task),
        checkpoint=checkpoint, resumed_from_run_id=previous_run_id,
        approved_by=approved_by,
    )
    session.add(run)
    task.state = "queued"
    task.cancel_requested = False
    task.pause_requested = False
    _touch(task)
    emit(session, task, run.id, "task.queued", {
        "run_no": run.run_no, "trigger": trigger, "mode": run.mode,
        "resumed_from_run_id": previous_run_id,
    })
    session.commit()
    session.refresh(run)
    return run


def pause_task(session: Session, owner_id: str, task_id: str) -> dict:
    task = _task(session, owner_id, task_id)
    if task.state == "queued":
        run = _active_run(session, task.id)
        st.ensure_transition(task.state, "paused")
        if run is not None:
            run.state = "paused"
            run.ended_at = datetime.now(timezone.utc)
        task.state = "paused"
        _touch(task)
        emit(session, task, run.id if run else None, "run.paused", {"before_start": True})
        session.commit()
        return {"state": task.state, "pending": False}
    if task.state == "running":
        task.pause_requested = True
        emit(session, task, None, "task.pause_requested", {})
        session.commit()
        return {"state": task.state, "pending": True}
    raise DomainError(
        "TASK_ILLEGAL_TRANSITION", f"任务当前状态 {task.state} 不能暂停", 409,
        {"from": task.state, "allowed": ["queued", "running"]},
    )


def resume_task(session: Session, owner_id: str, task_id: str) -> TaskRun:
    task = _task(session, owner_id, task_id)
    if task.state == "awaiting_approval":
        # M3-B：嵌套子计划的工具审批在子任务上决策后，父任务从这里恢复推进；
        # 本任务自己还有 pending 审批时不允许绕过审批恢复
        if pending_approvals(session, task.id):
            raise DomainError(
                "APPROVAL_PENDING", "任务还有待处理的审批，请先批准或驳回", 409,
                {"pending": len(pending_approvals(session, task.id))},
            )
        run = enqueue_run(session, owner_id, task_id, trigger="resume")
        emit(session, task, run.id, "task.resumed", {"from_state": "awaiting_approval"})
        session.commit()
        return run
    if task.state not in st.RESUMABLE_STATES:
        raise DomainError(
            "TASK_ILLEGAL_TRANSITION", f"任务当前状态 {task.state} 不能恢复", 409,
            {"from": task.state, "allowed": sorted(st.RESUMABLE_STATES | {"awaiting_approval"})},
        )
    run = enqueue_run(session, owner_id, task_id, trigger="resume")
    emit(session, task, run.id, "task.resumed", {"from_state": "paused"})
    session.commit()
    return run


def retry_task(session: Session, owner_id: str, task_id: str) -> TaskRun:
    task = _task(session, owner_id, task_id)
    if task.state not in st.RETRYABLE_STATES:
        raise DomainError(
            "TASK_ILLEGAL_TRANSITION", f"任务当前状态 {task.state} 不能重试", 409,
            {"from": task.state, "allowed": sorted(st.RETRYABLE_STATES)},
        )
    if task.rework_count >= task.max_rework and task.state == "rework_required":
        raise DomainError(
            "TASK_REWORK_LIMIT", f"已达到最大返工次数 {task.max_rework}", 409,
            {"rework_count": task.rework_count, "max_rework": task.max_rework},
        )
    run = enqueue_run(session, owner_id, task_id, trigger="retry")
    emit(session, task, run.id, "task.retried", {"run_no": run.run_no})
    session.commit()
    return run


def _descendants(session: Session, task: Task) -> list[Task]:
    root_id = task.root_task_id or task.id
    return list(session.execute(
        select(Task).where(Task.root_task_id == root_id, Task.id != root_id)
    ).scalars().all())


def cancel_task(session: Session, owner_id: str, task_id: str) -> dict:
    task = _task(session, owner_id, task_id)
    if task.state in st.TERMINAL_STATES:
        raise DomainError(
            "TASK_ILLEGAL_TRANSITION", f"任务已处于终态 {task.state}", 409,
            {"from": task.state, "allowed": []},
        )
    pending = task.state == "running"
    if pending:
        task.cancel_requested = True
        emit(session, task, None, "task.cancel_requested", {})
    else:
        st.ensure_transition(task.state, "cancelled")
        run = _active_run(session, task.id)
        if run is not None:
            run.state = "cancelled"
            run.ended_at = datetime.now(timezone.utc)
        task.state = "cancelled"
        emit(session, task, run.id if run else None, "task.cancelled", {"immediate": True})
    for approval in session.execute(
        select(TaskApproval).where(TaskApproval.task_id == task.id, TaskApproval.status == "pending")
    ).scalars().all():
        approval.status = "cancelled"
    for child in _descendants(session, task):
        if child.state in st.TERMINAL_STATES:
            continue
        child.state = "cancelled"
        child.ended_at = datetime.now(timezone.utc)
    task.ended_at = datetime.now(timezone.utc)
    _touch(task)
    session.commit()
    return {"state": task.state, "pending": pending}


def pending_approvals(session: Session, task_id: str) -> list[TaskApproval]:
    return list(session.execute(
        select(TaskApproval)
        .where(TaskApproval.task_id == task_id, TaskApproval.status == "pending")
        .order_by(TaskApproval.created_at)
    ).scalars().all())
