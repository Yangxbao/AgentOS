"""运行中预算熔断（M3-E）。

与 M2 的静态预估（guard.check_execution 的 EXECUTION_BUDGET_EXCEEDED）互补：
- guard 在执行前用单价档位**预估**，超出直接拒绝入队；
- 这里在执行中按 `usage_record` **真实累计** cost 与 tokens，超限暂停任务。

限额来源（优先级从高到低）：
- 成本：`task.budget_usd` → 公司策略 `policy.default_budget_usd`；
- Token：公司策略 `policy.default_task_budget_tokens`（任务级无 token 字段）。

超限抛 `BUDGET_EXCEEDED`，由执行器转为任务暂停（不是失败），
事件 `task.budget_exceeded`，task.result.error 可读。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.persistence.models import AgentRun, Company, Task, TaskRun, UsageRecord
from packages.shared.errors import DomainError

BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


def _company(session: Session, task: Task) -> Company | None:
    if not task.company_id:
        return None
    return session.get(Company, task.company_id)


def limits_for(session: Session, task: Task) -> dict:
    """任务的预算上限：{cost_usd, tokens}，None 表示该项不设限。"""
    company = _company(session, task)
    policy = (company.policy or {}) if company is not None else {}
    cost_limit = task.budget_usd
    if cost_limit is None:
        raw_default = policy.get("default_budget_usd")
        try:
            cost_limit = float(raw_default) if raw_default is not None else None
        except (TypeError, ValueError):
            cost_limit = None
    tokens_limit = policy.get("default_task_budget_tokens")
    if tokens_limit is not None:
        try:
            tokens_limit = int(tokens_limit)
            if tokens_limit <= 0:
                tokens_limit = None
        except (TypeError, ValueError):
            tokens_limit = None
    return {"cost_usd": cost_limit, "tokens": tokens_limit}


def spent_for(session: Session, task_id: str) -> dict:
    """任务已产生的真实消耗（按 usage_record 累计；mock 成本为 0 属实）。"""
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


def status(session: Session, task: Task, pending: dict | None = None) -> dict:
    """当前预算快照；pending 是本轮尚未落库的消耗（工具循环内已调模型未提交的部分）。"""
    limits = limits_for(session, task)
    spent = spent_for(session, task.id)
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
