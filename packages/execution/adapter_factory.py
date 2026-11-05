"""执行体工厂：真实 / Mock 的显式选择，绝不静默降级。"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from packages.agent_core import LiteLLMAdapter
from packages.model_gateway.credentials import has_credential, resolve_ref
from packages.persistence.models import Employee, ModelConnection
from packages.shared.errors import DomainError

from .mock_adapter import MockAdapter


@dataclass
class AdapterBundle:
    adapter: object
    mode: str
    model: str
    connection_id: str | None
    label: str


def resolve_connection(session: Session, employee: Employee, mode: str) -> ModelConnection | None:
    """主 → 备 → 拒绝。Mock 模式只用于记录，不要求凭据。"""
    candidates: list[ModelConnection] = []
    for connection_id in (employee.primary_model_id, employee.fallback_model_id):
        if not connection_id:
            continue
        connection = session.get(ModelConnection, connection_id)
        if connection is not None and connection.enabled:
            candidates.append(connection)
    if mode == "mock":
        return candidates[0] if candidates else None
    for connection in candidates:
        if has_credential(connection.api_key_ref):
            return connection
    raise DomainError(
        "EXECUTION_MODEL_UNAVAILABLE",
        "员工没有可用的模型连接（连接被停用或凭据缺失）",
        409,
        {"employee_id": employee.id},
    )


def build_adapter(
    session: Session, employee: Employee, mode: str
) -> AdapterBundle:
    connection = resolve_connection(session, employee, mode)
    if mode == "mock":
        delay_ms = 0
        try:
            delay_ms = max(0, int(os.environ.get("AGENTOS_MOCK_DELAY_MS", "0")))
        except ValueError:
            delay_ms = 0
        adapter = MockAdapter(label=employee.name, delay_ms=delay_ms)
        return AdapterBundle(
            adapter=adapter, mode="mock", model=adapter.model,
            connection_id=connection.id if connection else None, label=employee.name,
        )

    if connection is None:  # 理论上 resolve_connection 已抛错，防御性保留
        raise DomainError("EXECUTION_MODEL_UNAVAILABLE", "没有可用的模型连接", 409)
    api_key = resolve_ref(connection.api_key_ref)
    fallback_model = None
    if employee.fallback_model_id:
        fallback = session.get(ModelConnection, employee.fallback_model_id)
        # 仅同供应商才启用 LiteLLM fallback：跨供应商复用同一 api_key 会静默失败
        if fallback is not None and fallback.enabled and fallback.provider == connection.provider:
            fallback_model = fallback.model
    try:
        max_tokens = max(16, int(os.environ.get("AGENTOS_MAX_TOKENS", "1024")))
    except ValueError:
        max_tokens = 1024
    adapter = LiteLLMAdapter(
        model=connection.model,
        fallback_model=fallback_model,
        timeout=float(connection.timeout_s),
        api_key=api_key,
        base_url=connection.base_url,
        max_retries=connection.max_retries,
        max_tokens=max_tokens,
    )
    return AdapterBundle(
        adapter=adapter, mode="real", model=connection.model,
        connection_id=connection.id, label=employee.name,
    )
