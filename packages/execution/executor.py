"""执行器（M2-B/C）：单次 run 的完整执行。

关键约束：
- 每个步骤完成即提交（AgentRun + Usage + 子任务状态 + checkpoint），崩溃可续；
- 同一步骤不会因重启重复执行（checkpoint.completed_steps 判定）；
- 并行波次真实并发调用模型，DB 写段串行化（SQLite 单写者）；
- 取消/暂停在步骤边界生效；正在进行的模型调用不可中断（Adapter 能力如实声明）。
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.agent_core.adapter import collect_final
from packages.memory.service import retrieve_for_step
from packages.persistence import get_session
from packages.persistence.models import (
    AgentHandoff,
    AgentRun,
    Employee,
    EmployeeWorkspaceGrant,
    ModelConnection,
    Task,
    TaskApproval,
    TaskEvent,
    TaskRun,
    UsageRecord,
    Workspace,
)
from packages.shared.errors import DomainError
from packages.shared.types import AgentTask, new_id
from packages.tasks import state as st
from packages.tasks.approvals import create_approval
from packages.tasks.plan import topological_waves
from packages.tools.fs import load_image_data_uri
from packages.tools.paths import PathDenied, safe_resolve
from packages.tools.policy import global_tools_enabled
from packages.tools.workspaces import resolve_grant, workspace_brief

from . import budget
from .adapter_factory import build_adapter
from .guard import check_execution, steps_of
from .prompting import build_system_prompt
from .tool_loop import (
    TOOL_DENIED_LIMIT,
    RunSuspended,
    authorized_tools,
    build_tool_context,
    run_tool_loop,
)

logger = logging.getLogger("agentos.execution")

# M3-E：这些错误不视为任务失败，而是"保护性暂停"——保留检查点，人工处理后可续跑
PAUSE_CODES = {budget.BUDGET_EXCEEDED, TOOL_DENIED_LIMIT}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _emit(session: Session, task: Task, run_id: str | None, type_: str, payload: dict | None = None) -> None:
    session.add(TaskEvent(task_id=task.id, task_run_id=run_id, type=type_, payload=payload or {}))


def _child_map(session: Session, task: Task) -> dict[str, Task]:
    rows = session.execute(select(Task).where(Task.parent_task_id == task.id)).scalars().all()
    return {(row.plan or {}).get("step_id"): row for row in rows if (row.plan or {}).get("step_id")}


def _has_human_decision(session: Session, task: Task) -> bool:
    return session.execute(
        select(TaskApproval).where(
            TaskApproval.task_id == task.id,
            TaskApproval.status.in_(("approved", "rejected", "changes_requested")),
        )
    ).first() is not None


def _previous_agent_run(checkpoint: dict, step: dict) -> str | None:
    outputs = checkpoint.get("outputs") or {}
    for dep in step.get("depends_on") or []:
        run_id = (outputs.get(dep) or {}).get("agent_run_id")
        if run_id:
            return run_id
    return None


def _context_text(checkpoint: dict, step: dict, limit: int = 6000) -> str:
    outputs = checkpoint.get("outputs") or {}
    blocks: list[str] = []
    for dep in step.get("depends_on") or []:
        item = outputs.get(dep) or {}
        if item.get("content"):
            blocks.append(f"【上游步骤 {dep} 产出】\n{item['content']}")
    return "\n\n".join(blocks)[:limit]


def _task_cost(session: Session, task_id: str) -> float:
    total = session.execute(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0))
        .join(AgentRun, AgentRun.id == UsageRecord.agent_run_id)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .where(TaskRun.task_id == task_id)
    ).scalar_one()
    return round(float(total or 0.0), 8)


def _step_timeout(task: Task, step: dict) -> float:
    """步骤超时上限：步骤级 > 任务 context > 默认 300s。"""
    for value in (step.get("timeout_s"), (task.context or {}).get("step_timeout_s")):
        if value:
            try:
                return max(0.05, float(value))
            except (TypeError, ValueError):
                continue
    return 300.0


async def execute_run(run_id: str) -> str:
    """执行一条已认领的 run；返回终态字符串（便于 runner/测试断言）。"""
    session = get_session()
    run: TaskRun | None = None
    task: Task | None = None
    try:
        run = session.get(TaskRun, run_id)
        if run is None:
            return "missing"
        if run.state != "running":
            return run.state
        task = session.get(Task, run.task_id)
        if task is None:
            return "missing"

        task.state = "running"
        task.started_at = task.started_at or _now()
        task.version = (task.version or 1) + 1
        run.heartbeat_at = _now()
        _emit(session, task, run.id, "run.started", {
            "run_no": run.run_no, "mode": run.mode, "trigger": run.trigger,
        })
        session.commit()

        return await _execute(session, task, run)
    except DomainError as exc:
        session.rollback()
        if exc.code in PAUSE_CODES and run is not None and task is not None:
            return _pause_for_guard(session, task, run, exc)
        _fail(session, run, task, exc.code, exc.message)
        return "failed"
    except Exception as exc:  # noqa: BLE001 - 执行边界必须兜底，不能卡在 running
        session.rollback()
        logger.exception("run %s 执行异常", run_id)
        _fail(session, run, task, "EXECUTION_ERROR", str(exc)[:300])
        return "failed"
    finally:
        session.close()


async def _execute(session: Session, task: Task, run: TaskRun) -> str:
    steps = steps_of(task)
    checkpoint = dict(run.checkpoint or {})
    checkpoint.setdefault("completed_steps", [])
    checkpoint.setdefault("outputs", {})
    completed = set(checkpoint["completed_steps"])

    # 审批闸门（入口）：仅 before_run 在开始前拦；已有人工决策的返工/重试不重复拦。
    # after_run 的闸门在步骤全部完成后单独处理，每次交付都要签收。
    needs_gate = (
        task.approval_required
        and task.approval_stage == "before_run"
        and not run.approved_by
        and not _has_human_decision(session, task)
    )
    if needs_gate:
        approval = create_approval(session, task, run, gate="before_run", requested_by=task.created_by)
        run.state = "awaiting_approval"
        task.state = "awaiting_approval"
        task.version = (task.version or 1) + 1
        _emit(session, task, run.id, "approval.requested", {
            "approval_id": approval.id, "gate": "before_run",
        })
        session.commit()
        return "awaiting_approval"

    children = _child_map(session, task)
    waves = topological_waves(steps)
    write_lock = asyncio.Lock()

    for wave in waves:
        # 结束上一波遗留的只读事务：SQLite WAL 下的读事务是快照，
        # 不结束它就会看不到其他会话刚提交的 cancel_requested/pause_requested。
        session.commit()
        session.expire_all()
        task = session.get(Task, task.id)
        run = session.get(TaskRun, run.id)
        checkpoint = dict(run.checkpoint or {})
        completed = set(checkpoint.get("completed_steps", []))
        if task.cancel_requested:
            return _cancel(session, task, run)
        if task.pause_requested:
            return _pause(session, task, run, checkpoint)

        ready = [step for step in wave if step["id"] not in completed]
        if not ready:
            continue

        coros = [
            _run_step(
                owner_id=task.owner_id,
                task_id=task.id,
                run_id=run.id,
                step=step,
                mode=run.mode,
                lock=write_lock,
                child_id=(children.get(step["id"]).id if children.get(step["id"]) else None),
            )
            for step in ready
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

        if any(isinstance(item, RunSuspended) for item in results):
            session.expire_all()
            run = session.get(TaskRun, run.id)
            task = session.get(Task, task.id)
            # 顶层工具审批挂起由 _suspend_for_tool_approval 落状态；
            # M3-B 嵌套子计划内挂起会沿异常上传到这里，由父 run/task 统一转 awaiting
            if run.state != "awaiting_approval":
                run.state = "awaiting_approval"
                run.ended_at = _now()
            if task.state != "awaiting_approval":
                task.state = "awaiting_approval"
                task.version = (task.version or 1) + 1
            session.commit()
            return "awaiting_approval"

        failures = [item for item in results if isinstance(item, BaseException)]
        session.expire_all()
        run = session.get(TaskRun, run.id)
        task = session.get(Task, task.id)
        checkpoint = dict(run.checkpoint or {})
        completed = set(checkpoint.get("completed_steps", []))

        if failures:
            exc = failures[0]
            if isinstance(exc, DomainError) and exc.code in PAUSE_CODES:
                return _pause_for_guard(session, task, run, exc)
            if isinstance(exc, DomainError):
                raise exc
            raise DomainError(
                "EXECUTION_FAILED", f"步骤执行失败：{str(exc)[:200]}", 502,
                {"steps": [step["id"] for step in ready]},
            ) from exc

        run.heartbeat_at = _now()
        session.commit()

    if task.cancel_requested:
        return _cancel(session, task, run)
    if task.pause_requested:
        return _pause(session, task, run, checkpoint)

    checkpoint = dict(run.checkpoint or {})
    outputs = checkpoint.get("outputs") or {}
    last = ""
    for step in reversed(steps):
        item = outputs.get(step["id"]) or {}
        if item.get("content"):
            last = item["content"]
            break
    cost = _task_cost(session, task.id)

    if task.approval_required and task.approval_stage == "after_run" and not run.approved_by:
        approval = create_approval(
            session, task, run, gate="after_run", requested_by=task.created_by,
            context={"steps": [step["id"] for step in steps], "summary": last[:1000]},
        )
        run.state = "awaiting_approval"
        task.state = "awaiting_approval"
        task.result = {
            "summary": last[:4000],
            "steps": [
                {
                    "step_id": step["id"],
                    "employee_id": step.get("employee_id"),
                    "agent_run_id": (outputs.get(step["id"]) or {}).get("agent_run_id"),
                }
                for step in steps
            ],
            "mode": run.mode,
            "cost_usd": cost,
            "pending_approval": approval.id,
            "deliverables": _collect_deliverables(session, task, steps),
        }
        _emit(session, task, run.id, "approval.requested", {
            "approval_id": approval.id, "gate": "after_run",
        })
        session.commit()
        return "awaiting_approval"

    st.ensure_transition(task.state, "succeeded")
    task.state = "succeeded"
    task.ended_at = _now()
    task.result = {
        "summary": last[:4000],
        "steps": [
            {
                "step_id": step["id"],
                "title": step.get("title") or "",
                "employee_id": step.get("employee_id"),
                "agent_run_id": (outputs.get(step["id"]) or {}).get("agent_run_id"),
                "chars": len((outputs.get(step["id"]) or {}).get("content") or ""),
            }
            for step in steps
        ],
        "mode": run.mode,
        "cost_usd": cost,
        "deliverables": _collect_deliverables(session, task, steps),
    }
    task.version = (task.version or 1) + 1
    run.state = "succeeded"
    run.ended_at = _now()
    run.checkpoint = checkpoint
    _emit(session, task, run.id, "task.succeeded", {
        "steps": len(steps), "cost_usd": cost, "mode": run.mode,
    })
    session.commit()

    # M3-B：子任务的审批恢复 run 成功后，父任务若仍在等待，自动续跑（无需人工再点一次恢复）。
    # 子 run 失败时不自动续跑——避免对已知失败步骤立即重试烧钱，由人工决定。
    if task.parent_task_id and run.trigger in ("approval", "auto_resume"):
        # approval 与 auto_resume 两种独立子 run 成功都会级联向上恢复（祖父→父→子逐层）
        _auto_resume_parent_if_ready(session, task)
    return "succeeded"


def _auto_resume_parent_if_ready(session: Session, child: Task) -> str | None:
    """子任务审批恢复完成后，自动恢复其处于 awaiting_approval 的父任务。

    前置检查：父任务无待审批、无活跃 run、未被请求暂停/取消。
    """
    parent = session.get(Task, child.parent_task_id)
    if parent is None or parent.state != "awaiting_approval":
        return None
    if parent.pause_requested or parent.cancel_requested:
        return None
    if session.execute(
        select(TaskApproval).where(
            TaskApproval.task_id == parent.id, TaskApproval.status == "pending"
        )
    ).scalars().first() is not None:
        return None
    if session.execute(
        select(TaskRun).where(
            TaskRun.task_id == parent.id,
            # awaiting_approval 的父 run 正是要被恢复的状态，不算阻塞；
            # 只有排队/运行中的 run 才可能与新 run 冲突
            TaskRun.state.in_(("queued", "running")),
        )
    ).scalars().first() is not None:
        return None
    from packages.tasks.service import enqueue_run, pending_approvals

    assert not pending_approvals(session, parent.id)
    run = enqueue_run(session, parent.owner_id, parent.id, trigger="auto_resume")
    _emit(session, parent, run.id, "task.auto_resumed", {
        "reason": "子任务审批恢复完成", "child_task_id": child.id, "child_run_id": run.id,
    })
    session.commit()
    return run.id


def _fail(session: Session, run: TaskRun | None, task: Task | None, code: str, message: str) -> None:
    if run is None:
        return
    try:
        now = _now()
        run.state = "failed"
        run.error = f"{code}: {message}"[:500]
        run.ended_at = now
        if task is not None:
            task.state = "failed"
            task.ended_at = now
            task.result = {**(task.result or {}), "error": {"code": code, "message": message[:500]}}
            task.version = (task.version or 1) + 1
            _emit(session, task, run.id, "run.failed", {"code": code, "message": message[:500]})
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("记录失败状态时出错")


def _cancel(session: Session, task: Task, run: TaskRun) -> str:
    run.state = "cancelled"
    run.ended_at = _now()
    task.state = "cancelled"
    task.ended_at = _now()
    task.cancel_requested = False
    task.version = (task.version or 1) + 1
    _emit(session, task, run.id, "task.cancelled", {"by_signal": True})
    session.commit()
    return "cancelled"


def _pause(session: Session, task: Task, run: TaskRun, checkpoint: dict) -> str:
    run.state = "paused"
    run.ended_at = _now()
    run.checkpoint = checkpoint
    task.state = "paused"
    task.pause_requested = False
    task.version = (task.version or 1) + 1
    _emit(session, task, run.id, "run.paused", {
        "completed_steps": checkpoint.get("completed_steps", []),
    })
    session.commit()
    return "paused"


def _pause_for_guard(session: Session, task: Task, run: TaskRun, exc: DomainError) -> str:
    """M3-E 保护性暂停：预算耗尽 / 连续拒绝。保留检查点与已完成步骤，人工处理后可续跑。"""
    st.ensure_transition(task.state, "paused")
    now = _now()
    session.expire(run, ["checkpoint"])
    checkpoint = dict(run.checkpoint or {})
    run.state = "paused"
    run.ended_at = now
    run.error = f"{exc.code}: {exc.message}"[:500]
    run.checkpoint = checkpoint
    task.state = "paused"
    task.pause_requested = False
    task.cancel_requested = False
    task.result = {
        **(task.result or {}),
        "error": {"code": exc.code, "message": exc.message[:500]},
    }
    task.version = (task.version or 1) + 1
    event_type = (
        "task.budget_exceeded" if exc.code == budget.BUDGET_EXCEEDED else "task.tool_denied_limit"
    )
    _emit(session, task, run.id, event_type, {
        "code": exc.code, "message": exc.message[:500], **(exc.detail or {}),
    })
    _emit(session, task, run.id, "run.paused", {
        "reason": exc.code,
        "completed_steps": checkpoint.get("completed_steps", []),
    })
    session.commit()
    logger.warning("任务 %s 因 %s 暂停：%s", task.id, exc.code, exc.message)
    return "paused"


def _suspend_for_tool_approval(
    session: Session, task: Task, run: TaskRun, checkpoint: dict
) -> None:
    """工具调用待审批：保存 messages/待执行调用，任务与 run 同步挂起。"""
    fresh_run = session.get(TaskRun, run.id)
    fresh_task = session.get(Task, task.id)
    if fresh_run is None or fresh_task is None:
        return
    merged = dict(fresh_run.checkpoint or {})
    tool_state = checkpoint.get("tool_state")
    if tool_state:
        merged["tool_state"] = tool_state
    fresh_run.checkpoint = merged
    fresh_run.state = "awaiting_approval"
    fresh_run.ended_at = _now()
    fresh_task.state = "awaiting_approval"
    fresh_task.version = (fresh_task.version or 1) + 1
    _emit(session, fresh_task, fresh_run.id, "run.awaiting_approval", {
        "approval_id": (tool_state or {}).get("approval_id"),
        "gate": "tool_call",
        "step_id": (tool_state or {}).get("step_id"),
    })
    session.commit()


async def _run_step(
    *,
    owner_id: str,
    task_id: str,
    run_id: str,
    step: dict,
    mode: str,
    lock: asyncio.Lock,
    child_id: str | None,
) -> dict:
    """执行单个步骤（M3-B 调度器）：子任务有计划 → 递归委托；否则单步模型/工具执行。"""
    session = get_session()
    try:
        task = session.get(Task, task_id)
        run = session.get(TaskRun, run_id)
        if task is None or run is None:
            raise DomainError("NOT_FOUND", "任务或执行不存在", 404)
        child = session.get(Task, child_id) if child_id else None
        if child is not None and (child.plan or {}).get("steps"):
            return await _run_nested_step(
                session, owner_id=owner_id, task=task, run=run,
                child=child, step=step, mode=mode, lock=lock,
            )
        return await _run_single_step(
            session, owner_id=owner_id, task_id=task_id, run_id=run_id,
            step=step, mode=mode, lock=lock, child_id=child_id,
        )
    finally:
        session.close()


def _transition_child_to_running(session: Session, child: Task) -> None:
    """子任务进入 running（走状态机合法迁移：pending 直达，paused/failed 经 queued）。"""
    if child.state == "running":
        return
    if child.state == "pending":
        st.ensure_transition("pending", "running")
        child.state = "running"
        return
    st.ensure_transition(child.state, "queued")
    child.state = "queued"
    st.ensure_transition("queued", "running")
    child.state = "running"


def _enqueue_nested_run(session: Session, owner_id: str, child: Task, mode: str) -> TaskRun:
    """为子任务创建 nested run（trigger=nested）；检查点继承自其最近一次 run。"""
    active = session.execute(
        select(TaskRun).where(
            TaskRun.task_id == child.id,
            TaskRun.state.in_(("queued", "running", "awaiting_approval")),
        )
    ).scalars().first()
    if active is not None:
        # 子任务还有活跃执行（典型：工具审批待人工处理），父步骤暂时无法推进
        raise RunSuspended()

    last = session.execute(
        select(TaskRun).where(TaskRun.task_id == child.id).order_by(TaskRun.run_no.desc())
    ).scalars().first()
    checkpoint = (last.checkpoint or {}) if last is not None else {}
    previous_run_id = last.id if last is not None else None
    run_no = session.execute(
        select(func.max(TaskRun.run_no)).where(TaskRun.task_id == child.id)
    ).scalar_one() or 0
    nested_run = TaskRun(
        id=new_id(), owner_id=owner_id, task_id=child.id, run_no=int(run_no) + 1,
        trigger="nested", state="running", mode=mode,
        checkpoint=checkpoint, resumed_from_run_id=previous_run_id,
    )
    session.add(nested_run)
    child.started_at = child.started_at or _now()
    _transition_child_to_running(session, child)
    _emit(session, child, nested_run.id, "run.started", {
        "run_no": nested_run.run_no, "trigger": "nested", "mode": mode,
    })
    session.commit()
    return nested_run


def _nested_interrupt(session: Session, child: Task, nested_run: TaskRun, state: str) -> None:
    """父任务被取消/暂停时，同步收尾 nested run 与子任务状态。"""
    nested_run.state = state
    nested_run.ended_at = _now()
    if child.state not in st.TERMINAL_STATES:
        child.state = state
        if state == "cancelled":
            child.ended_at = _now()
    session.commit()


async def _run_nested_step(
    session: Session,
    *,
    owner_id: str,
    task: Task,
    run: TaskRun,
    child: Task,
    step: dict,
    mode: str,
    lock: asyncio.Lock,
) -> dict:
    """递归执行子任务的计划（M3-B）。

    - nested run 驱动子任务自己的波次；检查点写在子 run 上，支持断点续跑；
    - 祖先链预算/工具上限与根任务共享（budget 树聚合），子任务无法绕过；
    - 子计划内的工具审批会沿 RunSuspended 向上传导，父任务同步挂起。
    """
    # 预扣在每层子步骤的单步入口各自进行（此处无需预估——执行模型由步骤员工决定）
    budget.check(session, child)
    steps = steps_of(child)

    # 子任务已完成（重规划/恢复后的重入）：直接聚合既有产出，不再开新 run
    session.expire_all()
    child = session.get(Task, child.id)
    last = session.execute(
        select(TaskRun).where(TaskRun.task_id == child.id).order_by(TaskRun.run_no.desc())
    ).scalars().first()
    if (
        child.state == "succeeded"
        and last is not None
        and {s["id"] for s in steps} <= set((last.checkpoint or {}).get("completed_steps", []))
    ):
        checkpoint = dict(last.checkpoint or {})
        outputs = checkpoint.get("outputs") or {}
        content = ""
        for nested_step in reversed(steps):
            item = outputs.get(nested_step["id"]) or {}
            if item.get("content"):
                content = item["content"]
                break
        last_agent_run_id = checkpoint.get("last_agent_run_id")
        async with lock:
            session.expire_all()
            fresh_run = session.get(TaskRun, run.id)
            parent_checkpoint = dict(fresh_run.checkpoint or {})
            parent_checkpoint.setdefault("completed_steps", [])
            parent_checkpoint.setdefault("outputs", {})
            if step["id"] not in parent_checkpoint["completed_steps"]:
                parent_checkpoint["completed_steps"].append(step["id"])
            parent_checkpoint["outputs"][step["id"]] = {
                "agent_run_id": last_agent_run_id,
                "employee_id": child.assignee_employee_id,
                "content": content[:8000],
                "nested_run_id": last.id,
            }
            parent_checkpoint["last_agent_run_id"] = last_agent_run_id
            fresh_run.checkpoint = parent_checkpoint
            session.commit()
        return {"step_id": step["id"], "agent_run_id": last_agent_run_id, "content": content}

    nested_run = _enqueue_nested_run(session, owner_id, child, mode)
    try:
        waves = topological_waves(steps)
        child_map = _child_map(session, child)
        last_agent_run_id = None
        for wave in waves:
            # 波次边界：结束读事务、重读外部请求（与父层同语义）
            session.commit()
            session.expire_all()
            task = session.get(Task, task.id)
            child = session.get(Task, child.id)
            nested_run = session.get(TaskRun, nested_run.id)
            if task.cancel_requested or task.pause_requested:
                state = "cancelled" if task.cancel_requested else "paused"
                _nested_interrupt(session, child, nested_run, state)
                return {"step_id": step["id"], "interrupted": True}

            completed_ids = set((nested_run.checkpoint or {}).get("completed_steps", []))
            ready = [s for s in wave if s["id"] not in completed_ids]
            if not ready:
                continue
            coros = [
                _run_step(
                    owner_id=owner_id,
                    task_id=child.id,
                    run_id=nested_run.id,
                    step=gs,
                    mode=mode,
                    lock=lock,
                    child_id=(child_map.get(gs["id"]).id if child_map.get(gs["id"]) else None),
                )
                for gs in ready
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)

            if any(isinstance(item, RunSuspended) for item in results):
                session.expire_all()
                nested_run = session.get(TaskRun, nested_run.id)
                child = session.get(Task, child.id)
                if nested_run.state != "awaiting_approval":
                    nested_run.state = "awaiting_approval"
                    nested_run.ended_at = _now()
                if child.state != "awaiting_approval":
                    child.state = "awaiting_approval"
                session.commit()
                raise RunSuspended()

            failures = [item for item in results if isinstance(item, BaseException)]
            if failures:
                raise failures[0]

            session.expire_all()
            nested_run = session.get(TaskRun, nested_run.id)
            last_agent_run_id = (nested_run.checkpoint or {}).get("last_agent_run_id") or last_agent_run_id

        # 子计划全部完成：nested run 成功、子任务成功，聚合成父步骤结果
        session.expire_all()
        nested_run = session.get(TaskRun, nested_run.id)
        checkpoint = dict(nested_run.checkpoint or {})
        outputs = checkpoint.get("outputs") or {}
        content = ""
        for nested_step in reversed(steps):
            item = outputs.get(nested_step["id"]) or {}
            if item.get("content"):
                content = item["content"]
                break
        last_agent_run_id = checkpoint.get("last_agent_run_id") or last_agent_run_id
        nested_run.state = "succeeded"
        nested_run.ended_at = _now()
        child = session.get(Task, child.id)
        child.state = "succeeded"
        child.ended_at = _now()
        child.result = {"content": content[:4000], "agent_run_id": last_agent_run_id}
        session.commit()

        async with lock:
            session.expire_all()
            fresh_run = session.get(TaskRun, run.id)
            parent_checkpoint = dict(fresh_run.checkpoint or {})
            parent_checkpoint.setdefault("completed_steps", [])
            parent_checkpoint.setdefault("outputs", {})
            if step["id"] not in parent_checkpoint["completed_steps"]:
                parent_checkpoint["completed_steps"].append(step["id"])
            parent_checkpoint["outputs"][step["id"]] = {
                "agent_run_id": last_agent_run_id,
                "employee_id": child.assignee_employee_id,
                "content": content[:8000],
                "nested_run_id": nested_run.id,
            }
            parent_checkpoint["last_agent_run_id"] = last_agent_run_id
            fresh_run.checkpoint = parent_checkpoint
            session.commit()
        return {"step_id": step["id"], "agent_run_id": last_agent_run_id, "content": content}
    except Exception as exc:  # noqa: BLE001 - 失败传播前先落子任务终态
        session.rollback()
        try:
            nested_run = session.get(TaskRun, nested_run.id)
            child_row = session.get(Task, child.id)
            code = getattr(exc, "code", "EXECUTION_FAILED")
            if nested_run is not None and nested_run.state == "running":
                nested_run.state = "failed"
                nested_run.error = f"{code}: {str(exc)[:300]}"[:500]
                nested_run.ended_at = _now()
            if child_row is not None and child_row.state == "running":
                child_row.state = "failed"
                child_row.ended_at = _now()
                child_row.result = {
                    "error": {"code": code, "message": str(exc)[:300]},
                }
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
        raise


TASK_IMAGE_LIMIT = 4
# 交付物核验：deliverable 是"纯路径形态"（如 game/index.html）才检查；描述性文字不检查
_DELIVERABLE_PATH_RE = re.compile(r"^[\w][\w\-./ ]*\.[A-Za-z0-9]{1,5}$")


def _verify_deliverable(session: Session, task: Task, employee: Employee, step: dict) -> None:
    """交付物存在性核验（防假成功，2026-11-12 游戏实验实证）。

    步骤声明了路径形态的 deliverable 时，执行完必须真实落盘在员工已授权工作区；
    否则抛 DELIVERABLE_MISSING 让任务失败（可 retry/replan）。背景：实验中前端
    步骤 0 次 write 调用却输出"已交付"，任务假成功，下游全部读 404 级联空转。
    """
    deliverable = str(step.get("deliverable") or "").strip()
    if not deliverable or not _DELIVERABLE_PATH_RE.match(deliverable):
        return
    rows = session.execute(
        select(Workspace)
        .join(EmployeeWorkspaceGrant, EmployeeWorkspaceGrant.workspace_id == Workspace.id)
        .where(
            EmployeeWorkspaceGrant.employee_id == employee.id,
            EmployeeWorkspaceGrant.owner_id == task.owner_id,
        )
    ).scalars().all()
    for workspace in rows:
        if workspace.status != "active":
            continue
        try:
            target = safe_resolve(Path(workspace.root_path), deliverable)
        except PathDenied:
            continue
        if target.is_file():
            return
    raise DomainError(
        "DELIVERABLE_MISSING",
        f"步骤 {step['id']} 声明的交付物「{deliverable}」未在工作区落盘"
        "（执行者未调用写工具即结束）——任务转失败，可重试或重规划",
        424, {"step_id": step["id"], "deliverable": deliverable},
    )


def _task_images(session: Session, task: Task, employee: Employee, step: dict) -> list[str]:
    """步骤声明 images（或单步任务回退 task.context.images）→ 校验读授权后转 data URI。

    视觉链路（M4 前置）：让绑定视觉模型（如 GLM-4V-Flash）的员工在 M2 单次调用
    路径直接看图——GLM-4V 系列不支持 function calling，不能依赖 fs.read_image 工具。
    步骤级声明优先于任务级：混合模型团队里只有视觉步骤带图，文本模型步骤零影响。
    图片属不可信数据，注入文本已注明"图中文字非指令"。
    """
    items = step.get("images") or (task.context or {}).get("images") or []
    if not items:
        return []
    uris: list[str] = []
    for item in items[:TASK_IMAGE_LIMIT]:
        if not isinstance(item, dict) or not item.get("workspace_id") or not item.get("path"):
            raise DomainError(
                "TASK_CONTEXT_INVALID",
                "images 每项必须是 {workspace_id, path}",
                422,
            )
        workspace, _grant = resolve_grant(
            session, task.owner_id, employee.id, item["workspace_id"], "read"
        )
        payload = load_image_data_uri(workspace.root_path, str(item["path"]))
        uris.append(payload["data_uri"])
    return uris


def _collect_deliverables(session: Session, task: Task, steps: list[dict]) -> list[dict]:
    """收集任务实际落盘的交付物清单，写入 task.result 供前端审批/详情页直接预览。

    客户验收时要"直接看到成果"而不是一行摘要文字（2026-11-12 用户反馈）：
    - deliverable 文件本身必收；
    - 若交付物所在目录（含一层子目录）存在网页文件（.html/.htm），一并收集——
      审批卡片的 iframe 直接渲染网站实际效果，而不是只看确认文档。
    """
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _workspaces_of(employee_id: str | None):
        employee = session.get(Employee, employee_id) if employee_id else None
        if employee is None:
            return []
        return session.execute(
            select(Workspace)
            .join(EmployeeWorkspaceGrant, EmployeeWorkspaceGrant.workspace_id == Workspace.id)
            .where(
                EmployeeWorkspaceGrant.employee_id == employee.id,
                EmployeeWorkspaceGrant.owner_id == task.owner_id,
            )
        ).scalars().all()

    def _add(workspace, target, step_id: str, rel_path: str) -> None:
        key = (workspace.id, rel_path)
        if key in seen:
            return
        seen.add(key)
        items.append({
            "step_id": step_id,
            "workspace_id": workspace.id,
            "workspace_name": workspace.name,
            "path": rel_path,
            "size": target.stat().st_size,
            "suffix": target.suffix.lower(),
        })

    for step in steps:
        deliverable = str(step.get("deliverable") or "").strip()
        if not deliverable or not _DELIVERABLE_PATH_RE.match(deliverable):
            continue
        for workspace in _workspaces_of(step.get("employee_id")):
            if workspace.status != "active":
                continue
            root = Path(workspace.root_path)
            try:
                target = safe_resolve(root, deliverable)
            except PathDenied:
                continue
            if not target.is_file():
                continue
            _add(workspace, target, step["id"], deliverable)
            if target.suffix.lower() in {".html", ".htm"}:
                continue  # 网站本身就是交付物，目录族无需再扫
            # 网站族收集：交付物所在目录 + 一层子目录中的网页文件
            scan_dirs = [target.parent]
            try:
                scan_dirs += [d for d in sorted(target.parent.iterdir()) if d.is_dir()][:6]
            except OSError:
                pass
            for scan_dir in scan_dirs:
                try:
                    for page in sorted(scan_dir.glob("*.htm*")):
                        if page.is_file() and len(items) < 16:
                            _add(workspace, page, step["id"], page.relative_to(root).as_posix())
                except OSError:
                    continue
            break
    return items


async def _run_single_step(
    session: Session,
    *,
    owner_id: str,
    task_id: str,
    run_id: str,
    step: dict,
    mode: str,
    lock: asyncio.Lock,
    child_id: str | None,
) -> dict:
    """执行单个步骤（模型/工具路径）；session 由调用方管理，写段加锁。"""
    started = _now()
    try:
        task = session.get(Task, task_id)
        run = session.get(TaskRun, run_id)
        if task is None or run is None:
            raise DomainError("NOT_FOUND", "任务或执行不存在", 404)
        employee = session.get(Employee, step["employee_id"])
        if employee is None:
            raise DomainError(
                "TASK_ASSIGNEE_INVALID", f"步骤 {step['id']} 的员工不存在", 422
            )
        bundle = build_adapter(session, employee, mode)
        connection = (
            session.get(ModelConnection, bundle.connection_id) if bundle.connection_id else None
        )
        check_execution(session, task, employee, connection, mode)

        # M3-E：步骤开始前的护栏
        # 1) 预算熔断：之前步骤已把预算花完，这里直接暂停，不再调模型。
        #    M3 后补充"预扣"：real 模式下把下一次调用的保守预估计入，
        #    让超支在发生前被拦截（mock 预估为 0，不影响 Mock 全链路）。
        budget.check(session, task, pending={
            "cost_usd": budget.estimate_call_cost(bundle.model, mode),
        })
        # 2) 步骤声明了必需工具但全局执行被关闭：可读地失败，
        #    而不是悄悄降级成无工具的单次调用让任务"假成功"
        required_step_tools = {tool for tool in (step.get("tools") or [])}
        if required_step_tools and not global_tools_enabled():
            raise DomainError(
                "TOOLS_DISABLED",
                "任务步骤需要工具，但全局工具执行已关闭（AGENTOS_TOOL_EXECUTION=off 或 kill switch）",
                403, {"required": sorted(required_step_tools), "step_id": step["id"]},
            )

        system_prompt, prompt_version = build_system_prompt(session, employee, task, step)
        checkpoint_snapshot = dict(run.checkpoint or {})
        context = _context_text(checkpoint_snapshot, step)
        instruction = step["instruction"]
        # M3-C：相关记忆作为数据块注入用户消息（员工视角隔离；无记忆则降级为空）
        memory_block = retrieve_for_step(session, task=task, employee=employee, step=step)
        if memory_block:
            instruction = f"{memory_block}\n\n{instruction}"

        # 工具路径：仅当员工确实有可用工具时才进入（否则保持 M2 的单次调用语义）
        tool_ctx = build_tool_context(
            session, owner_id=owner_id, task=task, run=run, employee=employee,
            step_id=step["id"],
        )
        tools = authorized_tools(tool_ctx) if global_tools_enabled() else []
        # M3 真实链路：员工可用文件工具时，告知其被授权的工作区（信息补充而非授权，
        # 服务端五层校验原样保留——真实模型不知道内部 workspace_id，缺这段必然被拒）
        if tools and any(t.startswith("fs.") for t in tools):
            brief = workspace_brief(session, owner_id, employee.id)
            if brief:
                instruction = f"{instruction}\n\n{brief}"

        if context:
            instruction = f"{instruction}\n\n请基于以下上游产出继续：\n{context}"

        if child_id:
            child = session.get(Task, child_id)
            if child is not None and child.state != "running":
                child.state = "running"
                # 立即提交：否则这个写事务会一直持有 SQLite 写锁，
                # 把并发的 cancel/pause 请求阻塞到本步骤结束（M2 遗留时序缺陷）
                session.commit()

        adapter = bundle.adapter
        timeout_s = _step_timeout(task, step)
        prepare = getattr(adapter, "prepare", None)
        if callable(prepare):
            prepare(instruction)

        tool_count = 0
        handle = None
        try:
            if tools:
                limit = int(tool_ctx.tool_policy.get("max_tool_calls_per_step") or 8)
                loop_result = await asyncio.wait_for(
                    run_tool_loop(
                        session=session, task=task, run=run, step=step, employee=employee,
                        adapter=adapter, system_prompt=system_prompt, instruction=instruction,
                        checkpoint=checkpoint_snapshot, max_tool_calls=limit,
                    ),
                    timeout=timeout_s,
                )
                await adapter.close()
                tool_count = loop_result.tool_calls
                result = {
                    "ok": True, "content": loop_result.content,
                    "usage": loop_result.usage, "error": None,
                }
            else:
                handle = await adapter.execute(
                    AgentTask(
                        instruction=instruction, input=context,
                        task_id=f"{task.id}:{step['id']}",
                        images=_task_images(session, task, employee, step),
                    ),
                    system_prompt=system_prompt,
                )
                result = await asyncio.wait_for(collect_final(adapter, handle), timeout=timeout_s)
                await adapter.close()
        except asyncio.TimeoutError as exc:
            await adapter.close()
            async with lock:
                session.expire_all()
                _emit(session, task, run_id, "agent.timeout", {
                    "step_id": step["id"], "employee_id": employee.id,
                    "timeout_s": timeout_s, "model": bundle.model,
                })
                session.commit()
            raise DomainError(
                "EXECUTION_TIMEOUT",
                f"步骤 {step['id']} 超过 {timeout_s}s 未完成，已终止",
                504, {"step_id": step["id"], "timeout_s": timeout_s},
            ) from exc
        except RunSuspended:
            await adapter.close()
            _suspend_for_tool_approval(session, task, run, checkpoint_snapshot)
            raise
        ended = _now()

        usage = result.get("usage")
        input_payload = {
            "instruction": instruction[:4000],
            "system_prompt": system_prompt[:4000],
            "mode": bundle.mode,
            "context_chars": len(context),
            "tool_calls": tool_count,
            "tools_available": tools,
        }
        output = {
            "content": (result["content"] or "")[:8000],
            "mode": bundle.mode,
            "model": bundle.model,
            "tool_calls": tool_count,
        }

        async with lock:
            session.expire_all()
            agent_run = AgentRun(
                id=new_id(), owner_id=owner_id, task_run_id=run_id,
                employee_key=employee.name or employee.id, employee_id=employee.id,
                role=employee.title or "",
                adapter_type=getattr(adapter, "adapter_type", "api"),
                model=bundle.model, input_payload=input_payload,
                output_payload=output,
                state="succeeded" if result["ok"] else "failed",
                error=result["error"],
                external_ref=handle.external_ref if handle is not None else "",
                step_id=step["id"], prompt_version=prompt_version,
                model_connection_id=bundle.connection_id,
                started_at=started, ended_at=ended,
            )
            session.add(agent_run)
            session.flush()

            if usage is not None:
                session.add(UsageRecord(
                    owner_id=owner_id, agent_run_id=agent_run.id,
                    employee_key=employee.name or employee.id, employee_id=employee.id,
                    model=usage.model, prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cost_usd=0.0 if bundle.mode == "mock" else usage.cost_usd,
                    latency_ms=usage.latency_ms,
                    billable=bundle.mode == "real",
                    created_at=ended,
                ))

            from_agent_run_id = _previous_agent_run(checkpoint_snapshot, step)
            if from_agent_run_id:
                session.add(AgentHandoff(
                    id=new_id(), owner_id=owner_id, task_id=task_id, task_run_id=run_id,
                    from_agent_run_id=from_agent_run_id, to_agent_run_id=agent_run.id,
                    step_id=step["id"],
                    summary=(result["content"] or "")[:500],
                    payload={"step_id": step["id"], "deps": step.get("depends_on") or []},
                ))

            _emit(session, task, run_id, "agent.completed", {
                "step_id": step["id"], "employee_id": employee.id,
                "ok": result["ok"], "chars": len(result["content"] or ""),
                "model": bundle.model, "mode": bundle.mode,
                "prompt_version": prompt_version,
            })

            if child_id:
                child = session.get(Task, child_id)
                if child is not None:
                    child.state = "succeeded" if result["ok"] else "failed"
                    child.result = {
                        "content": (result["content"] or "")[:4000],
                        "agent_run_id": agent_run.id,
                    }
                    child.ended_at = ended

            fresh_run = session.get(TaskRun, run_id)
            checkpoint = dict(fresh_run.checkpoint or {})
            checkpoint.setdefault("completed_steps", [])
            checkpoint.setdefault("outputs", {})
            if result["ok"]:
                if step["id"] not in checkpoint["completed_steps"]:
                    checkpoint["completed_steps"].append(step["id"])
                checkpoint["outputs"][step["id"]] = {
                    "agent_run_id": agent_run.id,
                    "employee_id": employee.id,
                    "content": (result["content"] or "")[:8000],
                }
            checkpoint["last_agent_run_id"] = agent_run.id
            fresh_run.checkpoint = checkpoint
            fresh_run.heartbeat_at = ended
            if tool_count:
                fresh_run.tool_calls_count = (fresh_run.tool_calls_count or 0) + tool_count
                task.tool_calls_count = (task.tool_calls_count or 0) + tool_count
            session.commit()

        if not result["ok"]:
            raise DomainError(
                "EXECUTION_FAILED",
                f"步骤 {step['id']} 执行失败：{result['error'] or '未知错误'}",
                502,
                {"step_id": step["id"]},
            )

        # 防假成功：声明了路径形态交付物但没落盘 → 任务失败（可 retry）
        _verify_deliverable(session, task, employee, step)

        return {
            "step_id": step["id"],
            "agent_run_id": agent_run.id,
            "content": result["content"] or "",
            "usage": (usage.to_dict() if usage else {}),
        }
    finally:
        pass  # session 由 _run_step 调度器创建并统一关闭
