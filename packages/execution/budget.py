"""运行中预算熔断（M3-E，M3-B 扩展为任务树感知）。

与 M2 的静态预估（guard.check_execution 的 EXECUTION_BUDGET_EXCEEDED）互补：
- guard 在执行前用单价档位**预估**，超出直接拒绝入队；
- 这里在执行中按 `usage_record` **真实累计** cost 与 tokens，超限暂停任务。

M3-B 递归语义（防止子任务绕过预算）：
- 限额取**祖先链上最紧**的预算（任务自身 → 根任务，None 视为不设限）；
- 消耗按**整棵任务树**聚合（root_task_id 相同的所有任务）；
- 因此子任务不可能通过递归拆分逃避父任务预算；子任务自己的 budget_usd 只会进一步收紧。

超限抛 `BUDGET_EXCEEDED`，由执行器转为任务暂停（不是失败），
事件 `task.budget_exceeded`，task.result.error 可读。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.persistence.models import AgentRun, Company, Task, TaskRun, UsageRecord
from packages.shared.errors import DomainError

BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
# M3-B：单任务树总工具调用上限（防递归失控扩张；后端强制，不依赖 Prompt）
TREE_TOOL_CALL_LIMIT = 100


def root_of(session: Session, task: Task) -> Task:
    """沿 parent_task_id 走到根任务（防御性上限 32 层，防脏数据成环）。"""
    current = task
    for _ in range(32):
        if not current.parent_task_id:
            return current
        parent = session.get(Task, current.parent_task_id)
        if parent is None:
            return current
        current = parent
    return current


def _company(session: Session, task: Task) -> Company | None:
    if not task.company_id:
        return None
    return session.get(Company, task.company_id)


def _tree_ids(session: Session, root_id: str) -> list[str]:
    rows = session.execute(
        select(Task.id).where(Task.root_task_id == root_id)
    ).scalars().all()
    return list(rows) or [root_id]


def limits_for(session: Session, task: Task) -> dict:
    """任务树的有效预算上限：{cost_usd, tokens}，None 表示该项不设限。

    成本取祖先链上所有显式预算的最小值（子任务只能收紧，不能放宽）；
    Token 上限来自公司策略（任务级无 token 字段）。
    """
    company = _company(session, task)
    policy = (company.policy or {}) if company is not None else {}
    tokens_limit = policy.get("default_task_budget_tokens")
    if tokens_limit is not None:
        try:
            tokens_limit = int(tokens_limit)
            if tokens_limit <= 0:
                tokens_limit = None
        except (TypeError, ValueError):
            tokens_limit = None

    cost_limit: float | None = None
    current: Task | None = task
    for _ in range(32):
        if current is None:
            break
        if current.budget_usd is not None:
            value = float(current.budget_usd)
            cost_limit = value if cost_limit is None else min(cost_limit, value)
        if not current.parent_task_id:
            break
        current = session.get(Task, current.parent_task_id)
    return {"cost_usd": cost_limit, "tokens": tokens_limit}


def spent_for(session: Session, task_id: str) -> dict:
    """单个任务的已产生消耗（按 usage_record 累计；mock 成本为 0 属实）。"""
    row = session.execute(
        select(
            func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
            func.coalesce(func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), 0),
        )
        .join(AgentRun, AgentRun.id == UsageRecord.agent_run_id)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .where(TaskRun.task_id == task_id)
    ).one()
    return {
        "cost_usd": round(float(row[0] or 0.0), 8),
        "tokens": int(row[1] or 0),
    }


def spent_for_tree(session: Session, task: Task) -> dict:
    """整棵任务树的已产生消耗（防递归拆分重复计算/逃避预算）。"""
    root = root_of(session, task)
    row = session.execute(
        select(
            func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
            func.coalesce(func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), 0),
        )
        .join(AgentRun, AgentRun.id == UsageRecord.agent_run_id)
        .join(TaskRun, TaskRun.id == AgentRun.task_run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .where(Task.root_task_id == (root.root_task_id or root.id))
    ).one()
    return {
        "cost_usd": round(float(row[0] or 0.0), 8),
        "tokens": int(row[1] or 0),
    }


def tree_tool_calls(session: Session, task: Task) -> int:
    """整棵任务树已发生的工具调用次数快照。"""
    root = root_of(session, task)
    total = session.execute(
        select(func.coalesce(func.sum(Task.tool_calls_count), 0)).where(
            Task.root_task_id == (root.root_task_id or root.id)
        )
    ).scalar_one()
    return int(total or 0)


def status(session: Session, task: Task, pending: dict | None = None) -> dict:
    """当前预算快照；pending 是本轮尚未落库的消耗（工具循环内已调模型未提交的部分）。"""
    limits = limits_for(session, task)
    spent = spent_for_tree(session, task)
    if pending:
        spent["cost_usd"] = round(spent["cost_usd"] + float(pending.get("cost_usd") or 0.0), 8)
        spent["tokens"] = int(spent["tokens"] + int(pending.get("tokens") or 0))
    cost_limit = limits["cost_usd"]
    tokens_limit = limits["tokens"]
    return {
        "limit_usd": cost_limit,
        "limit_tokens": tokens_limit,
        "spent_usd": spent["cost_usd"],
        "spent_tokens": spent["tokens"],
        "cost_exceeded": cost_limit is not None and spent["cost_usd"] > float(cost_limit),
        "tokens_exceeded": tokens_limit is not None and spent["tokens"] > int(tokens_limit),
    }


def check(session: Session, task: Task, pending: dict | None = None) -> dict:
    """预算检查：未超限返回快照；超限抛 BUDGET_EXCEEDED（执行器将其转为暂停）。"""
    snapshot = status(session, task, pending)
    reasons = []
    if snapshot["cost_exceeded"]:
        reasons.append(
            f"成本 ${snapshot['spent_usd']} 已超过预算 ${snapshot['limit_usd']}"
        )
    if snapshot["tokens_exceeded"]:
        reasons.append(
            f"Token 用量 {snapshot['spent_tokens']} 已超过上限 {snapshot['limit_tokens']}"
        )
    if reasons:
        raise DomainError(
            BUDGET_EXCEEDED,
            "任务预算耗尽：" + "；".join(reasons) + "，已自动暂停",
            409,
            {key: snapshot[key] for key in (
                "limit_usd", "limit_tokens", "spent_usd", "spent_tokens",
            )},
        )
    return snapshot
