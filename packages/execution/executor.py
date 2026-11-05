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
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.agent_core.adapter import collect_final
from packages.persistence import get_session
from packages.persistence.models import (
    AgentHandoff,
    AgentRun,
    Employee,
    ModelConnection,
    Task,
    TaskApproval,
    TaskEvent,
    TaskRun,
    UsageRecord,
)
from packages.shared.errors import DomainError
from packages.shared.types import AgentTask, new_id
from packages.tasks import state as st
from packages.tasks.approvals import create_approval
from packages.tasks.plan import topological_waves

from .adapter_factory import build_adapter
from .guard import check_execution, steps_of
from .prompting import build_system_prompt

logger = logging.getLogger("agentos.execution")


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

        failures = [item for item in results if isinstance(item, BaseException)]
        session.expire_all()
        run = session.get(TaskRun, run.id)
        task = session.get(Task, task.id)
        checkpoint = dict(run.checkpoint or {})
        completed = set(checkpoint.get("completed_steps", []))

        if failures:
            exc = failures[0]
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
    }
    task.version = (task.version or 1) + 1
    run.state = "succeeded"
    run.ended_at = _now()
    run.checkpoint = checkpoint
    _emit(session, task, run.id, "task.succeeded", {
        "steps": len(steps), "cost_usd": cost, "mode": run.mode,
    })
    session.commit()
    return "succeeded"


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
    """执行单个步骤；独立 session，写段加锁。"""
    session = get_session()
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

        system_prompt, prompt_version = build_system_prompt(session, employee, task, step)
        checkpoint_snapshot = dict(run.checkpoint or {})
        context = _context_text(checkpoint_snapshot, step)
        instruction = step["instruction"]
        if context:
            instruction = f"{instruction}\n\n请基于以下上游产出继续：\n{context}"

        if child_id:
            child = session.get(Task, child_id)
            if child is not None:
                child.state = "running"

        adapter = bundle.adapter
        handle = await adapter.execute(
            AgentTask(instruction=instruction, input=context, task_id=f"{task.id}:{step['id']}"),
            system_prompt=system_prompt,
        )
        result = await collect_final(adapter, handle)
        await adapter.close()
        ended = _now()

        usage = result.get("usage")
        input_payload = {
            "instruction": instruction[:4000],
            "system_prompt": system_prompt[:4000],
            "mode": bundle.mode,
            "context_chars": len(context),
        }
        output = {
            "content": (result["content"] or "")[:8000],
            "mode": bundle.mode,
            "model": bundle.model,
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
                external_ref=handle.external_ref,
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
            session.commit()

        if not result["ok"]:
            raise DomainError(
                "EXECUTION_FAILED",
                f"步骤 {step['id']} 执行失败：{result['error'] or '未知错误'}",
                502,
                {"step_id": step["id"]},
            )

        return {
            "step_id": step["id"],
            "agent_run_id": agent_run.id,
            "content": result["content"] or "",
            "usage": (usage.to_dict() if usage else {}),
        }
    finally:
        session.close()
