"""模型连接服务（B3，API-34..39）。

安全：只接受凭据引用；测试连接只返回 ok/latency/错误码，绝不回显密钥。
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.agent_core import LiteLLMAdapter
from packages.model_gateway import catalog
from packages.model_gateway.credentials import has_credential, validate_ref
from packages.model_gateway.health import health_cache
from packages.persistence.models import Company, Employee, ModelConnection
from packages.shared.errors import DomainError
from packages.shared.types import new_id

from .common import check_version, get_or_404, iso_utc, require

ERROR_MAP = {
    "AUTH": ("UPSTREAM_AUTH_FAILED", 502),
    "TIMEOUT": ("UPSTREAM_TIMEOUT", 504),
    "OTHER": ("UPSTREAM_ERROR", 502),
}


def serialize_connection(conn: ModelConnection) -> dict:
    return {
        "id": conn.id,
        "company_id": conn.company_id,
        "name": conn.name,
        "provider": conn.provider,
        "model": conn.model,
        "api_key_ref": conn.api_key_ref,
        "has_credential": has_credential(conn.api_key_ref),
        "base_url": conn.base_url,
        "timeout_s": conn.timeout_s,
        "max_retries": conn.max_retries,
        "model_list_source": conn.model_list_source,
        "last_health_check_at": iso_utc(conn.last_health_check_at),
        "last_health_status": conn.last_health_status,
        "last_health_latency_ms": conn.last_health_latency_ms,
        "enabled": conn.enabled,
        "created_at": iso_utc(conn.created_at),
        "updated_at": iso_utc(conn.updated_at),
    }


def _company(session: Session, owner_id: str, company_id: str) -> Company:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    if company.status == "archived":
        raise DomainError("BR_COMPANY_ARCHIVED", "公司已归档，不能修改模型连接", 409)
    return company


def _duplicate(
    session: Session,
    company_id: str,
    provider: str,
    model: str,
    base_url: str | None,
    exclude: str | None = None,
) -> None:
    stmt = select(ModelConnection).where(
        ModelConnection.company_id == company_id,
        ModelConnection.provider == provider,
        ModelConnection.model == model,
        ModelConnection.base_url == base_url,
    )
    if exclude:
        stmt = stmt.where(ModelConnection.id != exclude)
    if session.execute(stmt).first() is not None:
        raise DomainError("BR_MODEL_CONNECTION_DUPLICATE", "同一公司下已存在相同的模型连接", 409)


def create_connection(
    session: Session,
    owner_id: str,
    company_id: str,
    *,
    name: str,
    provider: str,
    model: str = "",
    api_key_ref: str,
    base_url: str | None = None,
    timeout_s: int = 60,
    max_retries: int = 2,
    model_list_source: str = "static",
) -> ModelConnection:
    _company(session, owner_id, company_id)
    provider_info = catalog.provider_info(provider)
    if provider_info is None:
        raise DomainError("BR_PROVIDER_UNKNOWN", f"未知供应商：{provider}", 422,
                          {"providers": catalog.provider_ids()})
    ref = validate_ref(api_key_ref)
    clean_model = (model or "").strip()
    if not clean_model:
        models = catalog.list_models(provider)
        if not models:
            raise DomainError("VALIDATION_ERROR", "该供应商需要手动填写模型", 422)
        clean_model = models[0]["id"]

    clean_name = name.strip()
    require(bool(clean_name), "VALIDATION_ERROR", "连接名称不能为空", 422)
    _duplicate(session, company_id, provider, clean_model, base_url)

    conn = ModelConnection(
        id=new_id(), owner_id=owner_id, company_id=company_id, name=clean_name,
        provider=provider, model=clean_model, api_key_ref=ref, base_url=base_url,
        timeout_s=timeout_s, max_retries=max_retries, model_list_source=model_list_source,
        enabled=True,
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)
    return conn


def list_connections(session: Session, owner_id: str, company_id: str) -> list[ModelConnection]:
    _company(session, owner_id, company_id)
    return list(session.execute(
        select(ModelConnection).where(ModelConnection.company_id == company_id).order_by(ModelConnection.name)
    ).scalars().all())


def get_connection(session: Session, owner_id: str, connection_id: str) -> ModelConnection:
    return get_or_404(session, ModelConnection, connection_id, owner_id, "模型连接")


def update_connection(
    session: Session,
    owner_id: str,
    connection_id: str,
    *,
    name: str | None = None,
    model: str | None = None,
    api_key_ref: str | None = None,
    base_url: str | None = None,
    timeout_s: int | None = None,
    max_retries: int | None = None,
    enabled: bool | None = None,
    expected_updated_at: str | None = None,
) -> ModelConnection:
    conn = get_connection(session, owner_id, connection_id)
    check_version(expected_updated_at, conn.updated_at, "模型连接")
    changed_config = False
    if name is not None:
        conn.name = name.strip()
        require(bool(conn.name), "VALIDATION_ERROR", "连接名称不能为空", 422)
    if model is not None and model.strip() and model.strip() != conn.model:
        conn.model = model.strip()
        changed_config = True
    if api_key_ref is not None:
        conn.api_key_ref = validate_ref(api_key_ref)
        changed_config = True
    if base_url is not None and base_url != conn.base_url:
        conn.base_url = base_url or None
        changed_config = True
    if timeout_s is not None:
        conn.timeout_s = timeout_s
    if max_retries is not None:
        conn.max_retries = max_retries
    if enabled is not None:
        conn.enabled = enabled
    if changed_config:
        _duplicate(session, conn.company_id, conn.provider, conn.model, conn.base_url, exclude=conn.id)
        health_cache.invalidate(conn.id)
    session.commit()
    session.refresh(conn)
    return conn


def delete_connection(session: Session, owner_id: str, connection_id: str) -> None:
    conn = get_connection(session, owner_id, connection_id)
    refs = session.execute(
        select(Employee).where(
            (Employee.primary_model_id == conn.id) | (Employee.fallback_model_id == conn.id),
            Employee.deleted_at.is_(None),
        )
    ).scalars().all()
    if refs:
        raise DomainError(
            "BR_MODEL_IN_USE",
            f"该连接仍被 {len(refs)} 名员工引用，请先切换模型或停用连接",
            409,
            {"employee_ids": [e.id for e in refs]},
        )
    session.delete(conn)
    session.commit()


def _classify_error(message: str) -> str:
    text = message.lower()
    if "401" in text or "auth" in text or "api key" in text or "unauthorized" in text:
        return "AUTH"
    if "timeout" in text or "timed out" in text:
        return "TIMEOUT"
    return "OTHER"


async def test_connection(session: Session, owner_id: str, connection_id: str) -> dict:
    conn = get_connection(session, owner_id, connection_id)
    from packages.model_gateway.credentials import resolve_ref

    api_key = resolve_ref(conn.api_key_ref)
    adapter = LiteLLMAdapter(
        model=conn.model, timeout=float(conn.timeout_s), api_key=api_key,
        base_url=conn.base_url, max_retries=0,
    )
    started = time.perf_counter()
    status = await adapter.health_check()
    latency = int((time.perf_counter() - started) * 1000)

    from datetime import datetime, timezone

    conn.last_health_check_at = datetime.now(timezone.utc)
    conn.last_health_latency_ms = latency
    conn.last_health_status = "ok" if status.ok else "fail"
    session.commit()
    health_cache.put(
        health_cache.key(conn.id, health_cache.fingerprint(conn.provider, conn.model, conn.base_url, conn.api_key_ref)),
        status.ok, latency,
    )

    if status.ok:
        return {
            "ok": True,
            "latency_ms": latency,
            "model": conn.model,
            "checked_at": iso_utc(conn.last_health_check_at),
        }
    kind = _classify_error(status.detail)
    code, http = ERROR_MAP[kind]
    raise DomainError(code, f"连接测试失败：{status.detail[:200]}", http,
                      {"kind": kind, "latency_ms": latency})


def models_for_connection(session: Session, owner_id: str, connection_id: str) -> dict:
    conn = get_connection(session, owner_id, connection_id)
    return {
        "provider": conn.provider,
        "source": conn.model_list_source,
        "models": catalog.list_models(conn.provider),
    }


def connection_health(session: Session, conn: ModelConnection) -> tuple[bool | None, str]:
    """读取缓存健康状态，供员工详情/派工使用；unknown 表示尚无数据（不阻塞）。"""
    key = health_cache.key(
        conn.id, health_cache.fingerprint(conn.provider, conn.model, conn.base_url, conn.api_key_ref)
    )
    entry = health_cache.get(key)
    if entry is not None:
        return entry.ok, "cache"
    if conn.last_health_status in ("ok", "fail"):
        return conn.last_health_status == "ok", "db"
    return None, "unknown"
