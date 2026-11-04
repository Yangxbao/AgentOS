"""M0 顺序协作编排：两个不同职责的员工完成一次真实交接。

研究员（researcher）产出分析 → 审查员（reviewer）独立审查并给出结构化意见。
全程落库：task / task_run / agent_run×2 / task_event×N / usage_record×2。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from packages.agent_core import AgentAdapter
from packages.agent_core.adapter import collect_final
from packages.persistence.models import AgentRun, Task, TaskEvent, TaskRun, UsageRecord
from packages.shared.types import AgentTask, new_id, utcnow


@dataclass
class EmployeeSpec:
    """M0 简化员工定义（M1 会落 employee 表）。role/goal/backstory 借鉴 CrewAI。"""

    key: str
    role: str
    goal: str
    backstory: str
    adapter: AgentAdapter

    @property
    def system_prompt(self) -> str:
        return f"你是{self.role}。目标：{self.goal}。背景：{self.backstory}"


def _emit(session: Session, task_id: str, task_run_id: str | None, type_: str, payload: dict) -> None:
    session.add(TaskEvent(task_id=task_id, task_run_id=task_run_id, type=type_, payload=payload))


async def _run_employee(
    session: Session,
    task_run_id: str,
    employee: EmployeeSpec,
    instruction: str,
    input_text: str,
) -> tuple[AgentRun, dict[str, Any]]:
    agent_run = AgentRun(
        id=new_id(),
        task_run_id=task_run_id,
        employee_key=employee.key,
        role=employee.role,
        adapter_type=employee.adapter.adapter_type,
        model=getattr(employee.adapter, "model", ""),
        input_payload={"instruction": instruction, "input": input_text[:2000]},
    )
    session.add(agent_run)
    session.flush()

    handle = await employee.adapter.execute(
        AgentTask(instruction=instruction, input=input_text),
        system_prompt=employee.system_prompt,
    )
    result = await collect_final(employee.adapter, handle)

    agent_run.state = "succeeded" if result["ok"] else "failed"
    agent_run.error = result["error"]
    agent_run.output_payload = {"content": result["content"][:8000]}
    agent_run.external_ref = handle.external_ref

    usage = result.get("usage")
    if usage is not None:
        session.add(UsageRecord(
            agent_run_id=agent_run.id,
            employee_key=employee.key,
            model=usage.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=usage.latency_ms,
        ))
    return agent_run, result


async def run_sequential_handoff(
    session: Session,
    researcher: EmployeeSpec,
    reviewer: EmployeeSpec,
    objective: str,
) -> dict[str, Any]:
    """执行一次 研究员→审查员 顺序交接任务，返回可 JSON 序列化的结果。"""
    task = Task(id=new_id(), title=objective[:120], objective=objective, state="running")
    session.add(task)
    session.flush()
    task_run = TaskRun(id=new_id(), task_id=task.id, run_no=1, trigger="manual")
    session.add(task_run)
    session.flush()
    _emit(session, task.id, task_run.id, "dispatched", {"objective": objective})

    # 阶段 1：研究员
    research_instruction = (
        "请就以下目标做简明分析，输出 3-5 条要点，每条一句话。\n目标：" + objective
    )
    run1, res1 = await _run_employee(session, task_run.id, researcher, research_instruction, "")
    _emit(session, task.id, task_run.id, "agent_completed",
          {"employee": researcher.key, "ok": res1["ok"], "chars": len(res1["content"])})

    if not res1["ok"]:
        task_run.state = "failed"
        task_run.error = f"researcher failed: {res1['error']}"
        task.state = "failed"
        task_run.ended_at = utcnow()
        _emit(session, task.id, task_run.id, "failed", {"stage": "research", "error": res1["error"]})
        session.commit()
        return {"ok": False, "task_id": task.id, "error": res1["error"]}

    # 阶段 2：审查员独立审查（交接物 = 研究员产出全文）
    review_instruction = (
        "你是独立审查员。请审查以下分析成果：1) 指出最大的一处事实或逻辑风险；"
        "2) 给出结论（pass/reject）与一句理由。用 JSON 格式输出："
        '{"conclusion": "...", "risk": "...", "reason": "..."}'
    )
    run2, res2 = await _run_employee(session, task_run.id, reviewer, review_instruction, res1["content"])
    _emit(session, task.id, task_run.id, "agent_completed",
          {"employee": reviewer.key, "ok": res2["ok"], "chars": len(res2["content"])})

    if not res2["ok"]:
        task_run.state = "failed"
        task_run.error = f"reviewer failed: {res2['error']}"
        task.state = "failed"
        task_run.ended_at = utcnow()
        _emit(session, task.id, task_run.id, "failed", {"stage": "review", "error": res2["error"]})
        session.commit()
        return {"ok": False, "task_id": task.id, "error": res2["error"]}

    review = _try_parse_review(res2["content"])
    conclusion = review.get("conclusion", "unknown")
    task_run.state = "succeeded"
    task_run.ended_at = utcnow()
    # M0 简化：审查结论仅记录，状态机裁决（in_review→review_passed/rework）在 M3 完整实现
    task.state = "review_passed" if conclusion == "pass" else "in_review"
    _emit(session, task.id, task_run.id, "completed",
          {"review_conclusion": conclusion, "task_state": task.state})
    session.commit()

    return {
        "ok": True,
        "task_id": task.id,
        "task_run_id": task_run.id,
        "task_state": task.state,
        "research_output": res1["content"],
        "review_output": res2["content"],
        "review_parsed": review,
        "agent_runs": [run1.id, run2.id],
    }


def _try_parse_review(text: str) -> dict[str, Any]:
    """尽力解析审查员 JSON 输出；解析失败不伪造，返回 unknown。"""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        data = json.loads(text[start:end])
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError):
        pass
    return {"conclusion": "unknown", "raw": text[:500]}
