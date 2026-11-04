"""派工预览（B5）：硬过滤 8 条 + 五因子打分 + 正式/降级审查池（T1..T6）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core.capabilities import employee_capabilities
from packages.model_gateway import catalog
from packages.model_gateway.credentials import has_credential
from packages.organization.common import iso_utc
from packages.persistence.models import (
    AssignmentDecision,
    Company,
    Employee,
    EmployeePosition,
    ModelConnection,
    Position,
)
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .effective import compute_effective_permissions

ALGORITHM_VERSION = "m1.0"
TIER_ORDER = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5, "T6": 6}
COST_ESTIMATE = {"local": 0.0, "budget": 0.01, "middle": 0.03, "premium": 0.08}
COST_SCORE = {"local": 1.0, "budget": 0.9, "middle": 0.6, "premium": 0.3}
RISK_ORDER = ["low", "medium", "high", "critical"]


def _walk_up(session: Session, start: str | None, limit: int = 20) -> list[str]:
    chain: list[str] = []
    current = start
    while current and len(chain) < limit:
        if current in chain:
            break
        chain.append(current)
        employee = session.get(Employee, current)
        current = employee.reports_to if employee else None
    return chain


def _is_subordinate(session: Session, candidate: Employee, doer: Employee) -> bool:
    return doer.id in _walk_up(session, candidate.reports_to)


def _is_management_ancestor(session: Session, candidate: Employee, doer: Employee) -> bool:
    return candidate.id in _walk_up(session, doer.reports_to)


def _positions_of(session: Session, employee_id: str) -> list[Position]:
    links = session.execute(
        select(EmployeePosition).where(EmployeePosition.employee_id == employee_id)
    ).scalars().all()
    return [p for p in (session.get(Position, link.position_id) for link in links) if p]


def _connection_of(session: Session, employee: Employee) -> ModelConnection | None:
    return session.get(ModelConnection, employee.primary_model_id) if employee.primary_model_id else None


def _model_ok(connection: ModelConnection | None) -> bool:
    return bool(connection and connection.enabled and has_credential(connection.api_key_ref))


def _employee_context(session: Session, employee: Employee) -> dict:
    caps = employee_capabilities(session, employee)
    positions = _positions_of(session, employee.id)
    connection = _connection_of(session, employee)
    info = catalog.model_info(connection.model) if connection else None
    return {
        "employee": employee,
        "positions": positions,
        "connection": connection,
        "model_info": info,
        "tags": set(caps["domain_tags"]),
        "tools": set(employee.tools_allowed or []),
        "capabilities": caps,
        "permissions": compute_effective_permissions(session, employee.owner_id, employee.id)["permissions"],
    }


def _hard_filter(ctx: dict, company: Company, request: dict, prefer_department: str | None) -> str | None:
    employee: Employee = ctx["employee"]
    if company.status == "archived":
        return "company_archived"
    if employee.status != "active" or employee.deleted_at is not None:
        return "inactive"
    if not _model_ok(ctx["connection"]):
        return "no_model"
    required = set(request.get("required_capabilities") or [])
    if required and not required.issubset(ctx["tags"]):
        missing = sorted(required - ctx["tags"])
        return f"capability_missing:{','.join(missing)}"
    required_tools = set(request.get("required_tools") or [])
    if required_tools and not required_tools.issubset(ctx["tools"]):
        missing = sorted(required_tools - ctx["tools"])
        return f"tool_denied:{','.join(missing)}"
    risk = request.get("risk_level", "low")
    max_risk = ctx["permissions"].get("max_risk_level", "medium")
    if RISK_ORDER.index(risk) > RISK_ORDER.index(max_risk):
        return "risk_exceeded"
    budget = request.get("budget_usd")
    if budget is not None and ctx["model_info"] is not None:
        estimate = COST_ESTIMATE.get(ctx["model_info"].cost_tier, 0.03)
        if estimate > float(budget):
            return "over_budget"
    if employee.id in (request.get("exclude_employee_ids") or []):
        return "excluded_by_request"
    return None


def _score(ctx: dict, prefer_department: str | None) -> dict:
    employee: Employee = ctx["employee"]
    position_match = 0.5
    if ctx["positions"]:
        position_match = 0.7
        if prefer_department and any(p.department_id == prefer_department for p in ctx["positions"]):
            position_match = 1.0
        elif employee.department_id and prefer_department and employee.department_id == prefer_department:
            position_match = 0.9
    chain_score = 0.3
    if prefer_department:
        chain_score = 0.9 if employee.department_id == prefer_department else 0.5
    tier = ctx["model_info"].cost_tier if ctx["model_info"] else "middle"
    factors = {
        "position_match": position_match,
        "review_chain_distance": chain_score,
        "performance": 0.5,
        "cost_efficiency": COST_SCORE.get(tier, 0.5),
        "load": 0.5,
    }
    weights = {"position_match": 0.30, "review_chain_distance": 0.20,
               "performance": 0.20, "cost_efficiency": 0.15, "load": 0.15}
    score = round(sum(factors[k] * weights[k] for k in weights), 4)
    return {"score": score, "factors": factors, "weights": weights}


def _reviewer_pool(session: Session, company_id: str, doer_ctx: dict, request: dict) -> dict:
    doer: Employee = doer_ctx["employee"]
    required = set(request.get("required_capabilities") or [])
    active = list(session.execute(
        select(Employee).where(
            Employee.company_id == company_id, Employee.status == "active", Employee.deleted_at.is_(None)
        )
    ).scalars().all())

    formal: list[dict] = []
    degraded: list[dict] = []
    excluded: list[dict] = []

    for employee in active:
        if employee.id == doer.id:
            continue
        ctx = _employee_context(session, employee)
        if not _model_ok(ctx["connection"]):
            excluded.append({"employee_id": employee.id, "reason": "no_model"})
            continue
        if required and not required.issubset(ctx["tags"]):
            excluded.append({"employee_id": employee.id, "reason": "capability_missing"})
            continue
        if _is_subordinate(session, employee, doer):
            excluded.append({"employee_id": employee.id, "reason": "subordinate_not_allowed"})
            continue
        if employee.id in (request.get("exclude_employee_ids") or []):
            excluded.append({"employee_id": employee.id, "reason": "excluded_by_request"})
            continue
        can_review = any(p.can_review for p in ctx["positions"])
        cross_model = bool(
            ctx["connection"] and doer_ctx["connection"] and ctx["connection"].model != doer_ctx["connection"].model
        )
        cross_provider = bool(
            ctx["connection"]
            and doer_ctx["connection"]
            and ctx["connection"].provider != doer_ctx["connection"].provider
        )
        if can_review:
            if _is_management_ancestor(session, employee, doer):
                tier = "T5"
            else:
                same_dept = employee.department_id == doer.department_id
                tier = {(False, True): "T1", (True, True): "T2",
                        (False, False): "T3", (True, False): "T4"}[(same_dept, cross_model)]
            formal.append({
                "employee_id": employee.id, "model": ctx["connection"].model,
                "tier": tier, "cross_model": cross_model, "cross_provider": cross_provider,
                "management_review": tier == "T5",
            })
        elif employee.department_id != doer.department_id:
            degraded.append({
                "employee_id": employee.id, "model": ctx["connection"].model,
                "tier": "T6", "cross_model": cross_model, "cross_provider": cross_provider,
                "management_review": False, "degraded_reviewer": True,
            })

    pool_name = "formal" if formal else ("degraded" if degraded else None)
    pool = formal or degraded
    if not pool:
        if len(active) <= 1:
            code, suggestion = "company_has_single_employee", "至少招聘 1 名具备能力与审查资格的同事"
        elif any(item["reason"] == "subordinate_not_allowed" for item in excluded):
            code, suggestion = "only_subordinate_candidates", "开启 allow_subordinate_review 或指定其他审查人"
        elif any(item["reason"] == "capability_missing" for item in excluded):
            code, suggestion = "capability_not_covered", "提升审查人能力标签，或降低任务能力要求"
        else:
            code, suggestion = "no_eligible_reviewer", "增加跨部门审查岗，或手动指定审查人"
        return {"reviewer": None, "pool": None, "reason_code": code, "suggestion": suggestion,
                "excluded": excluded}

    pool.sort(key=lambda item: (
        TIER_ORDER[item["tier"]], not item["cross_provider"], not item["cross_model"], item["employee_id"]
    ))
    best = pool[0]
    reviewer = session.get(Employee, best["employee_id"])
    return {
        "reviewer": {
            "employee_id": best["employee_id"],
            "name": reviewer.name if reviewer else "",
            "model": best["model"],
            "pool": pool_name,
            "independence": best["tier"],
            "cross_model": best["cross_model"],
            "cross_provider": best["cross_provider"],
            "management_review": best["management_review"],
            "degraded_reviewer": best.get("degraded_reviewer", False),
            "warnings": ["degraded_reviewer_used"] if pool_name == "degraded" else [],
        },
        "pool": pool_name,
        "reason_code": None,
        "excluded": excluded,
    }


def preview_assignment(session: Session, owner_id: str, company_id: str, request: dict) -> dict:
    company = session.get(Company, company_id)
    if company is None or company.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"公司不存在：{company_id}", 404)
    risk = request.get("risk_level", "low")
    if risk not in RISK_ORDER:
        raise DomainError("VALIDATION_ERROR", "risk_level 必须是 low/medium/high/critical", 422)

    prefer_department = request.get("prefer_department_id")
    employees = list(session.execute(
        select(Employee).where(
            Employee.company_id == company_id, Employee.deleted_at.is_(None)
        )
    ).scalars().all())

    candidates, excluded = [], []
    for employee in employees:
        ctx = _employee_context(session, employee)
        reason = _hard_filter(ctx, company, request, prefer_department)
        if reason:
            excluded.append({"employee_id": employee.id, "name": employee.name, "reason": reason})
            continue
        scored = _score(ctx, prefer_department)
        candidates.append({
            "employee_id": employee.id, "name": employee.name,
            "model": ctx["connection"].model if ctx["connection"] else "",
            "score": scored["score"], "factors": scored["factors"],
        })
    candidates.sort(key=lambda item: (-item["score"], item["employee_id"]))

    selected_id = request.get("selected_employee_id")
    candidate_ids = {item["employee_id"] for item in candidates}
    if selected_id and selected_id not in candidate_ids:
        raise DomainError("VALIDATION_ERROR", "selected_employee_id 不在候选集中", 422)
    if candidates:
        doer_id = selected_id or candidates[0]["employee_id"]
        doer = session.get(Employee, doer_id)
        doer_ctx = _employee_context(session, doer) if doer is not None else {"employee": None}
        reviewer_info = _reviewer_pool(session, company_id, doer_ctx, request)
    else:
        reviewer_info = {
            "reviewer": None, "pool": None, "reason_code": "no_candidate",
            "suggestion": "先满足派工硬过滤条件", "excluded": [],
        }

    data_quality = {"performance": "unavailable", "load": "unavailable"}
    decision = AssignmentDecision(
        id=new_id(), owner_id=owner_id, company_id=company_id, requested_by=owner_id,
        requirement=request, candidates=candidates,
        selected_employee_id=selected_id,
        reviewer_employee_id=(reviewer_info["reviewer"] or {}).get("employee_id"),
        reviewer_meta=reviewer_info, data_quality=data_quality, algorithm_version=ALGORITHM_VERSION,
    )
    session.add(decision)
    session.commit()
    session.refresh(decision)

    return {
        "decision_id": decision.id,
        "candidates": candidates,
        "excluded": excluded,
        "reviewer": reviewer_info["reviewer"],
        "reviewer_reason_code": reviewer_info["reason_code"],
        "reviewer_suggestion": reviewer_info.get("suggestion"),
        "data_quality": data_quality,
        "score_note": "m1.0 暂定权重；performance/load 为中性值 0.5，不构成真实绩效评估",
        "algorithm_version": ALGORITHM_VERSION,
        "created_at": iso_utc(decision.created_at),
    }


def get_decision(session: Session, owner_id: str, decision_id: str) -> dict:
    decision = session.get(AssignmentDecision, decision_id)
    if decision is None or decision.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"派工决策不存在：{decision_id}", 404)
    return {
        "decision_id": decision.id,
        "company_id": decision.company_id,
        "requirement": decision.requirement,
        "candidates": decision.candidates,
        "reviewer": decision.reviewer_meta.get("reviewer"),
        "reviewer_reason_code": decision.reviewer_meta.get("reason_code"),
        "data_quality": decision.data_quality,
        "algorithm_version": decision.algorithm_version,
        "created_at": iso_utc(decision.created_at),
    }
