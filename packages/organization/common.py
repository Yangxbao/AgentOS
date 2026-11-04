"""组织域公共工具：404、乐观锁、UTC 序列化、名称唯一性。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.shared.errors import DomainError

T = TypeVar("T")


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def require(condition: bool, code: str, message: str, status_code: int = 409, detail: dict | None = None) -> None:
    if not condition:
        raise DomainError(code, message, status_code, detail)


def not_found(entity: str, entity_id: str) -> DomainError:
    return DomainError("NOT_FOUND", f"{entity} 不存在：{entity_id}", 404)


def get_or_404(session: Session, model: type[T], entity_id: str, owner_id: str, entity_label: str) -> T:
    obj = session.get(model, entity_id)
    if obj is None or getattr(obj, "owner_id", None) != owner_id:
        raise not_found(entity_label, entity_id)
    return obj


def check_version(expected_updated_at: str | None, actual: datetime | None, entity_label: str = "资源") -> None:
    """乐观并发：客户端带回上次读到的 updated_at，不一致返回 409。"""
    if not expected_updated_at or actual is None:
        return
    try:
        expected = datetime.fromisoformat(expected_updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError("VALIDATION_ERROR", "expected_updated_at 必须是 ISO-8601 时间", 422) from exc
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=timezone.utc)
    actual_utc = actual if actual.tzinfo else actual.replace(tzinfo=timezone.utc)
    if abs((actual_utc - expected).total_seconds()) > 0.001:
        raise DomainError(
            "CONFLICT_STALE",
            f"{entity_label}已被其他操作修改，请刷新后重试",
            409,
            {"expected": expected_updated_at, "actual": iso_utc(actual)},
        )


def ensure_unique_name(
    session: Session,
    model: type[T],
    owner_id: str,
    name: str,
    *,
    company_id: str | None = None,
    exclude_id: str | None = None,
    code: str = "BR_NAME_TAKEN",
    entity_label: str = "名称",
) -> None:
    stmt = select(model).where(getattr(model, "owner_id") == owner_id, getattr(model, "name") == name)
    if company_id is not None:
        stmt = stmt.where(getattr(model, "company_id") == company_id)
    stmt = stmt.where(getattr(model, "id") != exclude_id) if exclude_id else stmt
    if session.execute(stmt).first() is not None:
        raise DomainError(code, f"{entity_label}已存在：{name}", 409)
