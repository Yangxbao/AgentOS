"""API 层审计入口：统一补 request_id / actor，并强制走脱敏。

为什么放在 API 层：request_id 只在这里可得。业务服务保持框架无关，
审计由路由在业务成功后追加；导入这类需要整体事务的场景改为服务内写入（commit=False）。
"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext
from apps.api.errors import request_id_of
from packages.permissions.audit import write_audit


def audit_action(
    session: Session,
    actor: ActorContext,
    request: Request,
    *,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict | None = None,
    commit: bool = True,
):
    return write_audit(
        session,
        actor.owner_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail or {},
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        request_id=request_id_of(request),
        commit=commit,
    )
