"""提示词接口 API-25、30..33（版本创建与激活落审计）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, get_actor, get_db
from packages.prompts.service import (
    activate_revision,
    create_revision,
    diff_against_previous,
    get_revision,
    list_revisions,
    read_content,
    serialize_revision,
)

router = APIRouter(tags=["prompts"])


class PromptCreate(BaseModel):
    content: str = Field(min_length=1)
    note: str = ""


@router.get("/employees/{employee_id}/prompts")
def list_prompts_endpoint(
    employee_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    return [serialize_revision(r) for r in list_revisions(db, actor.owner_id, employee_id)]


@router.post("/employees/{employee_id}/prompts", status_code=status.HTTP_201_CREATED)
def create_prompt_endpoint(
    employee_id: str,
    payload: PromptCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    revision = create_revision(
        db, actor.owner_id, employee_id,
        content=payload.content, note=payload.note, created_by=actor.actor_id,
    )
    audit_action(
        db, actor, request,
        action="prompt.version.create", target_type="prompt", target_id=revision.id,
        detail={
            "employee_id": employee_id,
            "version": revision.version,
            "content_hash": revision.content_hash,
            "file_path": revision.file_path,
            "note": revision.note,
            "is_active": revision.is_active,
        },
    )
    return serialize_revision(revision)


@router.get("/prompts/{revision_id}")
def get_prompt_endpoint(
    revision_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    revision = get_revision(db, actor.owner_id, revision_id)
    data = serialize_revision(revision)
    data["content"] = read_content(revision)
    return data


@router.post("/prompts/{revision_id}/activate")
def activate_prompt_endpoint(
    revision_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    target = get_revision(db, actor.owner_id, revision_id)
    previous = [
        item.version
        for item in list_revisions(db, actor.owner_id, target.employee_id)
        if item.is_active and item.id != target.id
    ]
    revision = activate_revision(db, actor.owner_id, revision_id)
    audit_action(
        db, actor, request,
        action="prompt.version.activate", target_type="prompt", target_id=revision.id,
        detail={
            "employee_id": revision.employee_id,
            "version": revision.version,
            "previous_active_versions": previous,
        },
    )
    return serialize_revision(revision)


@router.get("/prompts/{revision_id}/diff")
def diff_prompt_endpoint(
    revision_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    return {"diff": diff_against_previous(db, actor.owner_id, revision_id)}
