"""审计日志：只增不改；detail 落库前强制脱敏。

脱敏两条规则（宁可多删，不可漏记）：
1. 敏感键名（api_key/token/secret/password/authorization…）→ 固定占位符；
2. 任意字符串值命中 sk-xxx / Bearer xxx 形态 → 替换为占位符。

`api_key_ref` 属于引用（env:VAR / dpapi:x / keyring:s:u），不是密钥本体，保留可审计。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import AuditLog

REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = {
    "api_key", "apikey", "api_key_value", "api_key_plain", "key",
    "token", "access_token", "refresh_token", "secret", "client_secret",
    "password", "passwd", "authorization", "bearer", "credential",
}
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
]


def _redact_text(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def sanitize_detail(value: Any) -> Any:
    """递归脱敏：dict/list/tuple/str 全覆盖，其他类型原样返回。"""
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.strip().lower() in _SENSITIVE_KEYS:
                cleaned[key] = REDACTED
            else:
                cleaned[key] = sanitize_detail(item)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize_detail(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


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
    commit: bool = True,
) -> AuditLog:
    """追加一条审计。

    commit=False 用于调用方已开启显式事务（如配置导入），由外层统一提交/回滚，
    保证“业务变更 + 审计”要么同时落库、要么同时消失。
    """
    row = AuditLog(
        owner_id=owner_id, actor_type=actor_type, actor_id=actor_id, action=action,
        target_type=target_type, target_id=target_id,
        detail=sanitize_detail(detail or {}), request_id=request_id,
    )
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    else:
        session.flush()
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
