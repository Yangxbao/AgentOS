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
from packages.tools.policy import global_tools_enabled

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
            return run.state  # awaiting_approval

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

        # M3-E：步骤开始前的护栏
        # 1) 预算熔断：之前步骤已把预算花完，这里直接暂停，不再调模型
        budget.check(session, task)
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

        # 工具路径：仅当员工确实有可用工具时才进入（否则保持 M2 的单次调用语义）
        tool_ctx = build_tool_context(
            session, owner_id=owner_id, task=task, run=run, employee=employee,
            step_id=step["id"],
        )
        tools = authorized_tools(tool_ctx) if global_tools_enabled() else []
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

        return {
            "step_id": step["id"],
            "agent_run_id": agent_run.id,
            "content": result["content"] or "",
            "usage": (usage.to_dict() if usage else {}),
        }
    finally:
        session.close()
