"""统一工具调用入口（M3-A）。

任何工具执行都必须走这里：
参数校验 → 权限决策 → 风险/审批 → 幂等 → 执行 → 截断 → 脱敏 → 落库 → 审计 → 事件。

禁止绕过本模块直接调用 handler（handler 里也没有独立的权限判断）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from packages.permissions.audit import sanitize_detail, write_audit
from packages.persistence.models import TaskEvent, ToolCall
from packages.shared.errors import DomainError

from .context import ToolContext, ToolOutcome
from .paths import PathDenied
from .policy import decide
from .registry import ToolSpec, get_spec
from .schema import validate_args

DENY_CODES = {
    "TOOL_PATH_DENIED",
    "TOOL_SENSITIVE_FILE",
    "TOOL_NETWORK_DENIED",
    "TOOL_SSRF_BLOCKED",
    "TOOL_NOT_GRANTED",
    "TOOL_NOT_REGISTERED",
    "TOOL_DISABLED",
    "SHELL_DISABLED",
    "CATEGORY_DISABLED",
    "RISK_EXCEEDED",
    "WORKSPACE_NOT_GRANTED",
    "WORKSPACE_READ_ONLY",
    "WORKSPACE_ARCHIVED",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_args(args: dict) -> str:
    payload = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _idempotency_key(ctx: ToolContext, tool: str, args_hash: str, call_index: int) -> str:
    raw = f"{ctx.task.id if ctx.task else '-'}|{ctx.step_id}|{call_index}|{tool}|{args_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def summarize_args(args: dict) -> dict:
    summary: dict = {}
    for key, value in args.items():
        if key == "content" and isinstance(value, str):
            summary["content_bytes"] = len(value.encode("utf-8"))
            summary["content_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
            continue
        if isinstance(value, str):
            summary[key] = value[:200]
        elif isinstance(value, (int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, dict):
            summary[key] = {str(k)[:40]: str(v)[:120] for k, v in list(value.items())[:10]}
        else:
            summary[key] = str(value)[:200]
    return sanitize_detail(summary)


def summarize_output(spec: ToolSpec, data: dict) -> dict:
    if spec.name == "fs.read_file":
        return {
            "path": data.get("path"),
            "size": data.get("size"),
            "sha256": data.get("sha256"),
            "chars": len(data.get("content") or ""),
        }
    if spec.name == "fs.list_dir":
        return {
            "path": data.get("path"),
            "count": data.get("count"),
            "truncated": data.get("truncated"),
            "names": [entry.get("name") for entry in (data.get("entries") or [])][:30],
        }
    if spec.name == "fs.write_file":
        return {key: data.get(key) for key in ("path", "mode", "bytes", "sha256", "created")}
    if spec.name == "fs.delete_file":
        return {key: data.get(key) for key in ("path", "deleted", "bytes", "sha256")}
    if spec.name == "http.request":
        return {
            "url": data.get("url"),
            "status": data.get("status"),
            "bytes": data.get("bytes"),
            "content_type": data.get("content_type"),
            "sha256": data.get("sha256"),
            "redirects": data.get("redirects"),
        }
    text = json.dumps(data, ensure_ascii=False, default=str)
    return {"preview": text[:800], "bytes": len(text.encode("utf-8"))}


def _emit(ctx: ToolContext, status: str, payload: dict) -> None:
    if ctx.task is None:
        return
    ctx.session.add(TaskEvent(
        task_id=ctx.task.id,
        task_run_id=ctx.run.id if ctx.run else None,
        type=f"tool.{status}",
        payload=payload,
    ))


def _record(ctx: ToolContext, *, spec: ToolSpec | None, args_summary: dict, args_hash: str,
            idem: str, status: str, risk: str, call_index: int) -> ToolCall:
    row = ToolCall(
        id=ctx.tool_call_id or uuid.uuid4().hex[:24],
        owner_id=ctx.owner_id,
        company_id=ctx.company.id,
        task_id=ctx.task.id if ctx.task else None,
        task_run_id=ctx.run.id if ctx.run else None,
        agent_run_id=None,
        employee_id=ctx.employee.id,
        step_id=ctx.step_id,
        call_index=call_index,
        tool_name=spec.name if spec else "unknown",
        category=spec.category if spec else "",
        risk_level=risk,
        status=status,
        args_summary=sanitize_detail(args_summary),
        args_hash=args_hash,
        idempotency_key=idem,
        workspace_id=(args_summary.get("workspace_id") if isinstance(args_summary, dict) else None),
        output_summary={},
    )
    ctx.session.add(row)
    ctx.session.flush()
    ctx.tool_call_id = row.id
    return row


def _finish(
    ctx: ToolContext, row: ToolCall, *, status: str, error_code: str | None = None,
    error_message: str | None = None, output: dict | None = None, truncated: bool = False,
    output_bytes: int = 0, duration_ms: int = 0, resolved_path: str = "",
) -> None:
    row.status = status
    row.error_code = error_code
    row.error_message = (error_message or "")[:500] if error_message else None
    row.output_summary = sanitize_detail(output or {})
    row.truncated = truncated
    row.output_bytes = output_bytes
    row.duration_ms = duration_ms
    if resolved_path:
        row.resolved_path = resolved_path[:512]
    if status in ("succeeded", "failed", "denied", "timeout"):
        row.ended_at = _now()
    write_audit(
        ctx.session, ctx.owner_id,
        action="tool.call",
        target_type="tool_call", target_id=row.id,
        actor_type="agent", actor_id=ctx.employee.id,
        detail={
            "tool": row.tool_name, "status": status, "risk": row.risk_level,
            "error_code": error_code, "duration_ms": duration_ms,
            "workspace_id": row.workspace_id, "approval_id": row.approval_id,
            "task_id": row.task_id, "step_id": row.step_id,
        },
        request_id=ctx.request_id,
        commit=False,
    )
    _emit(ctx, status, {
        "tool_call_id": row.id, "tool": row.tool_name, "status": status,
        "risk": row.risk_level, "error_code": error_code,
        "duration_ms": duration_ms, "step_id": ctx.step_id,
    })
    ctx.session.commit()


def _outcome(row: ToolCall, **extra) -> ToolOutcome:
    return ToolOutcome(
        status=row.status, tool_call_id=row.id,
        output={"tool": row.tool_name, **(row.output_summary or {})},
        error_code=row.error_code, error_message=row.error_message,
        truncated=row.truncated, duration_ms=row.duration_ms, **extra,
    )


async def invoke_tool(
    ctx: ToolContext,
    tool_name: str,
    raw_args: dict | None,
    *,
    call_index: int | None = None,
) -> ToolOutcome:
    call_index = ctx.call_index if call_index is None else call_index
    ctx.call_index = call_index
    # 只有"审批恢复"才复用既有 tool_call 记录；普通连续调用必须各自新建
    if not ctx.approved:
        ctx.tool_call_id = None
    args = raw_args if isinstance(raw_args, dict) else {}
    args_summary = summarize_args(args)
    args_hash = _hash_args(args)
    idem = _idempotency_key(ctx, tool_name, args_hash, call_index)

    try:
        spec = get_spec(tool_name)
    except DomainError as exc:
        row = _record(
            ctx, spec=None, args_summary=args_summary, args_hash=args_hash, idem=idem,
            status="denied", risk="critical", call_index=call_index,
        )
        _finish(ctx, row, status="denied", error_code=exc.code, error_message=exc.message)
        return _outcome(row)

    risk = spec.risk
    try:
        args = validate_args(spec.params, args, tool=tool_name)
    except DomainError as exc:
        row = _record(
            ctx, spec=spec, args_summary=args_summary, args_hash=args_hash, idem=idem,
            status="denied", risk=risk, call_index=call_index,
        )
        _finish(ctx, row, status="denied", error_code=exc.code, error_message=exc.message)
        return _outcome(row)

    decision = decide(ctx, spec, args)
    risk = decision.risk
    if not decision.allowed:
        row = _record(
            ctx, spec=spec, args_summary=args_summary, args_hash=args_hash, idem=idem,
            status="denied", risk=risk, call_index=call_index,
        )
        _finish(
            ctx, row, status="denied", error_code=decision.code,
            error_message=decision.message, resolved_path=decision.resolved_path,
        )
        return _outcome(row)

    # 幂等：同一 task/step/call_index/参数已成功过 → 直接复用，不重复产生副作用
    existing = ctx.session.query(ToolCall).filter(
        ToolCall.idempotency_key == idem, ToolCall.status == "succeeded"
    ).first()
    if existing is not None and existing.id != ctx.tool_call_id:
        return ToolOutcome(
            status="succeeded", tool_call_id=existing.id,
            output={"tool": existing.tool_name, **(existing.output_summary or {}), "reused": True},
            truncated=existing.truncated, duration_ms=0,
        )

    if decision.requires_approval and not ctx.approved:
        row = ctx.session.get(ToolCall, ctx.tool_call_id) if ctx.tool_call_id else None
        if row is None:
            row = _record(
                ctx, spec=spec, args_summary=args_summary, args_hash=args_hash, idem=idem,
                status="awaiting_approval", risk=risk, call_index=call_index,
            )
        row.status = "awaiting_approval"
        row.risk_level = risk
        if decision.resolved_path:
            row.resolved_path = decision.resolved_path[:512]
        from packages.tasks.approvals import create_approval

        approval = create_approval(
            ctx.session, ctx.task, ctx.run, gate="tool_call",
            requested_by=ctx.employee.id,
            context={
                "tool": spec.name,
                "risk": risk,
                "args": sanitize_detail(args_summary),
                "workspace_id": decision.workspace_id,
                "step_id": ctx.step_id,
                "reason": f"{spec.name} 风险等级 {risk}，需要人工审批",
            },
        )
        approval.tool_call_id = row.id
        row.approval_id = approval.id
        ctx.session.commit()
        _emit(ctx, "awaiting_approval", {
            "tool_call_id": row.id, "tool": spec.name, "status": "awaiting_approval",
            "risk": risk, "approval_id": approval.id, "step_id": ctx.step_id,
        })
        write_audit(
            ctx.session, ctx.owner_id, action="tool.approval_requested",
            target_type="tool_call", target_id=row.id, actor_type="agent",
            actor_id=ctx.employee.id,
            detail={"tool": spec.name, "approval_id": approval.id, "risk": risk},
            request_id=ctx.request_id, commit=False,
        )
        ctx.session.commit()
        return ToolOutcome(
            status="awaiting_approval", tool_call_id=row.id,
            output={"tool": spec.name}, requires_approval=True,
            approval_id=approval.id, error_code="TOOL_APPROVAL_REQUIRED",
            error_message="工具调用需要人工审批",
        )

    row = ctx.session.get(ToolCall, ctx.tool_call_id) if ctx.tool_call_id else None
    if row is None:
        row = _record(
            ctx, spec=spec, args_summary=args_summary, args_hash=args_hash, idem=idem,
            status="running", risk=risk, call_index=call_index,
        )
    row.status = "running"
    row.started_at = _now()
    if decision.resolved_path:
        row.resolved_path = decision.resolved_path[:512]
    if decision.workspace_id:
        row.workspace_id = decision.workspace_id
    ctx.session.commit()

    started = time.perf_counter()
    try:
        data = await asyncio.wait_for(spec.handler(ctx, args), timeout=spec.timeout_s)
    except asyncio.TimeoutError:
        duration = int((time.perf_counter() - started) * 1000)
        _finish(
            ctx, row, status="timeout", error_code="TOOL_TIMEOUT",
            error_message=f"工具 {spec.name} 超过 {spec.timeout_s}s", duration_ms=duration,
        )
        return _outcome(row)
    except DomainError as exc:
        duration = int((time.perf_counter() - started) * 1000)
        status = "denied" if exc.code in DENY_CODES else "failed"
        _finish(
            ctx, row, status=status, error_code=exc.code, error_message=exc.message,
            duration_ms=duration,
        )
        return _outcome(row)
    except PathDenied as exc:
        duration = int((time.perf_counter() - started) * 1000)
        _finish(
            ctx, row, status="denied", error_code=exc.code, error_message=exc.message,
            duration_ms=duration,
        )
        return _outcome(row)
    except Exception as exc:  # noqa: BLE001 - 工具边界必须兜底，不能把异常抛进执行器
        duration = int((time.perf_counter() - started) * 1000)
        _finish(
            ctx, row, status="failed", error_code="TOOL_EXEC_FAILED",
            error_message=f"{type(exc).__name__}: {exc}"[:400], duration_ms=duration,
        )
        return _outcome(row)

    duration = int((time.perf_counter() - started) * 1000)
    encoded = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    truncated = False
    if len(encoded) > spec.max_output_bytes:
        truncated = True
        for key in ("content", "body", "body_base64"):
            if isinstance(data.get(key), str):
                data[key] = data[key][: max(0, spec.max_output_bytes // 2)] + "\n…[truncated]"
        encoded = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    _finish(
        ctx, row, status="succeeded", output=summarize_output(spec, data),
        truncated=truncated, output_bytes=len(encoded), duration_ms=duration,
        resolved_path=decision.resolved_path,
    )
    outcome = _outcome(row)
    outcome.output["data"] = sanitize_detail(data)
    outcome.output["tool"] = spec.name
    return outcome
