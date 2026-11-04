"""模型连接接口 API-34..39。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, get_actor, get_db
from apps.api.schemas.people import ConnectionCreate, ConnectionUpdate
from packages.model_gateway import catalog
from packages.organization import connections as service

router = APIRouter(tags=["model-connections"])


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
    return service.serialize_connection(conn)


@router.patch("/model-connections/{connection_id}")
def update_connection_endpoint(
    connection_id: str,
    payload: ConnectionUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    conn = service.update_connection(
        db, actor.owner_id, connection_id,
        name=payload.name, model=payload.model, api_key_ref=payload.api_key_ref,
        base_url=payload.base_url, timeout_s=payload.timeout_s,
        max_retries=payload.max_retries, enabled=payload.enabled,
        expected_updated_at=payload.expected_updated_at,
    )
    return service.serialize_connection(conn)


@router.delete("/model-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection_endpoint(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    service.delete_connection(db, actor.owner_id, connection_id)
    return None


@router.post("/model-connections/{connection_id}/test")
async def test_connection_endpoint(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return await service.test_connection(db, actor.owner_id, connection_id)


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
