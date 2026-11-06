"""系统级控制（M3-E）：全局工具执行紧急开关（kill switch）。

- GET  /api/v1/system/tool-execution：查询当前状态；
- POST /api/v1/system/tool-execution {"enabled": bool}：立即生效（进程级），写审计。

开关是进程内存态：立即停止一切工具调用，进程重启后回到
AGENTOS_TOOL_EXECUTION 决定的初始值（持久关闭请用环境变量）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, get_actor, get_db
from packages.permissions.audit import write_audit
from packages.shared.errors import DomainError
from packages.tools.policy import set_tool_execution, tool_execution_state

router = APIRouter(tags=["system"])


class ToolExecutionSwitch(BaseModel):
    enabled: bool


@router.get("/system/tool-execution")
def get_tool_execution(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    state = tool_execution_state()
    write_audit(
        db, actor.owner_id,
        action="system.tool_execution_view",
        target_type="system", target_id="tool-execution",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        detail={"enabled": state["enabled"]},
    )
    return state


@router.post("/system/tool-execution")
def set_tool_execution_endpoint(
    payload: ToolExecutionSwitch,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    state = tool_execution_state()
    # 诚实语义：进程级紧急开关只能"停止"（在 env 之上加杀），不能强制开启 env=off 的系统。
    # env off 时请求 enabled=true 必然是静默 no-op——明确拒绝并给出修复指引，
    # 而不是返回 200 + enabled=false 让前端永远显示"关闭"。
    if payload.enabled and not state["env_enabled"]:
        raise DomainError(
            "TOOL_EXECUTION_BLOCKED_BY_ENV",
            "全局工具执行由环境变量 AGENTOS_TOOL_EXECUTION 控制（当前 off）。"
            "进程级紧急开关只能停止执行，无法强制开启；"
            "请在 .env 设置 AGENTOS_TOOL_EXECUTION=on 并重启后端后重试。",
            409,
            {"state": state},
        )
    set_tool_execution(payload.enabled)
    state = tool_execution_state()
    write_audit(
        db, actor.owner_id,
        action="system.tool_execution_changed",
        target_type="system", target_id="tool-execution",
        actor_type=actor.actor_type, actor_id=actor.actor_id,
        detail={"enabled": payload.enabled, "state": state},
        request_id=getattr(request.state, "request_id", "-"),
    )
    return state
