"""长期记忆接口（M3-C，M3-11..14）。

- POST  /companies/{cid}/memories        人工写入（任意作用域）
- GET   /companies/{cid}/memories        列表（scope/employee 过滤）
- GET   /memories/{id}                   详情
- PATCH /memories/{id}                   更新（内容重脱敏 + FTS 同步）
- DELETE /memories/{id}                  软删（检索不到、FTS 无残留）
- POST  /memories/{id}/promote           提升 employee → project/company（仅本地人工）
- GET   /memories/search                 检索（FTS5，降级 LIKE）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, get_actor, get_db
from apps.api.schemas.memory import MemoryCreate, MemoryPromote, MemoryUpdate
from packages.memory import service as memory_service

router = APIRouter(tags=["memory"])


@router.post("/companies/{company_id}/memories", status_code=201)
def create_memory_endpoint(
    company_id: str,
    payload: MemoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = memory_service.create_memory(
        db, actor.owner_id,
        scope=payload.scope,
        company_id=company_id,  # employee 作用域也记公司（列表/共享过滤用），隔离靠 employee_id
        employee_id=payload.employee_id,
        project_task_id=payload.project_task_id,
        kind=payload.kind, title=payload.title, content=payload.content,
        tags=payload.tags, created_by=actor.actor_id, created_by_type="user",
    )
    audit_action(
        db, actor, request, action="memory.api.create",
        target_type="memory_item", target_id=result["id"],
        detail={"scope": result["scope"], "duplicate": result.get("duplicate")},
    )
    return result


@router.get("/companies/{company_id}/memories")
def list_memories_endpoint(
    company_id: str,
    scope: str | None = None,
    employee_id: str | None = None,
    status: str = "active",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    items, total = memory_service.list_memories(
        db, actor.owner_id, company_id=company_id, scope=scope,
        employee_id=employee_id, status=status,
        offset=(page - 1) * page_size, limit=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/memories/search")
def search_memories_endpoint(
    q: str = Query(min_length=1, max_length=400),
    company_id: str | None = None,
    scope: str | None = None,
    employee_id: str | None = None,
    top_k: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """本地人工检索（owner 视角可见全部）；员工视角检索走任务执行注入或工具。"""
    items = memory_service.search_memories(
        db, actor.owner_id, query=q, company_id=company_id,
        scope=scope, viewer_employee_id=employee_id, top_k=top_k,
    )
    return {"items": items, "total": len(items)}


@router.get("/memories/{memory_id}")
def get_memory_endpoint(
    memory_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    return memory_service.get_memory(db, actor.owner_id, memory_id)


@router.patch("/memories/{memory_id}")
def update_memory_endpoint(
    memory_id: str,
    payload: MemoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = memory_service.update_memory(
        db, actor.owner_id, memory_id, payload.model_dump(exclude_none=True),
        updated_by=actor.actor_id,
    )
    audit_action(
        db, actor, request, action="memory.api.update",
        target_type="memory_item", target_id=memory_id, detail={},
    )
    return result


@router.delete("/memories/{memory_id}")
def delete_memory_endpoint(
    memory_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = memory_service.delete_memory(db, actor.owner_id, memory_id, deleted_by=actor.actor_id)
    audit_action(
        db, actor, request, action="memory.api.delete",
        target_type="memory_item", target_id=memory_id, detail={},
    )
    return result


@router.post("/memories/{memory_id}/promote")
def promote_memory_endpoint(
    memory_id: str,
    payload: MemoryPromote,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    result = memory_service.promote_memory(
        db, actor.owner_id, memory_id, to_scope=payload.to_scope, promoted_by=actor.actor_id,
    )
    audit_action(
        db, actor, request, action="memory.api.promote",
        target_type="memory_item", target_id=memory_id,
        detail={"to_scope": payload.to_scope},
    )
    return result
