"""配置导入导出 API-42..44（zip 原样上传，避免 multipart 依赖）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from apps.api.deps import ActorContext, get_actor, get_db
from packages.config_io import export_company, import_company, inspect_bundle

router = APIRouter(tags=["config"])


@router.get("/companies/{company_id}/export")
def export_endpoint(
    company_id: str, db: Session = Depends(get_db), actor: ActorContext = Depends(get_actor)
):
    data = export_company(db, actor.owner_id, company_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="agentos-{company_id}.zip"'},
    )


@router.post("/config/import")
async def import_endpoint(
    request: Request,
    dry_run: bool = False,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    data = await request.body()
    if not data:
        from packages.shared.errors import DomainError

        raise DomainError("IMPORT_EMPTY", "请求体为空，请上传 zip 文件", 422)
    if dry_run:
        return inspect_bundle(db, actor.owner_id, data)
    return import_company(db, actor.owner_id, data, strategy="rename")
