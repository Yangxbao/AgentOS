"""审计日志：只增不改。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import AuditLog


def write_audit(
    session: Session,
    owner_id: str,
    *,
    action: str,
    target_type: str,
    target_id: str,
    detail: dict | None = None,
    actor_type: str = "user",
    actor_id: str = "local",
    request_id: str = "-",
) -> AuditLog:
    row = AuditLog(
        owner_id=owner_id, actor_type=actor_type, actor_id=actor_id, action=action,
        target_type=target_type, target_id=target_id, detail=detail or {}, request_id=request_id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def serialize_audit(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": row.detail,
        "request_id": row.request_id,
        "created_at": iso_utc(row.created_at),
    }


def list_audit(
    session: Session,
    owner_id: str,
    *,
    actor_type: str | None = None,
    action: str | None = None,
    target_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog).where(AuditLog.owner_id == owner_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    total = len(session.execute(stmt).scalars().all())
    rows = session.execute(stmt.order_by(AuditLog.id.desc()).offset(offset).limit(limit)).scalars().all()
    return list(rows), total
