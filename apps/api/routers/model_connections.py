"""模型连接接口 API-34..39（配置变更与启停落审计，绝不记录密钥值）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, get_actor, get_db
from apps.api.schemas.people import ConnectionCreate, ConnectionUpdate
from packages.model_gateway import catalog
from packages.organization import connections as service

router = APIRouter(tags=["model-connections"])

TRACKED_FIELDS = ("name", "model", "base_url", "timeout_s", "max_retries", "enabled")


@router.get("/companies/{company_id}/model-connections")
def list_connections_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return [service.serialize_connection(c) for c in service.list_connections(db, actor.owner_id, company_id)]


@router.post(
    "/companies/{company_id}/model-connections",
    status_code=status.HTTP_201_CREATED,
)
def create_connection_endpoint(
    company_id: str,
    payload: ConnectionCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conn = service.create_connection(
        db, actor.owner_id, company_id,
        name=payload.name, provider=payload.provider, model=payload.model,
        api_key_ref=payload.api_key_ref, base_url=payload.base_url,
        timeout_s=payload.timeout_s, max_retries=payload.max_retries,
        model_list_source=payload.model_list_source,
    )
    audit_action(
        db, actor, request,
        action="model_connection.create", target_type="model_connection", target_id=conn.id,
        detail={
            "name": conn.name, "provider": conn.provider, "model": conn.model,
            "api_key_ref": conn.api_key_ref,  # 只存引用（env:/dpapi:/keyring:）
            "base_url": conn.base_url, "enabled": conn.enabled,
        },
    )
    return service.serialize_connection(conn)


@router.patch("/model-connections/{connection_id}")
def update_connection_endpoint(
    connection_id: str,
    payload: ConnectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    before = service.get_connection(db, actor.owner_id, connection_id)
    before_snapshot = {key: getattr(before, key) for key in TRACKED_FIELDS}
    before_key_ref = before.api_key_ref
    conn = service.update_connection(
        db, actor.owner_id, connection_id,
        name=payload.name, model=payload.model, api_key_ref=payload.api_key_ref,
        base_url=payload.base_url, timeout_s=payload.timeout_s,
        max_retries=payload.max_retries, enabled=payload.enabled,
        expected_updated_at=payload.expected_updated_at,
    )
    after_snapshot = {key: getattr(conn, key) for key in TRACKED_FIELDS}
    changed = [key for key in TRACKED_FIELDS if before_snapshot[key] != after_snapshot[key]]
    detail: dict = {
        "changed": changed,
        "before": {key: before_snapshot[key] for key in changed},
        "after": {key: after_snapshot[key] for key in changed},
    }
    if before_key_ref != conn.api_key_ref:
        # 凭据引用本身可能含路径信息，只记录“换过”，不记录取值
        detail["credential_ref_changed"] = True
    audit_action(
        db, actor, request,
        action="model_connection.update", target_type="model_connection", target_id=conn.id,
        detail=detail,
    )
    return service.serialize_connection(conn)


@router.delete("/model-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection_endpoint(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conn = service.get_connection(db, actor.owner_id, connection_id)
    snapshot = {"name": conn.name, "provider": conn.provider, "model": conn.model}
    service.delete_connection(db, actor.owner_id, connection_id)
    audit_action(
        db, actor, request,
        action="model_connection.delete", target_type="model_connection", target_id=connection_id,
        detail=snapshot,
    )
    return None


@router.post("/model-connections/{connection_id}/test")
async def test_connection_endpoint(
    connection_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = await service.test_connection(db, actor.owner_id, connection_id)
    audit_action(
        db, actor, request,
        action="model_connection.test", target_type="model_connection", target_id=connection_id,
        detail={"ok": True, "latency_ms": result.get("latency_ms")},
    )
    return result


@router.get("/model-connections/{connection_id}/models")
def models_endpoint(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return service.models_for_connection(db, actor.owner_id, connection_id)


@router.get("/model-providers")
def providers_endpoint():
    """供应商与静态模型目录（前端下拉用）。"""
    return {
        "providers": [
            {
                "id": provider.id,
                "label": provider.label,
                "api_key_env": provider.api_key_env,
                "models": catalog.list_models(provider.id),
            }
            for provider in catalog.PROVIDERS.values()
        ]
    }
